# UFS workload TC 설계서 (v4)

스마트폰에서 잰 UFS trace 를 **파일 동작**으로 바꿔 기기 `/data`(f2fs) 위에서 다시 재생하고, 재생 중 잡은 trace 를 원본과 자동으로 비교하는 TC 예요.
이 문서만 보고 다른 프로젝트에서 같은 TC 를 다시 만들 수 있게, 규칙·상수·형식·시행착오를 전부 적었어요. 코드 위치는 이 저장소의 `wl/` 이고, 실행 방법은 `GUIDE.md` 9절이에요.

- 기준 기기: OnePlus CPH2749, Android 16, kernel 6.12, UFS, `/data` = f2fs
- 버전: v4 (git 태그 `wl-v4`, `wl/metrics.py` 의 `VERSION`). 판정 기준은 v1 부터 그대로예요
- 결과 수준: 2시간 하루 TC 에서 전체 지표 16/16 통과, 구간별 통과 81%, 늦은 request 0.18%. 유형별 13개 TC 는 구간별 평균 82%, 전체 173/204 (12절)

---

## 0. 코드를 그대로 가져갈 때

### 0.1 가져갈 파일과 폴더 배치
`wl/` 만 복사하면 import 에서 멈춰요. 아래 배치를 그대로 지켜요 (코드가 `wl/` 의 상위 폴더를 기준으로 경로를 잡아요).
```
<프로젝트>/
  run.py                 agent HTTP 클라이언트 (run_tc.py 가 import run)
  report/extract.py      작은 함수 네 개 (segments·metrics·compare·run_tc 가 import extract)
  scenarios/*/<ID>.scenario.json   시나리오 목록 (ID 만 씀)
  runs/<ID>/2*.json      시나리오 측정 결과 (trace ID)
  wl/
    segments.py gen_tc.py run_tc.py compare.py metrics.py usage.py
    mix.json catmap.json Makefile
    replay/main.go go.mod go.sum
    .private/            조각·TC·결과·usage.json (커밋 안 함, 스크립트가 만듦)
```
`wl/export_site.py` 는 분석 사이트용이라 가져가지 않아도 돼요.

### 0.2 이 저장소 밖에 기대는 것 (새 프로젝트에서 맞출 곳)

**1. `report/extract.py`.** 이 저장소 파일 전체를 가져가도 되고, 아래만 있으면 돼요. `ROOT` 는 반드시 `wl/` 의 상위 폴더예요.
```python
import glob, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = Path.home() / ".agent-standalone/archive/jobs"      # agent 가 trace 를 보관하는 곳
DIR = ("case when opcode in (40,136) then 'R' when opcode in (42,138) then 'W' "
       "when opcode=66 then 'D' when opcode=53 then 'F' else 'X' end")
def size_bucket(col):   # ≤4K, ≤16K, ≤128K, ≤512K, 그 이상
    return (f"case when {col}<=4096 then 0 when {col}<=16384 then 1 when {col}<=131072 then 2 "
            f"when {col}<=524288 then 3 else 4 end")
def parquet_of(tid):    # trace ID → parquet 경로
    hits = glob.glob(str(ARCHIVE / "*" / "trace" / tid / "result_fsio_ufs.parquet"))
    return hits[0] if hits else None
def scenario_info(sid): # 시나리오 ID → (시나리오 JSON, 마지막 run JSON, 경로)
    p = glob.glob(str(ROOT / "scenarios" / "*" / f"{sid}.scenario.json"))[0]
    run = sorted(f for f in glob.glob(str(ROOT / "runs" / sid / "*.json")) if not f.endswith("-dry.json"))[-1]
    return json.load(open(p)), json.load(open(run)), run
```

**2. 원본 측정 목록** (`segments.py` 의 `runs()`). 시나리오 ID 는 `scenarios/*/<ID>.scenario.json` 이름에서 오고, `runs/<ID>/` 에 이름이 `2*[0-9].json` 인 파일(`20261028-152536.json` 같은 시각 이름)이 있어야 대상이 돼요. 이름이 다르면 조용히 빠져요. 회차별 trace 는 그 파일의 `results[0].traceJobs[] = {repeatIndex, traceJobId}` 에서 찾아요. 측정 결과를 다른 방식으로 두면 `runs()` 가 `(시나리오 ID, 회차, trace ID, parquet 경로)` 를 내게 고쳐요.

**3. trace 실행기** (`run_tc.py` + 루트 `run.py`). `run.py` 의 `call(method, path, body)` 는 `UX_AGENT`(기본 `http://127.0.0.1:50051`)로 JSON 을 보내는 HTTP 클라이언트이고, `DEVICE` 는 `UX_DEVICE`(agent 의 기기 ID)예요. 쓰는 API:
- `POST /api/agent/scenario/run` body `{deviceIds, scenarioName, steps, loops: [], repeat: 1, busyPolicy: "wait"}`, Step 은 `{type, params}` (`shell` cmd, `trace_start` trace_type=fsio_ufs·window_seconds·include_vfs·include_dram, `sleep` seconds, `trace_stop`)
- `GET /api/agent/benchmark/status?jobId=` → `state` 가 `completed`/`failed`/`cancelled` 면 끝
- `GET /api/agent/benchmark/result?jobId=&deviceId=` → `results[0].traceJobs[0].traceJobId`

agent 는 Step 파라미터를 콤마로 잘라 회차별 값으로 써요. 그래서 shell 명령에 콤마를 넣지 않아요 (`DEV` 경로·uxwl 옵션 포함).
다른 실행기로 바꾸면 6절 순서를 지키고, 결과 폴더에 `compare.py` 가 읽는 네 파일을 남겨요: `manifest.json`, `tc.bin`(run_tc 가 복사), 기기에서 받은 uxwl `result.json`(`startBoottime`, `startMonotonic`, `lateOver5ms`, `elapsedSec`, `requests` 사용), `run.json` 의 `{"pq": <TC trace parquet>}`.

**4. trace 도구** = fsiotrace `fsio_ufs` parquet (2.2). 다른 도구면 같은 열 이름으로 parquet 을 만들어요. 꼭 맞출 값:
- `time` 은 기기 boottime(또는 monotonic) 초여야 해요. compare 가 uxwl 시작 시각으로 맞추고, 범위 밖이면 멈춰요.
- Hibern8 은 `action` 이 `uic_send`/`uic_complete`, `mgmt_name` 이 `'DME_HIBER_ENTER'`/`'DME_HIBER_EXIT'`.
- 재생기 request 의 `comm` 이 정확히 `uxwl` 이어야 해요 (`metrics.TC_ONLY`). 바이너리 이름을 바꾸면 TC request 가 다 빠져요.
- trace 에 `is_fsync_triggered` 가 하나도 없으면 segments·metrics 가 **옛 규칙**으로 바뀌어요: comm 만으로 앱 스레드를 가리고, 앱 comm 의 node Write 를 전부 fsync 로 봐요. 열 이름이 다르거나 fsync 가 없는 trace 는 조용히 이 규칙을 타요.

