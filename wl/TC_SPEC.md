# UFS workload TC 설계서 (v1)

스마트폰에서 잰 UFS trace 를 **파일 동작**으로 바꿔 기기 `/data`(f2fs) 위에서 다시 재생하고, 재생 중 잡은 trace 를 원본과 자동으로 비교하는 TC 예요.
이 문서만 보고 다른 프로젝트에서 같은 TC 를 다시 만들 수 있게, 규칙·상수·형식·시행착오를 전부 적었어요. 코드 위치는 이 저장소의 `wl/` 이고, 실행 방법은 `GUIDE.md` 9절이에요.

- 기준 기기: OnePlus CPH2749, Android 16, kernel 6.12, UFS, `/data` = f2fs
- 버전: v1 (git 태그 `wl-v1`, `wl/metrics.py` 의 `VERSION`)
- 결과 수준: 2시간 하루 TC 에서 전체 지표 16/16 통과, 구간별 통과 76~77%, 늦은 request 0.13~0.18% (12절)

---

## 1. 핵심 아이디어

블록 request 를 그대로 다시 내는 TC(LBA replay)는 FS 가 만드는 I/O 를 재현하지 못해요. f2fs 의 node·Checkpoint·Flush·Discard·GC 는 앱 동작의 결과라서, 블록을 그대로 내면 FS I/O 가 두 번 나오거나(원본 몫 + 재생이 만든 몫) 아예 안 나와요.

그래서 이렇게 해요.

1. 원본 trace 의 request 를 **앱이 한 파일 동작**(pread, pwrite, fsync, O_DIRECT, atomic write, unlink, 디렉터리 fsync)으로 되돌려요.
2. **FS 가 만든 request 는 재생하지 않아요.** 재생 중 f2fs 가 스스로 만들게 두고, 그 양을 원본과 비교해요.
3. 재생은 원본 시각에 맞춰 **열린 루프**(open loop)로 내요. 앞 request 가 늦게 끝나도 다음 request 는 제 시각에 나가요.
4. 재생 trace 를 원본과 **구간마다 같은 지표로** 재서 판정해요. 이 비교가 TC 실행의 기본 단계예요.

```
원본 측정 trace (parquet)
   │ segments.py : request 분류 → 파일 동작 조각 (.npz)
   ▼
조각 (시나리오-회차마다 하나)
   │ gen_tc.py  : seq(조각 이어 붙이기) 또는 day(하루 사용 흐름)
   ▼
tc.bin + manifest.json (timeline)
   │ run_tc.py  : push → prep → Discard 대기 → trace 시작 → uxwl run → trace 끝
   ▼
TC trace (parquet) + result.json
   │ compare.py : 시각 맞추기 → 구간마다 원본 조각과 같은 지표 → 판정
   ▼
compare.json, history.jsonl
```

---

## 2. 입력: 원본 trace

### 2.1 측정 조건 (원본·TC 모두 같아야 해요)
- **배터리 + 무선 adb.** USB 전원이면 deviceidle 이 ACTIVE 라 Discard·배경 I/O 가 달라져요.
- 측정이나 TC 가 도는 동안 **폰에 어떤 명령도 보내지 않아요** (adb shell, dumpsys 포함). trace 가 오염돼요.
- 시나리오 사이에 쉬는 시간을 두고, 대기 시나리오는 쉰 뒤에 시작해요.
- trace 출력 파일은 `/dev` 같은 /data 밖에 써요.

### 2.2 trace 에 필요한 필드
UFS request 마다 한 줄인 표(parquet)예요. 이 저장소는 fsiotrace(eBPF) 의 `fsio_ufs` 를 써요.

| 필드 | 쓰는 곳 |
|---|---|
| `time` (초, boottime) | 시각. 정렬·구간 자르기 |
| `action` | `send_req` 만 request 로 봄. Hibern8 은 `uic_send`/`uic_complete` + `mgmt_name` |
| `opcode` | SCSI: 40·136 Read, 42·138 Write, 66 UNMAP(Discard), 53 SYNCHRONIZE CACHE(Flush) |
| `lun`, `lba`(4KB 단위), `size`(바이트), `qd` | 크기·Sequential·QD |
| `is_mgmt` | UFS 관리 명령은 request 에서 뺌 |
| `ino`, `name`, `tid`, `comm` | 파일·스레드. 파일 동작으로 되돌릴 때 필수 |
| `is_fsync_triggered` | fsync 안에서 나온 Write |
| `is_direct_io` | O_DIRECT Write |
| `is_writeback_kworker` | 커널 writeback (fsync·O_DIRECT 에도 붙으므로 둘 다 아닐 때만 커널 몫) |
| `is_f2fs_node_write`, `is_f2fs_meta_write`, `is_checkpoint`, `is_journal` | FS 유발 Write |
| `is_gc`, `is_f2fs_node_gc`, `is_f2fs_data_gc` | GC |

주의할 점이에요.
- **flag 가 믿을 만한지 먼저 확인해요.** 이 저장소는 2026-10-28 에 귀속 버그를 고쳤고, 그 전 trace 의 파일 이름·comm·node/meta/Checkpoint/fsync flag 는 틀려요. Volume·size·LBA·Latency 는 맞아요.
- 고친 도구는 writeback·Checkpoint Write 의 `comm` 을 **주인 앱 이름으로** 붙여요. 그래서 comm 만으로는 앱 스레드인지 알 수 없고 flag 로 가려야 해요.
- Checkpoint Write 는 comm 이 `f2fs_ckpt` 가 아닌 이름(logd 등)으로 찍히기도 해서 `is_checkpoint` 와 `comm like 'f2fs_ckpt%'` 를 같이 봐요.

### 2.3 기기에서 확인한 값 (TC 동작에 영향)
- block queue: scheduler `mq-deadline`, `nomerges=0`, `max_sectors_kb=1024`, `read_ahead_kb=512`
- f2fs mount: `flush_merge`, `checkpoint_merge`, `fsync_mode=nobarrier`, quota 켜짐 (ino 4·5·6)
- 4KB 블록, 커널 `CONFIG_AIO` 있음 (Linux AIO `io_submit` 사용)

다른 기기로 옮기면 이 값부터 확인해요. 특히 `fsync_mode` 가 `posix` 면 fsync 마다 Flush 가 붙어 FS/FA 구분 규칙(3.2)이 달라져요.

---

## 3. 조각 만들기 (`segments.py`)

시나리오의 회차마다 trace 하나를 **조각** 하나(`<시나리오>-<회차>.npz`)로 바꿔요. 조각은 시각순 파일 동작 목록과 파일 표예요.

### 3.1 재생 op

| op | 번호 | 재생 동작 | 원본에서 무엇이었나 |
|---|---|---|---|
| R | 0 | O_DIRECT pread | Read (page cache 뒤 request 라 크기 그대로 냄) |
| W | 1 | buffered pwrite + `sync_file_range(WRITE)` | 그 밖의 Data Write (kworker writeback 등) |
| WB | 2 | buffered pwrite (sync 없음) | 앱 스레드 Data Write, 1초 안에 같은 스레드·파일 fsync 가 옴 |
| WD | 3 | O_DIRECT pwrite | 앱 스레드 O_DIRECT Data Write |
| FS | 4 | fsync | 앱 스레드 fsync (node Write 로 보임) |
| DB | 5 | (재생 안 함) | Discard 바이트. 기록만 |
| UNLINK | 6 | unlink | 잠깐 쓰고 지워진 파일 |
| TRUNC | 7 | ftruncate(off) | (합성용) |
| MARK | 8 | 없음. file = timeline 구간 번호 | 구간 경계 (통계용) |
| FA | 9 | `F2FS_IOC_COMMIT_ATOMIC_WRITE` | atomic commit (SQLite atomic write) |
| WX | 10 | atomic write 안 pwrite (처음이면 `F2FS_IOC_START_ATOMIC_WRITE`) | FA 앞의 Data Write |
| CP | 11 | 재생 디렉터리 fsync | 원인을 모르는 Checkpoint (sync, 배경) |
| TRIM | 12 | FITRIM | (v1 은 안 씀) |
| DS | 13 | 재생 디렉터리 fsync (FS 직후) | fsync 가 부른 Checkpoint (새 journal, AtomicFile rename) |
| SCREEN | 14 | 화면 켜기(file=1)/끄기(0) | 시나리오의 화면 상태 |

`F2FS_IOC_START_ATOMIC_WRITE = 0xf501`, `F2FS_IOC_COMMIT_ATOMIC_WRITE = 0xf502` (`_IO(0xf5, 1/2)`).

### 3.2 request 분류 규칙

trace 의 `send_req` 를 시각순으로 보며 아래 순서로 정해요. 관리 명령(`is_mgmt`)은 빼요.

**앱 스레드인지:** 다음을 모두 만족하면 앱 몫이에요.
- comm 이 `kworker%`, `f2fs%`, `jbd2%` 가 아님
- `is_checkpoint`·`is_gc` 가 아님
- `is_writeback_kworker` 이면서 fsync·O_DIRECT 도 아닌 Write 가 아님

**Checkpoint 묶음:** comm 이 `f2fs_ckpt%` 이거나 `is_checkpoint` 인 Write 는 앞 Checkpoint Write 와 **1ms 넘게** 떨어지면 새 Checkpoint 로 보고 `CP` 를 하나 넣어요. Checkpoint 하나 안의 Write 간격은 0.2ms 안팎, Checkpoint 사이는 2ms 이상이에요.

**Read** → `R` (ino, lba, 블록 수, tid 보관)

**Discard** → `DB` (바이트만)

**Write**
1. FS 몫이면 버려요: `is_journal`, `is_checkpoint`, `is_f2fs_meta_write`, GC flag.
2. node Write 인데 fsync 안이 아니면(writeback node) 버려요.
3. fsync 안 node Write(`is_f2fs_node_write` 이고 `is_fsync_triggered`)면 fsync 예요. ino 가 있을 때만 넣어요.
   - 1ms(`CKPT_WIN`) 안에 Checkpoint Write 가 오면 → `FS` (그 Flush 는 Checkpoint 몫)
   - 아니고 3ms(`FLUSH_WIN`) 안에 Flush 가 오면 → `FA` (atomic commit 이 PREFLUSH|FUA 를 냄. `fsync_mode=nobarrier` 라 일반 fsync 는 Flush 가 없음)
   - 둘 다 아니면 → `FS`
4. 앱 몫 O_DIRECT → `WD`
5. 앱 몫 나머지 → 일단 `WA` (아래에서 WB/WX/W 로)
6. 앱 몫이 아닌 Data Write → `W`

**같은 fsync 의 node 여러 개 합치기:** 같은 (tid, ino) 의 FS/FA 가 0.3ms 안에 이어지면 하나로 봐요. 하나라도 FA 면 FA 예요. WAL 은 0.7ms 마다 따로 fsync 하므로 이보다 넓히면 안 돼요.

**WA 정하기:** 뒤에서부터 훑어, 같은 (tid, ino) 의 다음 FS/FA 가 **1초(`FSYNC_WIN`) 안**에 있으면 `WB`(그 fsync 가 FA 면 `WX`), 없으면 `W` 예요.

### 3.3 지워진 파일 (`UNLINK`)
trace 에는 unlink 가 없어요. 대신 이렇게 추정해요.
- 처음 접근이 Read 가 아닌 파일(새로 만든 파일)만 봐요.
- 이름이 `-journal`, `.tmp`, `.temp` 로 끝나면 그 이름의 inode 전부, 아니면 같은 이름이 inode 여러 개로 나올 때 마지막 것만 빼고 전부 지워진 것으로 봐요.
- 마지막 접근 0.5ms 뒤에 `UNLINK` 를 넣어요.

예: TikTok 은 105초 동안 `ttm_strategy.db-journal` 을 inode 1045개로 만들고 지웠어요. 이걸 재생하지 않으면 디렉터리 변경·Discard 가 크게 모자라요.

### 3.4 fsync 가 부른 Checkpoint (`DS`)
SQLite 는 새 rollback journal 을 만들면 디렉터리를 fsync 하고, AtomicFile(`.tmp` → rename)도 같은 결과를 내요. f2fs 에서는 이게 Checkpoint 예요.
- `-journal` 파일의 첫 fsync 시각을 모아요.
- 이름과 상관없이 FS/FA 직후 **3ms 안에** `CP` 가 오면 그 fsync 시각도 모아요.
- 모은 시각 + 50µs 에 `DS` 를 넣고, 그 3ms 안의 `CP` 는 지워요 (DS 가 만들 것이므로).
- 남는 `CP` 는 원인을 모르는 Checkpoint 예요.