**5. 사용 로그 데이터셋** (`usage.py`, `gen_tc.py day` 만 필요). `SRC` 를 받은 파일로 바꿔요. 입력은 JSON 배열이고 레코드마다 `pid`, `timestamp`(ms), `utcoffset`(시간), `package_name`, `name`, `is_system_app`, `type`(`MOVE_TO_FOREGROUND`/`MOVE_TO_BACKGROUND`) 이 있어야 해요. `usage.json` 을 손으로 채우면 4.4 표의 모양을 지켜요: `hourly` 키는 문자열 "0"~"23", `onMinQ`·`sessionsQ` 는 값 3개(가운데가 중앙값), `sessionSecQ`·`visitSecQ[c].p` 는 값 6개(10·25·50·75·90·99%).

**6. 시나리오 ID 가 코드에 박힌 곳.** `mix.json` 말고도 `gen_tc.py` 의 `SCREEN_OFF = ("S1", "S2", "S3", "S5")`(seq 모드에서 화면을 끄고 재생할 대기 시나리오)가 있어요. 대기 시나리오 ID 가 다르면 여기도 고쳐요. `mix.json` 의 시나리오에 조각이 하나도 없는 standby 구간이 있으면 `gen_tc.py day` 가 멈추며 알려 줘요.

### 0.3 호스트와 기기 조건
- **호스트:** Python 3.9 이상 + `duckdb`, `numpy`. Go 1.25, `golang.org/x/sys v0.43.0` 을 받을 수 있는 네트워크(또는 vendor). `adb`, `make` 가 PATH 에 있어야 해요 (`run_tc.py` 가 매번 `make` 로 uxwl 을 다시 빌드해요).
- **`UX_SERIAL`(adb serial)과 `UX_DEVICE`(agent 기기 ID)가 같은 폰**이어야 해요. 기본값은 이 저장소 실험실 값이라 그대로 두면 없는 폰을 가리켜요.
- **adb shell 이 root 로 떠야 해요.** `run_tc.py` 는 `su` 없이 `adb shell` 로 uxwl·sysfs 를 다뤄요. 기준 폰은 루팅되어 `adb shell id` 가 `uid=0(root)` 예요. root 가 아니면:
  - `/sys/power/wake_lock` 쓰기가 조용히 실패해 화면 꺼진 구간에 suspend 되고 시각이 밀려요.
  - `pending_discard` 를 못 읽어요. 이때 `run_tc.py` 가 경고를 내고 Discard 대기를 건너뛰어요.
- **`/data` 가 f2fs** 여야 해요. atomic write ioctl(FA·WX)과 Checkpoint 동작이 f2fs 전제예요. 재생 오류는 판정에 잡히지 않으므로 `run_tc.py` 가 `result.json` 의 `errorKinds` 를 경고로 보여 줘요. 비어 있는지 꼭 봐요.
- **보안 잠금(PIN·패턴)이 없어야** 해요. SCREEN op 는 `input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard` 로 켜서, 잠금이 있으면 화면 켜짐 구간이 잠금 화면에 머물러요.
- `/data` 여유 공간: TC 의 미리 채움 양 + 재생 중 새로 쓰는 양 (day6 은 미리 채움 7.9GB).

### 0.4 옮긴 뒤 처음 확인할 것
1. `python3 segments.py <시나리오 하나>` 가 조각을 만들고, 출력의 R·W·fsync·unlink 양이 원본 trace 와 맞는지.
2. `gen_tc.py seq` 로 그 조각 하나만 TC 로 만들어 `run_tc.py` 로 돌리고, 재생 오류 경고가 없고 compare 결과가 이 저장소의 같은 시나리오 결과와 비슷한지. (seq 모드는 구간에 카테고리가 없어 SETTLE 이 적용되지 않아요, 7.3)
3. 같은 seed 로 `gen_tc.py day` 를 두 번 돌려 tc.bin sha256 이 같은지.
4. 기기가 다르면 2.3 의 block queue·f2fs mount 값을 먼저 비교하고, 다르면 11절 보정 세트를 다시 돌려요.

판정 기준·재생 규칙을 바꾸면 `metrics.VERSION` 을 올려 앞 버전 결과와 섞이지 않게 해요.

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
| UNLINK | 6 | unlink (`segments.py` 안에서는 `UL`) | 잠깐 쓰고 지워진 파일 |
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

아래는 trace 에 `is_fsync_triggered` 가 있을 때(고친 fsiotrace) 규칙이에요. 하나도 없으면 comm 만으로 앱 스레드를 가리는 옛 규칙을 써요 (0.2 의 4).

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
2. atomic commit 의 node Write 면 `FA` 예요: node Write 이고, `is_fsync_triggered` 가 아니고, `io_flags` bit 41(SAW_FS)이 0, bit 35(WRITEBACK_KWORKER)가 1. uxwl 의 FA 가 같은 flag 값을 내는 것으로 확인했어요. fsync flag 가 없는 옛 trace 는 3번의 Flush 규칙을 그대로 써요.
   그 밖에 fsync 안이 아닌 node Write(writeback node)는 버려요.
3. fsync 안 node Write(`is_f2fs_node_write` 이고 `is_fsync_triggered`)면 fsync 예요. ino 가 있을 때만 넣어요.
   - fsync flag 가 있는 trace 는 늘 `FS` 예요. v2 까지는 "3ms 안에 Flush 가 오면 FA" 로 봤는데, 일반 fsync 의 node Write 도 약 60ms 뒤에 Flush 가 와서 이 시간 규칙이 맞지 않았고 진짜 atomic commit 은 빠졌어요.
   - flag 가 없는 옛 trace 만: 1ms(`CKPT_WIN`) 안에 Checkpoint Write 가 오면 `FS`, 아니고 3ms(`FLUSH_WIN`) 안에 Flush 가 오면 `FA`, 둘 다 아니면 `FS`
4. 앱 몫 O_DIRECT → `WD`
5. 앱 몫 나머지 → 일단 `WA` (아래에서 WB/WX/W 로)
6. 앱 몫이 아닌 Data Write → `W`

**같은 fsync 의 node 여러 개 합치기:** 같은 (tid, ino) 의 FS/FA 가 0.3ms 안에 이어지면 하나로 봐요. 하나라도 FA 면 FA 예요. WAL 은 0.7ms 마다 따로 fsync 하므로 이보다 넓히면 안 돼요.

**WA 정하기:** 뒤에서부터 훑어, 같은 (tid, ino) 의 다음 FS/FA 가 **1초(`FSYNC_WIN`) 안**에 있으면 `WB`(그 fsync 가 FA 면 `WX`), 없으면 `W` 예요.

**atomic commit 의 Data Write:** kworker flag 가 붙어 앱 몫이 아닌 `W` 로 분류되므로, 같은 (tid, ino) 의 다음 동작이 20ms(`ATOMIC_WIN`) 안의 `FA` 인 `W` 는 `WX` 로 바꿔요. 실제로 0.5~4ms 앞서 나와요.

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

같은 `--seed` 와 같은 조각이면 tc.bin 이 바이트까지 같아요. 난수는 `random.Random(seed)` 에서만 오고(SQLite 합성은 `Random(seed × 7 + 순번)`), 길이 맞추기에서 다시 짤 때 상태를 되돌려요.

**`mix.json` 구조**
```json
{
  "categories": {
    "browser": {"weight": null, "scenarios": {"B1": 0.3, "B4": 0.3, "B5": 0.3, "B1i": 0.1}},
    "messaging": {"weight": null, "proxy": true, "scenarios": {}, "db": {"mode": "wal", "kb": 12, "dbKb": 8, "perMin": 30}},
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

### 4.7 `cat`: 유형 하나만
```bash
python3 gen_tc.py cat --name cat-sns --cat sns --sec 600 --seed 1
```
`mix.json` 의 유형 하나(또는 `launch`, `daily`, `standby`)로 재생 시간 `--sec` 만큼 TC 를 만들어요. 시나리오 가중치대로 나누고, 조각은 되도록 통째로 쓰며, 할당보다 길면 잘라요(화면 꺼짐은 무작위 위치, 앱은 앞에서부터). `daily` 는 시간 대신 횟수를 따라요. 순서는 섞고 조각 사이 20초 쉬어요. 이 명령을 넣어도 `day` 의 tc.bin 은 바이트까지 같아요.

### 4.8 `idle`: 대조군
```bash
python3 gen_tc.py idle --name idle-ctl --sec 600
```
request 를 재생하지 않고 화면 켬·끔 구간만 둬요. 비교 필터를 지나 TC 측정에 섞이는 폰 자체 I/O 를 재요. 재생기나 기기 조건을 바꾸면 먼저 이걸 돌려요. v3 까지의 깨우기 키 버그(10절)도 이걸로 찾았어요.

---

## 5. 재생기 (`replay/main.go`, uxwl)

Go 단일 바이너리(linux/arm64, `CGO_ENABLED=0`, `golang.org/x/sys/unix`)이고 root 로 돌아요.
```
uxwl prep  --root /data/local/tmp/uxwl tc.bin
uxwl run   --root /data/local/tmp/uxwl [--speed 1] [--max-qd 256] [--max-wd 3] [--wakelock=true] tc.bin
uxwl clean --root /data/local/tmp/uxwl
uxwl trim  --root /data/local/tmp/uxwl          # FITRIM (v1 실행 흐름에서는 안 씀)
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
| RENAME (17) | 그 파일 fd 를 닫고 `<이름>.r` 로 rename (지우지 않음, 14.3 v5 후보 6). prep 이 남은 `.r` 을 지워요 |
| TRUNC | ftruncate(off) |
| SCREEN | 켤 때 `input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard`, 켜 있는 동안 10초마다 `input keyevent 0` / 끌 때 `KEYCODE_SLEEP`. 시스템 설정은 바꾸지 않아요. 켜진 화면에 WAKEUP 을 보내면 안 돼요(10절) |

파일마다 fd 를 두 개(buffered, O_DIRECT) 열어 두고 다시 써요. request 하나는 최대 16MB 예요.

### 5.4 동시성 규칙
열린 루프라 request 마다 goroutine 을 띄우되(전체 `--max-qd` 256 제한), 원본 앱의 순서 관계를 지키려고 아래 규칙을 둬요. 하나하나가 실측으로 찾은 규칙이에요.

0. **파일별 순서(v2):** goroutine 은 시작 순서가 정해져 있지 않아, 잠금만으로는 뒤 request 가 먼저 잠금을 잡을 수 있어요. 그래서 발행 전에 파일마다 순서를 정해요. 독점 op(FS·FA·WX·UNLINK·TRUNC·WD)는 앞 request 를 모두 기다리고, 공유 op 는 앞 독점 op 만 기다려요. CP·DS·TRIM 은 빼요. v1 은 이게 없어 `UNLINK: no such file` 이 8~25% 났어요.
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
Flush·Checkpoint·Discard 는 누구 몫인지 나눌 수 없어 남아요. `--all` 이면 다 세요. 대조 TC(4.8) 기준으로 이렇게 남는 Flush/s 는 화면 켜짐 0.74, 꺼짐 0.77(5분씩 한 번)이에요. 원본이 낮은 유형에서 Flush/s 가 조금 넘치는 몫이에요.

### 7.3 구간과 SETTLE
timeline 구간마다 원본 조각의 `[srcFrom, srcTo)` 와 TC trace 의 `[T0+tcStart, T0+tcStart+길이)` 를 같은 함수로 재요.
**화면 켜진 구간 바로 뒤 대기 구간은 처음 10초(`SETTLE`)를 양쪽 다 빼요** (구간에 `cat` 이 있는 day TC 만. seq TC 는 적용 안 됨). 앞 구간이 남긴 writeback·Checkpoint·Discard 가 몰려요(대기 시간 19% 에 FS Write 44%, Discard 82%). 원본 대기는 쉰 뒤에 쟀으므로 이게 없어요. 뺀 부분의 TC 값은 따로 보여 줘요.

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

## 9. 알려진 차이 (v4)

- **I/O 가 많은 유형의 FS Write 가 원본의 0.6~0.8배예요** (SNS 0.79, 카메라 0.64, 지도 0.64, 앱 실행 0.61, 브라우저 0.55). v3 까지는 깨우기 키 몫이 더해져 가려졌어요. 대부분 Checkpoint 가 쓰는 node 양의 차이예요(카메라 node Write 68 vs 23MB). 그중 조각에 Data Write 가 없는 inode 몫이 일부(SNS 대부분, 카메라·지도·앱 실행은 3~4할)를 설명해요. 파일 내용 없이 메타데이터만 바꾸는 동작은 block trace 에서 볼 수 없어 재생하지 못해요. 나머지는 파일 offset 을 LBA 순서로 이어 붙여(3.5) 한 파일 안에서 건드리는 direct node 가 원본보다 적어서라고 추정하는데, 확인하지 않았어요. 둘 다 VFS trace 를 같이 재야 제대로 고칠 수 있어요. Write 를 더 넣어 양만 맞추지는 않아요.
- **원본 값이 아주 작은 유형은 폰 배경 I/O 만으로 넘쳐요.** 갤러리 FS Write 0.9MB vs 12.2MB, 생산성·동영상·음악 Flush/s 원본의 1.3~1.5배.
- **SNS Flush/s 는 원본의 0.76배예요.** 원인은 확인하지 않았어요.
- **Read `operation not supported` 1건:** v3 부터 앱 실행, 하루 이벤트, 하루 TC 에서 1건씩 나와요. 양이 무시할 만해 원인은 보지 않았어요.

- **대기 구간 Flush/s 가 원본의 60% 정도예요.** 원본 대기 Checkpoint 는 Flush 5개(파일 동기화 2 + Checkpoint 3), TC 는 3개예요. syncfs 로 재생하면 쌓인 Discard 가 다 나가 Flush·Discard 가 몇 배가 됐고, Flush 개수는 flush_merge 와 그때 dirty 양에 따라 4~7개로 흔들려 맞추지 못했어요.
- **대기·홈은 FS Write 가 원본보다 많아요 (v4: 대기 1.29, 홈 1.37배).** 지금 폰에서 도는 배경 앱이 node·quota 를 dirty 로 만들고, TC 가 원본 간격으로 일으키는 Checkpoint 가 그것까지 같이 써요. 원본의 배경 앱 I/O 는 uxwl 이 이미 재생하고 있어서 그만큼이 더해져요. 데이터를 하나도 쓰지 않고 2.6초마다 Checkpoint 만 낸 5분에도 Checkpoint Write 가 6.4MB 로 원본 대기 5분(5.0MB)보다 많았어요. Checkpoint 안 FS Write 는 누구 몫인지 나눌 수 없어 거를 수 없어요.
- **readahead 체인의 QD 를 못 맞춰요** (원본 50, TC 26~31, 기준 ±50% 의 가장자리). 커널은 128KB 를 35µs 간격으로 내는데 io_submit 은 하나에 80µs 쯤 걸려요. readahead(2) + fadvise 로 커널에 맡겨 보면 request 크기와 양이 어긋났어요(음악 Read 67%).