재생기는 FS 바로 뒤(1ms 안)의 DS 를 **같은 goroutine 에서 fsync 가 끝난 뒤에** 내요 (5.4).

### 3.5 파일 offset 매핑
f2fs 는 덮어써도 새 LBA 에 쓰므로 LBA 로 파일 offset 을 알 수 없어요. 그래서:
1. inode 마다 R/W 계열이 건드린 LBA 구간 `[lba, lba+블록수)` 을 모아 정렬하고 겹치면 합쳐요.
2. 합친 구간을 LBA 순서로 이어 붙여 파일 offset 을 줘요. 구간 안은 Sequential 이 유지돼요.
3. **떨어져 있던 구간 사이에는 4KB 빈칸을 둬요.** 붙여 두면 같은 순간에 낸 Read 를 커널이 원본에 없던 큰 request 로 합쳐요.
4. 파일 크기 = 마지막 offset. inode 가 없는 request 는 파일 0(scratch) 이에요.
5. **파일 번호는 원본에서 처음 쓰인 LBA 순서**로 매겨요. 준비 단계가 이 순서로 미리 채우므로 f2fs 가 원본처럼 붙여 배치하고, 서로 다른 파일을 이어 읽던 Sequential Read 가 살아나요.
6. fsync·unlink 만 있는 파일은 크기 1블록으로 끝에 붙여요.

**원래 있던 파일(prefill):** 처음 접근이 Read 이거나, 파일 0 이거나, 아래 덮어쓰기 파일이면 준비 단계에서 미리 채워요. Write 로 시작하면 새로 만드는 파일이에요.

### 3.6 덮어쓰던 파일
3.5 처럼 이어 붙이면 WAL·`.pma`·로그 파일처럼 **같은 자리를 계속 덮어쓰던 파일이 끝없이 늘어나는 append** 가 돼요. 그러면 Checkpoint 마다 블록 할당·quota 가 바뀌어 대기 구간 Checkpoint Write 가 원본의 2배가 됐어요.

다음을 모두 만족하는 파일은 덮어쓰기로 재생해요.
- 처음 접근이 Write
- 지우지도(UNLINK) fsync 하지도(FS/FA) 않음
- 같은 파일 Write 를 **1초(`REWRITE_GAP`) 간격으로 묶었을 때** 묶음이 3개 이상이고, 가장 큰 묶음이 **1MB(`REWRITE_MAX` = 256블록) 이하**

이 파일은 크기를 가장 큰 묶음 크기로 정해 미리 채우고, Write 는 그 안을 처음부터 돌며 써요(끝을 넘으면 0으로). Read 는 offset 을 파일 크기로 나눈 나머지로 접어요.

**fsync 하는 파일은 빼요.** 덮어쓴 뒤 fsync 하면 f2fs 가 in-place update(IPU)로 node 를 쓰지 않아 fsync I/O 가 사라져요 (TikTok fsync 1166 → 608).

### 3.7 조각 출력
`<시나리오>-<회차>.npz`:

| 배열 | 형 | 뜻 |
|---|---|---|
| `t` | float64 | trace 시작부터 초 |
| `op` | uint8 | 3.1 번호 |
| `f` | uint32 | 조각 안 파일 번호 |
| `off` | uint64 | 바이트 offset (덮어쓰기 파일은 접은 값) |
| `len` | uint32 | 바이트 (DB 는 Discard 바이트) |
| `file_ino`, `file_size`, `file_existing` | | 파일 표 |

`index.json` 에 조각마다 시나리오·회차·trace ID·길이·op 별 개수·MB·파일 수, SQLite 통계(journal transaction 수, WAL commit 수와 크기 중앙값, fsync 가 부른 Checkpoint 수)를 남겨요.

조각은 기준 측정이 바뀌면 다시 만들어요. 시나리오마다 마지막 run 을 쓰므로 기준 세트보다 뒤에 시험 run 을 남기지 않아요.

---

## 4. TC 만들기 (`gen_tc.py`)

### 4.1 tc.bin 형식 (little endian)
```
header  "UXWL0001" (8) | nfiles u32 | 0 u32 | nreq u64
files   size u64 | flags u8 (1 = prefill)           × nfiles
reqs    t_us u64 | op u8 | file u32 | off u64 | len u32   × nreq   (25바이트, 시각순)
```
`manifest.json` 의 `timeline` 이 비교의 기준이에요.
```json
{"i": 3, "seg": "B7t-2", "tcStart": 812.4, "srcFrom": 0.0, "srcTo": 95.0, "cat": "sns"}
```
뜻: TC 의 `tcStart` 초부터 조각 `seg` 의 `[srcFrom, srcTo)` 초를 재생했다. 합성 구간은 `seg` 가 `synth-db-wal` 처럼 조각 이름이 아니고 `synth` 에 모델 값이 들어가요. `durSec` 는 TC 길이예요.

### 4.2 조각 붙이기 (`add_segment`)
- 구간 시작에 `MARK(i)` 를 넣어요.
- 조각의 `[srcFrom, srcTo)` request 를 `tcStart + (t - srcFrom)` 로 옮겨요. **DB(Discard)는 버려요** (8절).
- 파일 번호를 TC 파일로 바꿔요.
  - **원래 있던 파일은 (조각, 파일) 마다 하나**를 같이 써요. 같은 조각을 다시 써도 같은 파일이라 미리 채우는 양이 줄어요.
  - **새로 만드는 파일은 구간마다 새로** 만들어요. 같은 조각을 다시 써도 서로 겹치지 않게요.
- 구간에서 실제로 쓰는 파일만 만들어요.

### 4.3 `seq`: 보정용
조각을 순서대로 이어요. `--lead 5`초 쉬고 시작, 조각 사이 `--rest 20`초. `S5-1@0:1200` 처럼 조각의 일부만 쓸 수 있어요. 화면은 조각 앞 쉬는 시간 가운데서 켜거나 꺼요(대기 시나리오면 끔).