---

## 10. 해 봤는데 안 된 것

- **화면 유지에 `KEYCODE_WAKEUP` (v3 까지):** 켜진 화면의 꺼짐 시간을 늘리지 못해 화면이 약 30초마다 꺼졌다 켜졌어요. 켜질 때마다 다른 앱의 fsync·Flush, `/mnt/vendor/persist` journal Write 가 나왔고, 꺼질 때마다 Discard 가 나왔어요. 대조 TC 화면 켜짐 Flush/s 2.00 → 키코드 0 으로 0.74. 하루 TC 의 Flush/s 일치(v3 5.46 vs 5.51)에도 이 몫이 섞여 있었어요.

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

## 13. v2~v4 결과

판정 기준은 그대로이고 재생 쪽만 바뀌었어요. 모두 Run 한 번씩이라, 유형별 값은 9.2 의 Run 사이 흔들림(구간별 5%p, 항목 2개) 안이면 차이로 보지 않아요.

| 버전 | 바뀐 것 | tc.bin | 하루 TC 구간별 | 전체 | Flush/s (원본 5.51) | FS Write MB (원본 720) |
|---|---|---|---|---|---|---|
| v1 | | day6 | 76~77% | 16/16 | 4.68~4.94 | 636~653 |
| v2 | 파일별 순서 (5.4 의 0번) | day6 | 78.9% | 16/16 | 4.62 | 616 |
| v3 | atomic commit 분류 (3.2) | day7 | 79.3% | 16/16 | 5.46 | 636 |
| v4 | 화면 유지 키 (10절) | day7 | 80.9% | 16/16 | 4.91 | 578 |

유형별 TC (`cat`, 600초):

| 유형 | 구간별 v3 → v4 | 전체 v3 → v4 | Flush/s 원본 | v3 → v4 | FS Write MB 원본 | v3 → v4 |
|---|---|---|---|---|---|---|
| SNS | 77 → 84% | 15 → 13 | 13.44 | 11.19 → 10.21 | 171.0 | 141.7 → 135.4 |
| 동영상 | 80 → 84% | 15 → 15 | 1.68 | 3.23 → 2.31 | 14.5 | 18.9 → 15.3 |
| 브라우저 | 80 → 79% | 15 → 14 | 1.87 | 3.42 → 2.30 | 20.0 | 17.1 → 11.0 |
| 음악 | 84 → 89% | 13 → 13 | 1.86 | 3.41 → 2.41 | 14.4 | 14.7 → 9.6 |
| 지도 | 80 → 78% | 12 → 13 | 4.53 | 5.45 → 4.66 | 37.8 | 25.7 → 24.3 |
| 카메라 | 79 → 82% | 12 → 13 | 6.33 | 7.26 → 6.57 | 116.4 | 83.1 → 74.8 |
| 갤러리 | 74 → 77% | 12 → 13 | 2.11 | 3.56 → 2.57 | 0.9 | 9.8 → 12.2 |
| 메일·스토어 | 85 → 88% | 14 → 15 | 2.04 | 3.61 → 2.50 | 13.3 | 13.4 → 11.3 |
| 생산성 | 75 → 83% | 11 → 12 | 1.10 | 2.91 → 1.61 | 7.2 | 15.7 → 7.6 |
| 홈 | 80 → 80% | 12 → 12 | 3.40 | 3.73 → 2.80 | 18.7 | 45.4 → 25.6 |
| 앱 실행 | 83 → 76% | 14 → 13 | 6.60 | 7.08 → 6.64 | 70.7 | 50.8 → 43.4 |
| 하루 이벤트 | 82 → 86% | 15 → 16 | 3.27 | 4.36 → 3.42 | 36.8 | 40.4 → 30.6 |
| 대기 | 83 → 80% | 13 → 11 | 3.81 | 2.41 → 2.58 | 40.4 | 41.0 → 52.1 |
| 평균·합 | 80.1 → 81.9% | 173 → 173 | | Flush/s 통과 유형 4 → 8 | | FS Write 통과 유형 7 → 4 |

- 전체 항목 합이 그대로인 건 Flush/s 통과가 늘고 FS Write 통과가 줄어 서로 지워져서예요. FS Write 는 깨우기 키 몫이 빠지며 부족분이 드러났어요. 9절의 첫 항목이에요.
- `discardMB` 는 구간 안만 세요. v4 는 화면이 켜져 있는 동안 Discard 가 거의 안 나오고 화면을 끈 직후에 몰려서, 하루 TC 의 값이 288MB 로 작아 보여요. trace 전체로는 2,740MB 로 원본 2,473MB 에 가까워요. 카메라처럼 앱 구간만 있는 유형은 구간 안 Discard 가 0 으로 원본과 같아졌어요(v3 은 1만 1천MB).

## 14. 시나리오 함수 TC (v5 후보, 검증 중)

하루 TC 는 Mac 에서 가중치를 적용해 tc.bin 을 만들었어요. v5 후보는 시나리오 pattern 을 **함수**로 두고, 함수를 **유형**으로 묶고, 실행할 때 **유형 가중치**를 줘서 TC 하나 안에서 돌려요. 사용 로그 데이터셋은 쓰지 않아요. 최종 목표는 회사 framework 용 C++ 이고, 지금은 `uxwl` 로 구조와 일치도를 검증하는 단계예요.

### 14.1 구성

| 파일 | 하는 일 |
|---|---|
| `gen_funcs.py` | 조각(`seg/*.npz`) → 함수 묶음 `funcs.bin` (`UXFN0001`). 함수 61개, 회차 181개, 유형 13개 |
| `groups.json` | 유형 → 함수와 유형 안 비중. 데이터셋 값은 없어요 |
| `collect_db.py` | 앱 DB 의 테이블 구조와 행 동작 비율을 기기에서 재요. 결과는 `.private/dbinfo` |
| `replay/mix.go` | `uxwl plan`: 함수 하나(`--func`) 또는 가중치(`--weight`)로 tc.bin 과 실행 순서를 만들어요 |
| `replay/sqlite.go` | DB 파일 Write 를 실제 SQLite 로 내요 (14.2) |
| `run_func.py` | `matrix`: 함수 하나씩 실행·비교, `mix`: 가중치 TC |

- 가중치는 실행 시간 비중이에요. 함수는 끝까지 실행하고, 목표 비중보다 가장 모자란 유형에서 다음 함수를 골라요. 같은 seed 면 순서가 같아요.
- 함수 사이에는 20초 쉬어요(`rest`). 비중은 함수 실행 시간만으로 세요.

### 14.2 DB I/O 는 실제 SQLite

- DB 파일(WAL·rollback journal 포함)은 request 를 재생하지 않고 같은 구조의 테이블에 INSERT·UPDATE·DELETE 를 내요. 비율은 앱 DB 를 잰 값이에요. 행 값은 가짜예요.
- 행 동작만으로는 양이 맞지 않아요. 그래서 WAL frame 수를 재며 맞춰요(closed loop). 원본 조각의 WAL page 수를 목표로 두고, 작은 transaction(원본 ops/commit)을 반복하며 `-shm` 의 mxFrame 을 읽어요. 모자라거나 넘친 양은 다음 transaction 으로 넘겨요. 그래도 모자라면 채움 테이블 `_uxpad` (한 행 = page 하나)를 UPDATE 해요. C++ 에서는 `sqlite3_wal_hook` 의 nFrame 을 쓰면 돼요.
- Checkpoint 는 원본이 DB 본체에 쓴 page 수를 쌓아 두고, WAL 의 서로 다른 page 수가 그 1.5배 안일 때만 PASSIVE 로 해요. 아니면 DB 본체 Write 가 원본보다 몇 배 많아졌어요(YouTube 0.3 → 4.3MB).
- 재생 전에 WAL 을 256 frame 채우고 12초 쉬어요. 준비 Write 가 비교 시각 맞추기(±10초)에 걸리지 않게 해요.
- 끝에 DB 연결을 닫지 않아요. 닫으면 SQLite 가 Checkpoint 하고 WAL 을 지워 원본에 없는 Write 가 나와요.
- 앱 전용 CHECK 제약은 `ignore_check_constraints` 로 꺼요. 다른 제약에 3번 걸린 테이블은 빼고, 남은 테이블이 없으면 채움 테이블로 써요.
- 앱 DB 의 행 내용은 기기 밖으로 나가지 않아요. 구조·SQL 은 `.private/` 에만 둬요.

### 14.3 f2fs Checkpoint 를 일으키지 않아요

v4 는 원본 시각에 Checkpoint op 을 냈어요. v5 후보는 빼고 f2fs 가 정하게 둬요. 그 결과 FS Write 와 Checkpoint/s 가 원본보다 적게 나오는 함수가 많았어요. 특히 화면을 끈 대기 함수에서 커요(화면 끈 직후 5분 FS Write 원본 12.8 vs 1.0MB).

**원인 (2026-11-04, f2fs ftrace).** FS Write 부족분은 거의 다 Checkpoint Write 였어요. Shorts 를 돌리며 `f2fs_sync_file_exit`(cp_reason), `f2fs_sync_fs`, `f2fs_write_checkpoint`, `f2fs_new_inode` 를 보니 Checkpoint 는 두 갈래에서 나와요.

| 원인 | 원본 Shorts (230초) | 고치기 전 TC (125초) |
|---|---|---|
| 앱 fsync, cp_reason "node needs cp" | 56 | 1 |
| 폴더 fsync, "non regular" | 5 | 32 |
| `autosuspend` 의 sync (superblock dirty 일 때만) | 68 | 14 |
| 측정 중 새로 만든 폴더 | 96 | 4 |

- "node needs cp" 56번은 모두 측정 중 새로 만든 폴더 안 파일의 첫 fsync 였어요. 앱이 폴더를 만들고 그 안에 파일을 써서 fsync 하면, 아직 Checkpoint 되지 않은 폴더라 f2fs 가 Checkpoint 를 해요.
- 이런 fsync 는 node 를 쓰지 않고 바로 Checkpoint 로 가요. 그래서 UFS trace 에 fsync 로 남지 않고, 조각을 만들 때 "쓰고 지운 파일"(UL)로 보였어요. TC 는 모든 파일을 폴더 하나(`f/`)에 둬서 이 조건이 거의 생기지 않았어요.
- 원본 Checkpoint 바로 앞(10ms 안) request 를 보면, 앱 시나리오는 대부분 새 파일의 Write·unlink 예요(Shorts 63/65, YouTube 홈피드 93/104, TikTok 508/569). 대기 시나리오는 대부분 원래 있던 파일의 Write 예요(화면 꺼짐 30분 605/787). 대기 쪽은 시스템 sync 로 보여요.
- `cp_interval` 은 200초라 주기 Checkpoint 는 아니에요.

**고친 것 (v5 후보 2).** `gen_funcs.py` 는 원본 Checkpoint 바로 앞이 새 파일의 Write·unlink 이면 그 파일에 flag 16(새 폴더 안 파일)을 주고 마지막 Write 직후에 FS 를 넣어요(회차 전체 894개 파일). `uxwl` 은 이 파일을 `f/d<번호>/` 에 두고 처음 만들 때 폴더도 만들어요. Checkpoint 는 여전히 부르지 않고 f2fs 가 정해요. 같은 ftrace 로 TC Shorts 를 다시 보니 새 폴더 70개, "node needs cp" 62번이에요.

| 함수 (단독) | 통과 | FS Write MB 원본 / 전 → 후 | Checkpoint/s 원본 / 전 → 후 |
|---|---|---|---|
| Shorts 30회 넘기기 | 9 → 12 / 15 | 16.8 / 3.8 → 11.1 | 0.69 / 0.19 → 0.80 |
| YouTube 홈피드 40회 | 10 → 11 / 15 | 18.9 / 2.6 → 11.2 | 1.79 / 0.21 → 1.79 |
| 3앱 왕복 전환 ×6 | 13 → 15 / 16 | 5.7 / 1.3 → 3.8 | 0.35 / 0.09 → 0.38 |
| YouTube Shorts 20개 | 15 → 14 / 16 | 8.3 / 2.8 → 5.3 | 0.23 / 0.07 → 0.28 |
| TikTok 추천 영상 20개 | 15 → 14 / 16 | 84.8 / 81.8 → 73.5 | 5.55 / 4.49 → 4.15 |

- Checkpoint 횟수는 맞아졌어요. FS Write 는 아직 60~70% 예요. Checkpoint 한 번에 같이 쓰는 node 가 원본의 절반이에요(Shorts node 8.9 vs 4.3MB, meta 는 비슷). 원본 앱은 230초에 rename 639번을 하는데 TC 는 rename 을 재생하지 않아요. 다음 후보예요.
- 대기 시나리오의 시스템 sync Checkpoint 는 이 수정으로 바뀌지 않아요.
- 같은 build 로 나머지 52개를 다시 돌리니 판정 717 → 737 이에요. 바뀐 함수 40개 중 Flush/s 13개, FS Write 10개, Checkpoint/s 7개가 새로 맞았어요. 나빠진 항목(Flush/s 8, QD p99 6)은 새 폴더 파일이 없는 회차에서도 나와 Run 사이 흔들림으로 봐요.

**원본 폴더 구조 (v5 후보 3, 2026-11-05).** 원본 앱은 파일을 회차마다 수백 개 폴더에 나눠 둬요(Chrome cold start 209개, 경로를 아는 파일 96%). TC 는 `f/` 하나에 모아서 Checkpoint 때 같이 쓰이는 폴더 inode·dentry page 가 적었어요. `gen_funcs.py` 가 파일마다 원본 상위 폴더 번호(경로 문자열은 넣지 않음)를 `dirs` 로 남기고, `uxwl` 이 같은 번호를 `f/g<번호>/` 에 둬요. 폴더는 prep 에서 만들고 재생 전 sync 로 Checkpoint 돼요. `tc.bin` 은 `UXWL0002`(파일마다 dir u32)이고 `UXWL0001` 도 그대로 읽어요. `--flat` 이 예전 방식이에요.