시나리오 하나씩 보정할 때는 이 방식으로 짧은 TC 를 만들어 돌리며 규칙을 맞췄어요 (11절).

### 4.4 `day`: 하루 사용 흐름
사용자 행동 모델과 가중치 파일(`mix.json`)로 하루를 짜고, 화면 꺼진 시간만 압축해 기본 2시간 TC 로 만들어요.

**행동 모델 (`usage.json`)이 가져야 하는 값.** 이 저장소는 라이선스가 불명인 사용 로그 데이터셋에서 뽑아서 값은 공개하지 않아요. 다른 프로젝트에서는 회사 데이터나 직접 정한 값으로 같은 구조를 채우면 돼요.

| 키 | 뜻 |
|---|---|
| `perDay.onMinQ` | 하루 화면 켜짐 분 [25, 50, 75%] |
| `perDay.sessionsQ` | 하루 화면 켜짐 세션 수 [25, 50, 75%] |
| `hourly[h].sessions` | 시간대별 하루 평균 세션 시작 수 |
| `sessionSecQ` | 세션 길이 분위수 [10, 25, 50, 75, 90, 99%] |
| `visitSecQ[c].p` | 카테고리 방문 길이 분위수 (같은 세션 안 연속 같은 카테고리 = 방문 하나) |
| `transition[a][b]` | 세션 안 카테고리 a → b 전이 확률 |
| `firstCategory[c]` | 세션 첫 카테고리 확률 |
| `categoryShareUserAvg[c]` | 화면 켜진 시간 중 카테고리 비중 (사용자별 비중의 평균) |

데이터셋을 쓸 때 만든 방식: 앱 FG→BG 이벤트 짝으로 앱 사용 구간을 만들고, 2초 미만은 버리고, 한 구간은 최대 2시간, 앞 구간 끝에서 60초 넘게 빈 뒤에 오면 새 세션(그 사이 = 화면 꺼짐)으로 봤어요. 패키지 → 카테고리는 `catmap.json`(패키지 표 + 정규식)으로 정해요.

**순서**
1. **세션:** 하루 세션 수(중앙값)만큼, 시간대별 세션 수를 가중치로 시작 시각을 뽑아요. 길이는 세션 분위수에서 뽑고, 합이 하루 화면 켜짐 분(`--on-min`, 기본 중앙값)이 되게 비율로 늘이고 줄여요. 세션 사이는 최소 30초.
2. **카테고리 할당량:** 카테고리 가중치(`mix.json` 의 `weight`, null 이면 모델 값, `--set c=w` 가 우선, 측정 조각이 없는 카테고리는 0, 합 정규화) × 화면 켜짐 시간.
3. **방문:** 세션을 채울 때 다음 카테고리를 `(전이 확률 + 0.01) × 남은 할당량` 으로 뽑아요. 길이는 그 카테고리 방문 분위수에서 뽑되 할당량·세션 남은 시간을 넘지 않게. 3초 미만 방문은 버려요. 이렇게 하면 비중은 가중치대로, 순서는 실제 사용처럼 돼요.
4. **길이 맞추기:** TC 가 `--hours` 를 넘으면 세션을 **비트 반전 순서**(하루 전체에 고르게 퍼진 순서)로 골라 화면 켜짐 예산까지만 써요. 시간대 모양이 유지돼요. 예산을 바꿔 가며 최대 8번 다시 짜서 0.95~1.03 배 안에 들게 해요.
5. **조각 붙이기:** 방문마다 카테고리 안 시나리오 가중치로 시나리오를, 무작위로 회차를 골라요. 방문이 조각보다 길면 조각을 처음부터 다시 이어 붙이고(새 파일로), 짧으면 앞에서부터 잘라요.
6. **앱 실행:** 카테고리가 바뀔 때(홈·통화 제외) 앱 실행 조각을 하나 끼워요. 20%(`coldRatio`)는 cold start, 나머지는 warm 전환 시나리오이고, 시나리오 안 실행 횟수 `n` 으로 조각을 나눈 한 칸을 써요.
7. **화면 꺼짐:** 세션 사이 공백을 `--standby-scale`(기본 2%)로 압축(최소 5초)하고, 공백 길이 구간(5분 이하 / 30분 이하 / 그 이상)에 맞는 대기 시나리오에서 무작위 위치를 잘라 채워요. 앞에 화면 끄기(`SCREEN 0`)를 넣어요.
8. **하루 이벤트:** 앱 재설치, 다운로드, 큰 파일 복사·삭제 같은 시나리오를 하루 횟수만큼(소수는 확률) 하루 중 무작위 시각에 넣어요. 그 시각을 지나는 방문 앞에 끼워요.
9. 하루 끝까지 남은 시간은 대기로 채워요.

같은 `--seed` 와 같은 조각이면 tc.bin 이 바이트까지 같아요 (`random.Random(seed)` 하나만 쓰고, 길이 맞추기에서 다시 짤 때 상태를 되돌려요).

**`mix.json` 구조**
```json
{
  "categories": {
    "browser": {"weight": null, "scenarios": {"B1": 0.3, "B4": 0.3, "B5": 0.3, "B1i": 0.1}},
    "messaging": {"weight": null, "proxy": true, "scenarios": {}, "db": {"mode": "wal", "kb": 12, "perMin": 30}},
    "game": {"weight": 0, "scenarios": {}}
  },
  "launch": {"coldRatio": 0.2, "cold": {"A1": {"w": 0.4, "n": 5}}, "warm": {"A3": {"w": 0.4, "n": 6}}, "skip": ["home", "call"]},
  "daily": {"E3": 2, "E8": 1, "E6": 0.5},
  "standby": [{"maxSec": 300, "scenarios": {"S3": 1}}, {"maxSec": 1800, "scenarios": {"S1": 0.5, "S2": 0.5}}, {"maxSec": 1e9, "scenarios": {"S5": 1}}]
}
```
이 저장소의 카테고리와 시나리오 묶음은 `wl/mix.json` 그대로예요. 측정이 없는 카테고리는 `proxy: true` 로 비슷한 시나리오를 대신 쓰고 결과에 표시해요(쇼핑 → 웹·스토어 탐색, 통화 → 홈 대기).

### 4.5 SQLite transaction 합성 (`SqlTx`)
측정이 없는 메시지 앱은 SQLite 가 transaction 마다 내는 파일 동작을 그대로 만들어요. 간격은 지수 분포(분당 `perMin` 번)예요.
- **wal:** WAL 에 `kb` KB 덧붙이기(WB) → 0.1ms 뒤 fsync. WAL 이 4000KB 를 넘으면 그동안 바뀐 DB page 를 4KB 씩 WB → DB fsync → WAL 을 처음부터.
- **journal (rollback, DELETE):** journal 새 파일 쓰기 → fsync → 디렉터리 fsync(DS) → 1ms 뒤 header 4KB → fsync → DB page 쓰기 → DB fsync → journal unlink. transaction 하나 약 2ms (TikTok `ttm_strategy.db` 에서 본 간격).
`kb` 기본값 12 는 측정 앱들의 WAL commit 크기 중앙값이에요.

### 4.6 화면
앱 사용 구간 앞에는 `SCREEN 1`, 대기 앞에는 `SCREEN 0` 을 넣어요. 원본 앱 시나리오는 화면을 켜고, 대기 시나리오는 끄고 쟀기 때문이에요.

---

## 5. 재생기 (`replay/main.go`, uxwl)

Go 단일 바이너리(linux/arm64, `CGO_ENABLED=0`, `golang.org/x/sys/unix`)이고 root 로 돌아요.
```
uxwl prep  --root /data/local/tmp/uxwl tc.bin
uxwl run   --root /data/local/tmp/uxwl [--speed 1] [--max-qd 256] [--max-wd 3] [--wakelock=true] tc.bin
uxwl clean --root /data/local/tmp/uxwl
```
파일은 `<root>/f/%06d` 이에요. Write 내용은 seed 1 난수 16MB 버퍼 하나를 같이 써요(압축·dedup 영향 없게).

### 5.1 prep
- prefill 파일: **크기가 같아도 지우고** 새로 만들어 16MB 씩 pwrite → fsync. 앞 실행이 덮어써 블록 배치가 섞인 파일을 그대로 쓰면 실행마다 Write 가 다르게 쪼개져요.
- 새로 만들 파일: 지워 둬요.
- 끝에 `sync`. **page cache 는 비우지 않아요.** Read 는 O_DIRECT 라 상관없고, 비우면 inode·node 를 다시 읽는 4KB Read 가 생겨요.
- 파일 번호 순서로 채우므로 원본의 파일 배치 순서가 살아나요 (3.5).

### 5.2 run: 시각 맞추기
- 시작 시각의 `CLOCK_MONOTONIC`, `CLOCK_BOOTTIME` 을 기록해요 (비교 때 trace 시각과 맞출 때 씀).
- request 시각까지 2ms 넘게 남으면 `sleep(남은 시간 - 1ms)`, 그 뒤는 busy-wait 해요.
- 늦음 = 실제 발행 - 예정. 5ms 넘으면 `lateOver5ms` 로 세요. v1 에서 2시간 TC 기준 0.13~0.18% 예요.
- 화면이 꺼진 구간에 suspend 되면 타이머가 멈춰 시각이 밀리므로 재생하는 동안 `/sys/power/wake_lock` 에 `uxwl` 을 써요.

### 5.3 op 구현
| op | 구현 |
|---|---|
| R | O_DIRECT fd 로 pread (AIO 묶음은 5.5) |
| W | buffered fd 로 pwrite → `sync_file_range(off, n, SYNC_FILE_RANGE_WRITE)` |
| WB | buffered pwrite |
| WD | O_DIRECT pwrite |
| FS | buffered fd 로 fsync |
| FA | (처음이면 START_ATOMIC) → COMMIT_ATOMIC ioctl |
| WX | (처음이면 START_ATOMIC) → pwrite |
| CP, DS | `<root>/f` 디렉터리를 열어 fsync → f2fs 가 Checkpoint 를 냄 |
| UNLINK | 그 파일 fd 를 닫고 unlink |
| TRUNC | ftruncate(off) |
| SCREEN | `input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard`, 켜 있는 동안 10초마다 WAKEUP / 끌 때 `KEYCODE_SLEEP`. 시스템 설정은 바꾸지 않아요 |

파일마다 fd 를 두 개(buffered, O_DIRECT) 열어 두고 다시 써요. request 하나는 최대 16MB 예요.

### 5.4 동시성 규칙
열린 루프라 request 마다 goroutine 을 띄우되(전체 `--max-qd` 256 제한), 원본 앱의 순서 관계를 지키려고 아래 규칙을 둬요. 하나하나가 실측으로 찾은 규칙이에요.

1. **파일 잠금:** 파일마다 RWMutex. FS·FA·WX·UNLINK·TRUNC·**WD** 는 그 파일을 독점하고, 나머지는 공유 잠금이에요. fsync·unlink 는 그 파일의 진행 중 request 가 끝난 뒤에 돼요.
2. **WD 는 파일마다 하나씩, 전체 동시 3개(`--max-wd`):** 앱은 파일 하나를 스레드 하나가 순서대로 써요. 동시에 쓰면 f2fs 가 파일끼리 블록을 섞어 할당해 Write 가 4KB 로 쪼개졌어요.
3. **같은 파일·같은 op(R/W/WD)가 0.2ms 안에 이어지면 한 goroutine 이 순서대로** 내요. 따로 띄우면 장치에 닿는 순서가 섞여 readahead·카메라 저장 같은 Sequential request 가 Random 처럼 보이고 QD 가 부풀었어요. WD 는 앞 request 와 0.2ms 안이면 계속 이어요.
4. **이어지는 WD 는 pwrite 하나로 합쳐요** (offset 이 붙어 있고 합이 16MB 이하). 원본 앱의 큰 pwrite 가 커널에서 512KB 씩 나뉜 것이라서, 조각마다 따로 쓰면 다른 파일 Write 와 블록이 섞여 할당돼요.
5. **FS/FA 바로 뒤(1ms 안) DS 는 같은 goroutine 에서 fsync 가 끝난 뒤에** 내요 (SQLite 순서). 따로 띄우면 DS 의 Checkpoint 가 먼저 끝나 파일 node 까지 써 버리고, fsync 는 쓸 것이 없어 앱 스레드 node Write 가 사라졌어요.