| 함수 (단독) | 통과 전 → 후 | FS Write MB 원본 / 전 → 후 | Checkpoint 묶음(50ms) 원본 / 후 |
|---|---|---|---|
| Chrome cold start ×5 | 12 → 12 / 16 | 12.0 / 4.2 → 5.1 | 17 / 11 |
| cold start 순회 6앱 | 12 → 13 / 16 | 12.8 / 4.2 → 5.9 | |
| 무거운 앱 cold start | 13 → 12 / 16 | 19.0 / 5.1 → 6.5 | 17 / 8 |
| YouTube 홈피드 40회 | 11 → 13 / 15 | 18.9 / 11.2 → 14.3 | 68 / 67 |
| 버스트샷 3초 | 11 → 10 / 16 | 10.4 / 4.1 → 3.7 | 4 / 1 |
| Chrome 100MB 다운로드 | 13 → 13 / 15 | 10.5 / 5.9 → 6.6 | |

- FS Write 는 15~40% 늘었지만 아직 원본의 30~75% 예요. 남은 차이는 두 가지예요. (1) 앱 실행·버스트샷은 Checkpoint 횟수가 원본의 절반이에요. 원본 Checkpoint 바로 앞 request 가 원래 있던 파일의 Read·Write 라 원인을 trace 만으로 모르고, ftrace 로 원본 시나리오를 다시 봐야 해요. (2) 횟수가 맞는 YouTube 홈피드도 Checkpoint 한 번의 node 가 원본의 60% 예요(10.1 vs 5.9MB). meta(NAT·SIT)는 횟수만 맞으면 같아요.

**시나리오 step 의 sync (v5 후보 4, 2026-11-05).** "Chrome cold start ×5", "cold start 순회 6앱", "무거운 앱 cold start" 는 앱을 띄우기 전마다 shell step 으로 `sync; echo 3 > /proc/sys/vm/drop_caches` 를 해요. 앱 동작이 아니라 측정 절차지만 trace 구간 안에 있어서 원본 Checkpoint 의 일부가 여기서 나와요. trace 에서는 drop_caches 뒤 `sh` 가 실행 파일을 다시 읽는 Read burst(0.3초 안 20개 넘게)로 보이고, Checkpoint 가 0.2초쯤 뒤에 와요. `gen_funcs.py` 는 시나리오 JSON 에서 trace 구간 안에 이 step 이 있는 시나리오만 골라, burst 시작 시각에 `SYNC`(op 16)를 넣어요(42번: 회차마다 5·6·3번). `uxwl` 은 그 시각에 `sync()` 를 불러요. `--no-sync` 로 끌 수 있어요.

| 함수 (단독) | 통과 폴더만 → sync | Checkpoint/s 원본 / 폴더만 / sync | FS Write MB 원본 / 폴더만 / sync |
|---|---|---|---|
| Chrome cold start ×5 | 12 → 13 / 16 | 0.45 / 0.40 / 0.74 | 12.0 / 5.0 / 9.7 |
| cold start 순회 6앱 | 13 → 14 / 16 | 0.47 / 0.36 / 0.36 | 12.8 / 5.9 / 6.9 |
| 무거운 앱 cold start | 12 → 12 / 16 | 0.68 / 0.43 / 0.50 | 19.0 / 6.5 / 7.1 |

- Chrome cold start 는 Checkpoint 시각이 원본과 거의 겹쳐요(50ms 묶음 원본 17, TC 20). Checkpoint/s 가 넘치는 것은 TC Checkpoint Write 가 1ms 넘게 끊기는 일이 많아서예요(1ms 묶음 30 vs 39, request 864 vs 858). 첫 sync 가 TC 앞부분의 다른 앱 dirty data 까지 내려 1.6MB Checkpoint 가 하나 더 생기기도 해요. 세는 방식과 배경 상태 차이라 고치지 않았어요.
- 무거운 앱 cold start 는 횟수가 맞아도 FS Write 가 원본의 37% 예요. Checkpoint 한 번의 node 가 작은 문제(위 (2))가 남아 있어요. 원본 YouTube 홈피드의 Checkpoint node Write 9.8MB 는 Read 만 한 inode 에 붙어 있고, 그중 6.5MB 가 ino 4 하나라 귀속 오류일 수 있어요. 확인 중이에요.

**direct Write 를 하나씩 (v5 후보 5, 2026-11-05).** 카메라 사진 함수는 direct Write 가 원본에서 512KB 이어진 request 로 나가는데 TC 는 4KB 로 쪼개졌어요(버스트샷 3초 1.6GB 가 4KB request 3만 5천 개). 이 커널(6.12, `mode=adaptive`)은 새 block 을 할당하는 direct pwrite 두 개가 겹치면 두 파일에 block 을 하나씩 번갈아 할당해요. 폰에서 파일 5개에 2MB direct pwrite 를 동시에 내면 16MB 파일이 extent 700~2,700개, 하나씩 내면 8개(2MB 마다 하나)였어요. fallocate, 확장자(.jpg), `/data/media`, FUSE, AIO 로는 바뀌지 않았어요(할당하는 direct Write 는 `io_submit` 안에서 끝까지 기다려요). 원본 앱이 어떻게 겹침을 피하는지는 모르지만 배치는 하나씩 낸 것과 같아요. 그래서 `uxwl` 의 `--max-wd` 기본값을 3 → 1 로 바꿨어요. 하나씩이 동시보다 빨랐어요(80MB 48ms vs 93ms). `gen_funcs.py` 는 같은 파일에서 offset 이 이어지고 1ms 안에 온 WD 조각을 pwrite 하나로 합쳐요(16MB 까지, `--no-merge-wd` 로 끔). 합치기만으로는 바뀌지 않았어요.

| 함수 (단독) | 통과 전 → 후 | Request size W ≤4KB % 원본 / 전 → 후 | Sequential Write % 원본 / 전 → 후 | QD p99 원본 / 전 → 후 |
|---|---|---|---|---|
| 사진 10장 | 12 → 14 / 16 | 37 / 79 → 38 | 89.7 / 78.1 → 94.2 | 47 / 63 → 27 |
| 버스트샷 3초 | 10 → 12 / 16 | 34 / 86 → 31 | 86.6 / 72.5 → 93.1 | 23 / 63 → 59 |
| 사진 5장 → 바로 갤러리 | 11 → 13 / 16 | 62 / 82 → 68 | 80.4 / 68.3 → 85.7 | 43 / 63 → 27 |
| 전면 카메라 사진 5장 | 12 / 12 → 11 / 11 | 28 / 33 → 21 | 96.2 / 96.8 → 98.2 | 8 / 7 → 5 |

- 함수 단독 합계는 744/920 → 749/918 이에요(전면 카메라는 원본 FS Write 가 작아 판정에서 빠졌어요). 결과 보관: 전 `func-matrix-sync.json`, 합치기만 한 것 `func-matrix-wdmerge.json`.
- 버스트샷 QD p99 는 여전히 원본보다 높아요. FS Write 는 그대로라 이 수정과 상관없어요.