### 5.5 Read: AIO 묶음과 순서
원본 앱은 thread 여러 개와 readahead 가 같은 순간에 Read 를 내고, 커널이 block plug 로 묶어 UFS 에 한꺼번에 보내요(Chrome cold start QD 50~60). pread 를 goroutine 마다 부르면 수십 µs 간격으로 나가 QD 가 7 에 머물렀어요.

**묶음 규칙 (`io_submit` 한 번 = 묶음 하나)**
- 앞 Read 와 **100µs(`burstGap`) 안**에 이어지고, 묶음 첫 Read 부터 **200µs(`burstSpan`) 안**이고, 최대 128개.
- **같은 파일에서 묶음 안 앞 Read 끝에 바로 붙는 Read 가 오면 묶음을 끊어요.** io_submit 한 번은 plug 하나라 커널이 붙은 Read 를 합쳐, 원본의 128KB readahead 열 개가 512KB 몇 개가 됐어요(size·Sequential·QD 모두 어긋남).

**발행 순서**
- **goroutine 하나(submitter)가 시각 순서대로 io_submit** 하고, 완료(`io_getevents`)는 묶음마다 따로 goroutine 에서 기다려요.
- submitter 는 묶음의 파일 잠금을 파일 번호 순서로 `TryRLock` 해요. 하나라도 실패하면(FS·UNLINK 가 잡고 있으면) 그 묶음만 별도 goroutine 에서 기다렸다 내요.
- 묶음마다 goroutine 을 띄우면 준비(잠금·fd·AIO context)에 0.5ms 쯤 걸려 뒤 Read 가 먼저 나가, 음악 Sequential Read 가 원본 60% 에서 TC 26% 로 떨어졌어요.
- 주 루프에서 바로 io_submit 하면 그동안 다음 request 가 늦어져 늦음이 1.3% 가 됐어요.

AIO context 는 depth 128 로 만들어 최대 512개를 재사용해요. 커널에 AIO 가 없으면 pread 로 내요.

### 5.6 result.json
`startMonotonic`, `startBoottime`, `elapsedSec`, `scheduledSec`, `requests`, `lateOver5ms`, `lagMs{p50,p99,max}`, `qdMax`, op 별 `{n, MB, errors, latMs{p50,p99,p999}}`, timeline 구간별 같은 표(`segments`), `errorKinds`.
Latency 는 1µs~100s 로그 칸(칸당 10^(1/20)) 히스토그램이에요.

---

## 6. 실행 절차 (`run_tc.py`)

1. 결과 폴더 `<TC>-<시각>/` 에 manifest·tc.bin 을 복사해요.
2. uxwl 을 빌드하고 uxwl·tc.bin 을 `/data/local/tmp/uxwl/` 에 push 해요.
3. `uxwl clean` → `uxwl prep` (trace 밖에서).
4. **`/sys/fs/f2fs/*/pending_discard` 가 0 이 될 때까지 기다려요** (10초마다 `sync` 후 확인, 최대 15분). 앞 TC 파일을 지운 Discard 가 측정 앞부분에 섞이면 원본에 없던 Discard 가 GB 단위로 나와요. FITRIM 이나 f2fs 설정 변경으로 억지로 비우지 않아요.
5. trace 도구 시나리오를 돌려요: `sync` → trace 시작(로그에 쓰기 시작이 나온 뒤) → uxwl run 을 **nohup 백그라운드**로 → TC 길이 + 2초 sleep → `done` 파일이 생길 때까지 최대 120초 확인 → writeback 이 빠지게 3초 → trace 끝. 백그라운드 + sleep 으로 기다리는 이유는 실행기 shell Step 의 시간 제한과 상관없이 긴 TC 를 돌리려는 거예요.
6. trace parquet 변환을 기다리고, result.json 을 받아 `compare.py` 를 자동으로 돌려요.

---

## 7. 비교 (`compare.py`, `metrics.py`)

### 7.1 시각 맞추기
uxwl 의 시작 boottime(안 맞으면 monotonic) 중 trace 범위에 드는 것을 기준으로 잡고, 앞 10분의 **10ms 칸별 R/W/WD 바이트**(tc.bin 예정)와 trace 의 Read·Write 바이트를 ±10초 안에서 상호상관해 가장 잘 맞는 위치를 TC t=0 으로 써요. 재생기 시계와 trace 시각이 몇 초 어긋나는 일이 있어요.

### 7.2 TC 쪽 거르기 (`TC_ONLY`)
TC trace 에서는 `comm = 'uxwl'` 이거나 커널 문맥(`kworker%`, `f2fs%`, `jbd2%`)인 request 만 세요. 화면 꺼진 TC 동안 폰의 다른 앱(systemui SharedPreferences fsync 약 1/s, 설정, 제조사 서비스 DB)이 낸 I/O 는 원본 조각에도 이미 들어 있고 uxwl 이 그것까지 재생하므로, 그대로 두면 두 번 세요. 원본 쪽은 거르지 않아요.
Flush·Checkpoint·Discard 는 누구 몫인지 나눌 수 없어 남아요. `--all` 이면 다 세요.

### 7.3 구간과 SETTLE
timeline 구간마다 원본 조각의 `[srcFrom, srcTo)` 와 TC trace 의 `[T0+tcStart, T0+tcStart+길이)` 를 같은 함수로 재요.
**화면 켜진 구간 바로 뒤 대기 구간은 처음 10초(`SETTLE`)를 양쪽 다 빼요.** 앞 구간이 남긴 writeback·Checkpoint·Discard 가 몰려요(대기 시간 19% 에 FS Write 44%, Discard 82%). 원본 대기는 쉰 뒤에 쟀으므로 이게 없어요. 뺀 부분의 TC 값은 따로 보여 줘요.

### 7.4 지표 정의
구간 `[a, b)` 의 `send_req`(관리 명령 제외)로 더할 수 있는 합계(raw)를 만들고, 구간들을 더한 뒤 지표로 바꿔요. 카테고리·전체 지표는 raw 를 더해서 만들어요(평균의 평균이 아님).

| 지표 | 정의 |
|---|---|
| readMB, writeMB | Read/Write 바이트 (GC 제외) |
| fsWriteMB | FS 유발 Write: `is_journal`·`is_checkpoint`·`is_f2fs_meta_write` 이거나, node Write 중 fsync 안이 아닌 것. GC 제외 |
| dataWriteMB | writeMB - fsWriteMB |
| fsPct | fsWriteMB / writeMB (%) |
| flushPerSec | Flush(opcode 53) 수 / 초 |
| fsyncPerSec | fsync 안 node Write(`is_fsync_triggered`) 수 / 초 |
| ckptPerSec | Checkpoint 묶음 수 / 초 (Checkpoint Write 간격 1ms 넘으면 새 묶음) |
| discardMB, gcMB | Discard 바이트, GC Read+Write 바이트 |
| sizeR, sizeW | request 크기 분포 5칸: ≤4K, ≤16K, ≤128K, ≤512K, 그 이상 (%) |
| seqR, seqW | lun 별 시각순으로 `lba == 앞 request lba + size/4096` 인 바이트 비율 |
| gap | R/W request 사이 간격(DtoD) 분포 4칸: <1ms, <16ms, <200ms, ≥200ms |
| idlePct | 100ms 칸 중 R/W 가 하나도 없는 칸 비율 |
| wakesPerMin | 앞 request 와 1초 넘게 떨어진 request 수 / 분 (GC 포함) |
| qdP99 | R/W 의 dispatch 시 QD 99 분위 (64 상한) |
| h8PerMin, h8Pct | Hibern8: enter 완료부터 다음 exit 요청까지를 한 번으로, 횟수/분과 시간 비율 |

양·크기·Sequential·QD 는 GC 를 빼고, 시간 지표(간격·Idle·Wakeups)는 GC 도 장치를 깨우므로 넣어요.

### 7.5 판정 기준 (v1)
| 지표 | 방식 | 기준 |
|---|---|---|
| readMB, writeMB, dataWriteMB | 비율 | ±10% |
| fsWriteMB, flushPerSec, fsyncPerSec, ckptPerSec, wakesPerMin | 비율 | ±20% |
| qdP99 | 비율 | ±50% |
| fsPct, idlePct | 차이 | 5%p |
| seqR, seqW | 차이 | 10%p |
| sizeR, sizeW, gap | 분포 차이 (칸별 차이 합 / 2) | 15%p |
| discardMB, gcMB, h8PerMin, h8Pct | 값만 (판정 안 함) | |

- **SLACK (절대 차이 허용):** 배경 I/O 때문에 생기는 작은 절대 차이는 비율이 기준을 넘어도 통과예요. MB 지표는 `max(1MB, 0.5MB × 원본 분)`, flush/fsync 0.5/s, Checkpoint 0.2/s, Wakeups 5/분.
- **FLOOR (판정 안 함):** 원본·TC 둘 다 아주 작으면 판정하지 않아요. MB 1.0 (fsWriteMB 0.5), flush·fsync 0.2/s, Checkpoint 0.05/s, Wakeups 2/분, QD 2. size 분포는 request 20개 미만, Sequential 은 그 방향 1MB 미만이면 판정 안 해요.
- 결과: 구간별 통과 수(구간 × 지표), 카테고리별, 전체. `compare.json` 에 모두 남기고 `history.jsonl` 에 한 줄씩 쌓아요. `version` 과 `tcSha`(tc.bin sha256 앞 12자리)를 같이 남겨 같은 조건끼리만 견줘요.

### 7.6 Run 사이 흔들림
같은 TC·같은 uxwl 로 두 번 돌린 TC 끼리 비교한 값이에요(day6).
- 구간별 통과율은 1%p 안, 전체 판정은 같아요.
- 거의 안 흔들려요: Read Volume, Sequential Read(p90 0.4%p), Request size, Inter-arrival, Idle%(p90 2.7%p), fsync/s(p90 ×1.14).
- 많이 흔들려요: FS Write(p90 ×2.1), Checkpoint/s(p90 ×3.0), Flush/s(p90 ×1.6), Wakeups/분(p90 ×2.0), QD p99(p90 ×1.9), Sequential Write(p90 13%p). 구간 판정이 Run 마다 10~25% 뒤집혀요.
- 그래서 항목별 통과율 5%p, 카테고리 통과 수 2개 안의 차이는 흔들림으로 봐요. 바꾼 효과는 그보다 크거나 여러 카테고리에서 같은 쪽으로 움직일 때만 인정해요.

---

## 8. 재생하지 않는 것과 그 이유

| 원본 | 재생 | 이유 |
|---|---|---|
| node·meta·Checkpoint·journal Write | 안 함 | f2fs 가 만들게 두고 비교해요. 재생하면 두 번 나와요 |
| Flush | 안 함 | fsync·Checkpoint·atomic commit 이 만들어요 |
| GC | 안 함, 값만 비교 | 파일 시스템이 얼마나 차고 조각났는지에 달려요. 하루치 생성·삭제를 2시간에 몰아 day5 는 원본의 15배, day6 은 Run 마다 0.85~6배 |
| Discard | 안 함, 값만 비교 | TC 가 지우는 파일만으로 f2fs 가 이미 원본보다 많이 내요(대기 123 vs 62MB). 언제 낼지는 f2fs 가 idle 때 정해요 |
| Hibern8 | 값만 비교 | UFS 관리 명령이라 TC 쪽 다른 앱 몫을 거를 수 없어요 |

---

## 9. 알려진 차이 (v1)

- **대기 구간 Flush/s 가 원본의 60% 정도예요.** 원본 대기 Checkpoint 는 Flush 5개(파일 동기화 2 + Checkpoint 3), TC 는 3개예요. syncfs 로 재생하면 쌓인 Discard 가 다 나가 Flush·Discard 가 몇 배가 됐고, Flush 개수는 flush_merge 와 그때 dirty 양에 따라 4~7개로 흔들려 맞추지 못했어요.
- **I/O 가 적은 구간(대기·홈·통화)은 FS Write 가 원본의 1.5배쯤이에요.** 지금 폰에서 도는 배경 앱이 node·quota 를 dirty 로 만들고, TC 가 원본 간격으로 일으키는 Checkpoint 가 그것까지 같이 써요. 원본의 배경 앱 I/O 는 uxwl 이 이미 재생하고 있어서 그만큼이 더해져요. 데이터를 하나도 쓰지 않고 2.6초마다 Checkpoint 만 낸 5분에도 Checkpoint Write 가 6.4MB 로 원본 대기 5분(5.0MB)보다 많았어요. Checkpoint 안 FS Write 는 누구 몫인지 나눌 수 없어 거를 수 없어요. 반대로 I/O 가 많은 구간은 0.6~0.8배라 전체로는 0.9배 안팎으로 맞아 보여요.
- **readahead 체인의 QD 를 못 맞춰요** (원본 50, TC 26~31, 기준 ±50% 의 가장자리). 커널은 128KB 를 35µs 간격으로 내는데 io_submit 은 하나에 80µs 쯤 걸려요. readahead(2) + fadvise 로 커널에 맡겨 보면 request 크기와 양이 어긋났어요(음악 Read 67%).