**임시 파일은 지우지 않고 rename (v5 후보 6, 2026-11-06).** fsiotrace 가 Checkpoint node page 의 주인 inode 를 page 마다 남기게 됐어요(`result_fsio_cpnode.parquet`, GUIDE 8절). 새로 잰 "YouTube 홈피드 40회" 1회차에서 Checkpoint node 2,367 page 중 830 page 가 이름이 `.tmp` 로 끝나는 새 파일 523개의 것이었어요. TC 는 trace 에 unlink 가 안 보여서 이런 파일을 마지막 접근 직후 지웠고(`segments.py` UL), 지운 파일의 node 는 Checkpoint 에 나오지 않아 같은 자리가 242 page 였어요. 원본 `.tmp` inode 는 Checkpoint 두 번 넘게 나온 것이 305개라 몇 초 넘게 살아 있었어요. 지운 게 아니라 이름을 바꿔 남긴 것으로 봐요(AtomicFile, cache, 카메라 사진). 그래서 `segments.py` 는 이름이 `.tmp`·`.temp` 인 새 파일을 지우지 않고 rename 하고(RN), `uxwl` 은 op 17 `RENAME` 으로 `<이름>.r` 로 바꿔 둬요. `-journal` 과 같은 이름의 앞 inode 는 지금처럼 지워요. `UX_TMP_UNLINK=1` 이면 예전처럼 지워요.

새로 잰 원본 16개(새 fsiotrace)로 두 방식을 한 번씩 돌린 결과예요.

| 함수 (단독) | 바로 지우기 → rename | 원본 FS Write MB / 지우기 → rename | Checkpoint node page 원본 / 지우기 → rename |
|---|---|---|---|
| YouTube 홈피드 40회 | 12 → 13 / 15 | 21.8 / 14.5 → 15.6 | 2,367 / 1,475 → 2,020 |
| Shorts 30회 넘기기 | 15 → 14 / 16 | 12.6 / 8.0 → 11.2 | 1,531 / 1,085 → 1,591 |
| YouTube Shorts 20개 | 15 → 16 / 16 | 7.9 / 6.1 → 7.5 | 1,023 / 861 → 1,116 |
| 백그라운드 5분 뒤 복귀 | 7 → 14 / 16 | 3.8 / 10.0 → 2.8 | |
| 사진 5장 → 바로 갤러리 | 11 → 16 / 16 | 3.8 / 9.6 → 3.5 | |
| 버스트샷 3초 | 11 → 12 / 15 | 7.4 / 0.3 → 0.3 | 845 / 435 → 979 |

- 16개 합계 202 → 218 / 252, 함수 단독 전체 749/919 예요(원본 16개가 바뀌어 판정 수가 하나 늘었어요. 앞의 749/918 은 바뀌기 전 원본 기준). 결과 보관: `func-matrix-newmeas-unlink.json`, `func-matrix-newmeas-rename.json`.
- "백그라운드 5분 뒤 복귀" 와 "사진 5장 → 바로 갤러리" 는 바로 지우면 Checkpoint/s 가 원본의 3배, 10배였어요(2.48 vs 0.8, 2.15 vs 0.2). 지우는 동작이 Checkpoint 를 더 부른 것으로 봐요.
- "Shorts 30회 넘기기" 는 FS Write 가 맞게 됐지만 Flush/s·QD p99 가 새로 틀렸어요. Run 한 번이라 흔들림인지 아직 몰라요.
- 버스트샷은 Checkpoint 크기가 원본과 같아졌지만 시각이 달라요. 원본은 3.9초에 한 번(845 page) 났고, TC 는 재생이 끝난 뒤(17.4초)에 나서 비교 구간 밖이에요. 원본 카메라 함수의 Checkpoint 는 거의 모두 Files 앱 DB(`files_master_database`)의 WAL fsync 1~2ms 뒤에 와요(사진 10장 17/19번, 버스트샷 13/14번). 이 WAL 은 회차마다 inode 가 4~8개로 바뀌어요(DB 를 닫으면 WAL 이 지워지고 다시 열면 새로 생겨요). TC 는 DB 를 재생 내내 열어 둬서 WAL 이 새로 생기지 않아요. 새로 생긴 WAL 의 fsync 바로 뒤 Checkpoint 는 화면 켜짐 시나리오 전체에서 278번이에요(`files_master_database` 97, `ns.db` 48, `phenotype.db` 15). f2fs 가 이 fsync 를 왜 Checkpoint 로 처리하는지(cp_reason)는 아직 확인하지 않았어요.

**새 WAL 은 DB 를 다시 열어 만들어요 (v5 후보 7, 2026-11-06).** 원본 "버스트샷 3초" 를 f2fs ftrace(`f2fs_sync_file_exit`)로 다시 봤어요. 일반 파일 fsync 는 모두 cp_reason 이 "no needed" 였고, Checkpoint 를 부른 건 폴더 fsync("non regular")였어요. 3회에 60번이고 41번이 Files 앱 "BG Thread" 였어요. SQLite 는 새로 만든 WAL 을 처음 sync 할 때 그 폴더도 fsync 해요(UNIXFILE_DIRSYNC). 앱이 DB 를 닫았다 다시 열면 WAL 이 새 inode 로 생기고, 그 첫 sync 마다 Checkpoint 가 하나씩 나요.
- `gen_funcs.py`: 원본에서 처음 보인 WAL inode 의 첫 Write 10 ms 안에 Checkpoint 가 왔으면 그 transaction 에 새 WAL flag(`0x10`)를 달아요. 새 WAL 마다 transaction 을 나눠요(원본은 70 ms 안에 WAL 을 네 번 새로 만들기도 해요). 61개 함수에 471번이에요.
- 같은 Checkpoint 를 원본 폴더 fsync 재생(DS)으로도 내던 것이 152번이라, 새 WAL 20 ms 안의 DS 는 뺐어요.
- `uxwl`: flag 가 달린 transaction 앞에서 DB 를 닫고 다시 열어요(`sqlReopens`). 폴더 fsync 는 SQLite 가 해요. 처음에는 `uxwl` 도 직접 폴더를 fsync 했는데 TC ftrace 에서 Checkpoint 가 두 번 나서, 그건 `--fresh-dirsync` 로만 켜요.

고치기 전과 고친 뒤(같은 build 로 두 번) 14개 함수 결과예요. 함수 단독 전체는 749 → 753, 752 / 919 예요.

| 함수 (단독) | 통과 전 → 1, 2 | FS Write MB 원본 / 전 → 1, 2 | Checkpoint/s 원본 / 전 → 1, 2 |
|---|---|---|---|
| 버스트샷 3초 | 12 → 14, 14 / 15 | 7.37 / 0.25 → 6.48, 6.32 | 0.25 / 0.00 → 0.16, 0.16 |
| 20장 삭제 → 휴지통 비우기 | 11 → 12, 13 / 16 | 4.06 / 0.80 → 2.51, 2.81 | 0.35 / 0.09 → 0.35, 0.35 |
| 동영상 2분 1080p | 14 → 16, 15 / 16 | 3.26 / 0.06 → 3.96, 2.95 | 0.07 / 0.00 → 0.06, 0.06 |
| 녹음 1분 | 13 → 14, 14 / 16 | 3.47 / 1.46 → 2.31, 2.60 | 0.13 / 0.06 → 0.11, 0.14 |
| 앱 재설치 (pm install) | 14 → 14, 14 / 16 | 7.36 / 4.26 → 5.61, 5.69 | 0.44 / 0.28 → 0.52, 0.56 |
| 사진 10장 | 15 → 14, 12 / 16 | 4.24 / 3.53 → 3.59, 4.86 | 0.29 / 0.16 → 0.29, 0.86 |
| 사진 5장 → 바로 갤러리 | 16 → 14, 15 / 16 | 3.78 / 3.49 → 3.15, 3.33 | 0.19 / 0.30 → 0.23, 0.26 |
| 무거운 앱 cold start | 11 → 12, 11 / 16 | 29.80 / 13.05 → 13.03, 12.31 | 2.16 / 1.62 → 1.81, 1.71 |

- 통과 열의 분모는 함수마다 판정 항목 수예요. 14개 함수 합은 187 → 191, 190 이고, 나머지 47개 함수는 다시 돌리지 않아 전체가 749 → 753, 752 예요.
- Checkpoint 가 없거나 모자라던 "버스트샷 3초", "20장 삭제 → 휴지통 비우기", "동영상 2분 1080p" 에 Checkpoint 와 FS Write 가 원본 가까이 생겼어요. 표에 없는 6개(cold start 순회 6앱, YouTube Music 3분, Chrome 100MB 다운로드, Chrome cold start ×5, 뷰어 1→1000장, 백그라운드 5분 뒤 복귀)는 통과 수가 ±1 안에서 움직였어요.
- "사진 10장" 2번째 Run 의 Checkpoint/s 0.86 은 같은 funcs.bin 1번째(0.29)의 3배라 Run 사이 흔들림으로 봐요. 배경 sync_fs(autosuspend) 같은 시스템 Checkpoint 가 섞였는지는 아직 몰라요.
- fsync/s 는 여전히 원본보다 높아요(버스트샷 10.1 vs 3.5). "무거운 앱 cold start" FS Write 는 이 수정으로 바뀌지 않았어요.
- 결과 보관: `func-matrix-pre-freshwal.json`, `func-matrix-freshwal3-1.json`, `func-matrix-freshwal3-2.json`.

### 14.4 함수 하나씩 결과 (2026-11-05, Run 한 번)

61개 함수, 판정 항목 920개 중 744개 통과(81%). 11-03 은 927개 중 717개(77%)였어요. 그 뒤 새 폴더 flag, 원본 폴더 구조, 시나리오 sync(14.3)를 넣고 모두 다시 돌렸어요. 결과는 `.private/results/func-matrix.json`, sync 전은 `func-matrix-dirs.json` 이에요. 같은 build 로 다시 잰 10개는 함수마다 1~3개씩 흔들렸어요.

| 유형 | 함수 | 통과 |
|---|---|---|
| 메일·스토어 | 2 | 94% |
| 브라우저 | 4 | 88% |
| SNS | 3 | 88% |
| 음악 | 1 | 88% |
| 앱 실행 | 8 | 87% |
| 동영상 | 10 | 86% |
| 갤러리 | 7 | 81% |
| 생산성 | 4 | 81% |
| 카메라 | 8 | 80% |
| 저장소 | 8 | 76% |
| 지도 | 1 | 69% |
| 대기 | 4 | 57% |
| 홈 | 1 | 53% |

- 가장 많이 틀린 항목(틀린 함수 수): FS Write 31, FS Write 비율 22, Flush/s 20, QD p99 19, Sequential Write 18, fsync/s 13. 14.3 과 같은 방향이에요.
- 채움 테이블 비중은 DB WAL frame 의 28% 예요. 함수마다 달라서 Instagram·갤러리는 절반 가까이예요. 행 동작만으로 원본 양을 다 못 내는 DB 가 많다는 뜻이에요.
- 원본의 일부 DB Write(`ttm_strategy.db`, `gphotos0.db`)에는 fsync flag 가 없어요. 어떤 호출인지 확인하지 않았어요. TC 는 SQLite 가 fsync 를 불러서 fsync/s 가 원본보다 많게 나와요.

### 14.5 가중치 TC 결과 (2시간, Run 한 번씩)

| TC | 가중치 | 실제 비중 | 구간별 통과 | 같은 함수 단독 | 전체 |
|---|---|---|---|---|---|
| m1 | sns 0.4, video 0.3, camera 0.2, standby 0.1 | 모두 목표 ±1%p | 76.3% | 85.9% | 13/16 |
| m1w (DB warm-up) | 같음, 같은 seed | 같음 | 78.9% | 85.9% | 13/16 |
| m2 | browser·sns·video 0.2, camera·launch·home·gallery 0.1 | 모두 목표 ±1%p | 74.2% | 83.3% | 13/16 |
| m2w (DB warm-up) | 같음, 같은 seed | 같음 | 77.6% | 83.3% | 12/16 |
| m2d (원본 폴더 구조, 시나리오 sync) | 같음, 같은 seed | 같음 | 80.3% | 86.2% | 12/16 |
| m2e (direct Write 하나씩) | 같음, 같은 seed | 같음 | 83.0% | 88.2% | 15/16 |

- **m2d (11-05).** m2w 에 원본 폴더 구조와 cold start 시나리오의 `sync` 재생(14.3)을 더했어요. 구간별 통과가 77.6% → 80.3% 예요. 구간 실패율은 FS Write 54% → 46%, FS Write 비율 36% → 22%, Checkpoint/s 30% → 18%, Flush/s 30% → 22% 로 줄었어요. 앱 실행 유형은 14/16 → 16/16 이에요. 전체 판정에서 FS Write 는 통과(원본 767 MB, TC 614 MB)로 바뀌었고, 대신 Sequential Write 가 틀렸어요(원본 79.6%, TC 67.9%). 2시간 동안 "R: operation not supported" 가 40번 나왔어요.
- **m2e (11-05).** m2d 에 direct Write 를 하나씩 내는 수정(14.3, `--max-wd 1`)을 더했어요. 구간별 통과가 80.3% → 83.0% 예요(905/1091). 구간 실패율은 Sequential Write 41% → 24%, Request size W 26% → 거의 0, QD p99 36% → 27% 로 줄었어요. 카메라 유형은 10/16 → 14/16 이에요. 전체 판정은 12/16 → 15/16 이고, Sequential Write(원본 79.6%, TC 84.1%), Request size W, QD p99 가 통과로 바뀌었어요. 남은 하나는 fsync/s(원본 1.66, TC 3.64)예요. 같은 함수 단독 값은 11-05 함수 단독 결과(749/918) 기준이에요. "R: operation not supported" 는 6번이에요.

- **DB page cache.** 가중치 TC 는 모든 DB 를 재생 전에 열고 채워요. 1~2시간 뒤에 도는 함수의 DB page 는 cache 에서 밀려나 있어서 함수 첫 5초에 DB 본체·WAL Read 가 원본보다 수 MB 많았어요(Instagram 피드 0.6 vs 12MB). 같은 구간이 두 번째 나올 때는 원본과 같았어요. 그래서 DB 를 60초 넘게 안 쓰다가 다시 쓰는 함수는 시작 10초 전(함수 사이 쉬는 구간)에 DB 파일을 한 번 읽어 둬요(`sqlWarms`). 구간 판정에서 Read Volume 실패가 39% → 거의 0, Request size Read 가 36% → 거의 0 이 됐어요. 함수 단독 실행은 시작이 60초 안이라 바뀌지 않아요.
- **남은 차이.** Checkpoint/s 는 원본보다 적어요(14.3). QD p99 는 원본보다 높은 구간이 많아요. 앞 함수의 writeback 이 다음 함수 구간에 이어지는 것으로 보는데 확인하지 않았어요. 함수를 이어 돌리면 생기는 차이라 고치지 않았어요.