---

## 10. 해 봤는데 안 된 것

다시 만들 때 같은 길로 가지 않도록 남겨요.

| 시도 | 결과 |
|---|---|
| 블록(LBA) 그대로 재생 | FS I/O 가 두 번 나옴. 출발점에서 버림 |
| LBA 구간을 이어 붙여 모든 파일을 append 로 | 덮어쓰던 파일이 끝없이 늘어 Checkpoint quota 가 원본의 5배 → 3.6 |
| 덮어쓰기 대상에 fsync 파일까지 넣기 | IPU 로 fsync node 가 사라짐 (TikTok 1166 → 608) |
| 구간 사이 빈칸 없이 offset 붙이기 | 같은 순간 Read 를 커널이 합쳐 큰 request 가 생김 → 4KB 빈칸 |
| pread 를 goroutine 마다 | QD 7 에 머묾 → AIO 묶음 |
| 붙은 Read 를 한 io_submit 에 | plug 가 합쳐 128KB → 512KB → 묶음 끊기 |
| 묶음마다 goroutine 이 io_submit | 순서가 섞여 Sequential Read 26% (원본 60%) → submitter 하나 |
| 주 루프에서 바로 io_submit | 늦음 1.3% |
| readahead(2) 로 체인 맡기기 | 크기·양 어긋남 |
| WD 를 파일 여러 개 동시에 | 블록 섞여 4KB 로 쪼개짐 → 파일당 하나, 동시 3개 |
| FS 와 DS 를 따로 띄우기 | 앱 node Write 가 사라짐 → 같은 goroutine |
| Discard 를 파일 삭제 + FITRIM 으로 재생 | 이미 원본보다 많음. 코드 지움 |
| 대기 Checkpoint 를 syncfs 로 | 쌓인 Discard 가 다 나가 Flush·Discard 몇 배 |
| prep 뒤 drop_caches | inode·node 를 다시 읽는 4KB Read 가 생김 |
| prep 에서 같은 크기 파일 재사용 | 실행마다 Write 쪼개짐이 달라짐 → 늘 새로 |
| 측정 바로 전에 앞 TC 파일 삭제 | 첫 구간에 원본에 없던 Discard 2.9GB → pending_discard 0 까지 대기 |
| TC 쪽 모든 request 비교 | 다른 앱 I/O 를 두 번 셈 → TC_ONLY |
| 대기 구간 처음부터 판정 | 앞 구간 잔여 I/O 로 FS Write·Discard 가 몰림 → SETTLE 10초 |

---

## 11. 만드는 순서 (권장)

1. **trace 확인:** 2.2 의 필드와 flag 가 맞는지, 파일 이름·tid 가 앱 스레드로 붙는지 먼저 봐요. 귀속이 틀리면 뒤 단계가 다 틀려요.
2. **조각 + 재생기 + 비교를 한 번에:** 3, 5, 7 을 최소한으로 만들고 시나리오 하나를 `seq` 로 돌려 비교까지 이어지게 해요.
3. **보정 세트로 맞추기:** 성격이 다른 시나리오를 하나씩 `seq` TC 로 돌리며 규칙을 맞춰요. 이 저장소는 Chrome cold start, TikTok 추천 영상, YouTube 영상, 카메라 사진·동영상, 1GB 파일 삭제, 갤러리 그리드, 화면 끈 직후 대기, YouTube Music 을 썼어요. 각각이 드러낸 문제:
   - TikTok: SQLite journal 생성·삭제, DS, atomic write
   - Chrome cold start: Read QD, AIO 묶음
   - 카메라 동영상: WD 직렬, pwrite 합치기
   - 대기: 덮어쓰기 파일, TC_ONLY, SETTLE, pending_discard 대기
   - YouTube Music: Read 순서(submitter), 붙은 Read 끊기
4. **하루 TC:** 4.4 로 짜고 2시간 TC 를 돌려 구간·카테고리·전체 판정을 봐요.
5. **흔들림 재기:** 같은 TC 를 두 번 이상 돌려 7.6 처럼 흔들림 폭을 정한 뒤에 버전을 고정해요.

---

## 12. v1 결과 (day6, 2시간 하루 TC, 세 번)

| Run | uxwl | 구간별 통과 | 전체 | 늦은 request |
|---|---|---|---|---|
| 1 | Read 순서 고치기 전 | 77.3% | 16/16 | 0.17% |
| 2 | v1 | 76.2% | 16/16 | 0.18% |
| 3 | v1 | 77.3% | 16/16 | 0.13% |

TC: request 약 24만 6천 개, 7379초, 파일 3만 7천 개, Read 8.3GB, Write 4.6GB(앱 몫), fsync 1만 2천, Checkpoint(CP) 4305, unlink 1만 5천.

지표별 구간 통과율(Run 3): Read Volume 94%, Request size 95~98%, Sequential Read 96%, Inter-arrival 97%, Idle% 98%, fsync/s 96%, Write Volume 72%, Checkpoint/s 70%, FS Write 66%, Sequential Write 65%, Wakeups 65%, QD p99 73%, FS Write 비율 47%, Flush/s 40%.
앱이 직접 내는 I/O(Read, Data Write, fsync, 크기, 간격)는 거의 맞고, f2fs 가 스스로 정하는 I/O(Checkpoint 묶음, Flush, FS Write 비율)가 남은 차이예요. 이건 9절의 이유로 파일 동작 재생만으로는 더 맞추기 어려워요.
