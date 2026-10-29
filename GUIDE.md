# uxtest 실행 가이드

Android 기기에서 UX 시나리오(앱 실행, 웹·피드, 미디어, 카메라, 파일, 생산성, 갤러리, 대기)를 재현하고, 그동안 UFS에 들어간 request를 eBPF 수집 도구(fsiotrace)로 기록해 분석하는 방법이에요. 다른 PC·기기에서 같은 평가를 다시 할 수 있게 순서대로 적었어요.

```
[uxtest/run.py] ──REST──▶ [agent --standalone] ──adb──▶ 기기
                              │  시나리오 Step 실행 (tap, scroll, shell …)
                              │  trace_start/stop → /dev/fsiotrace (eBPF)
                              ▼
            ~/.agent-standalone/archive/jobs/<시각>_<시나리오>/trace/<id>/result_fsio_ufs.parquet
                              ▼
[report/extract.py → export_web.py → web/] ──▶ 분석 사이트 (GitHub Pages)
[wl/] ──▶ UFS workload TC (측정한 trace 를 파일 동작으로 재생, 원본과 비교)
```

## 1. 준비물

### PC

| 항목 | 용도 | 비고 |
|---|---|---|
| Python 3.11+ | `run.py`, 분석 스크립트 | `pip install duckdb numpy` |
| adb (platform-tools) | 기기 연결 | |
| Node.js 20+ | 분석 사이트 (`web/`) | `cd web && npm ci` |
| Docker | fsiotrace 빌드 (linux/amd64 컨테이너) | Apple Silicon 이면 `--platform linux/amd64` |
| Android NDK r26d (Linux 판) | fsiotrace 빌드 | 컨테이너에 마운트해서 씀 |
| Go 1.25 | TC 재생기(`wl/replay`) 빌드 | TC 를 쓸 때만 |

### 저장소 세 개를 같은 상위 폴더에

```
project/
  agent/      # 시나리오 실행·trace 수집 서버 (사내 저장소)
  bpftrace/   # fsiotrace 소스 (github.com/kakaromo/bpftrace)
  uxtest/     # 이 저장소: 시나리오, 실행기, 분석, 사이트, TC
```

`scenarios/gen.py` 는 `../agent/docs/schemas/scenario.schema.json` 을, 실행 스크립트는 agent 의 기본 주소(`http://127.0.0.1:50051`)를 씀.

### 기기

- root adb 가 되는 기기 (userdebug/eng 빌드 또는 root). `adb shell id` 가 `uid=0` 이어야 eBPF 를 붙일 수 있어요.
- 개발자 옵션, USB 디버깅. 배터리 측정을 하려면 무선 디버깅도 켜요(아래 4절).
- 지금 시나리오의 좌표·패키지는 **OnePlus CPH2749 (1272×2772, OxygenOS, Android 16)** 기준이에요. 다른 기기면 5.4절을 보고 고쳐야 해요.

## 2. 수집 도구 fsiotrace 빌드

agent 는 `agent/tools/fsiotrace` 를 기기 `/dev/fsiotrace`(tmpfs) 로 올려 써요. 기기에 있는 것과 **크기가 다르면 자동으로 다시 push** 해요.

```sh
cd bpftrace
docker build --platform linux/amd64 -t fsiotrace-build -f Dockerfile .      # 처음 한 번
docker run --rm --platform linux/amd64 \
  -v $PWD:/src -v <NDK r26d 경로>:/opt/ndk:ro -e ANDROID_NDK_HOME=/opt/ndk -w /src \
  fsiotrace-build make NDK=/opt/ndk VMLINUX_BTF=/src/vmlinux.btf
cp out/aarch64/fsiotrace ../agent/tools/fsiotrace
```

- **2026-10-28 이후 버전(2b14f12 이상)을 쓰세요.** 그 전 버전은 writeback·공유 bio·kblockd 발급 request 에 다른 파일·앱 이름과 NODE/META/Checkpoint flag 를 붙였어요(Write 의 최대 38%). Volume·size·LBA·Latency 는 영향이 없지만 이름·flag 기반 분석은 틀려요.
- 2b14f12 에서 더 고친 것: fsync 안에서 나간 request 에 `FSYNC_TRIGGERED` 가 붙어요(그 전에는 늘 0). `REQ_SYNC`·`REQ_PRIO` 도 이제 나와요. 다른 파일시스템(cgroup 등)의 같은 inode 번호 이름이 f2fs Write 에 붙던 문제도 막았어요.
- 빌드 확인: `adb shell /dev/fsiotrace --version`. 시작할 때 BPF load 가 `-EAGAIN` 이면 스스로 최대 4번 다시 시도해요.

## 3. agent 실행

```sh
cd agent
./agent --standalone -config config/devices.toml          # 기본 127.0.0.1:50051
# 다른 PC 에서 붙으려면: --bind 0.0.0.0
```

- 브라우저로 `http://127.0.0.1:50051` 을 열면 agent UI 가 나와요(시나리오 캔버스, 실행 기록).
- `config/devices.toml` 의 `[minio]` 같은 접속 정보는 사내 값으로 두고 **저장소에 올리지 마세요.** standalone 모드에서는 쓰지 않아요.
- 결과 보관 위치: `~/.agent-standalone/archive/jobs/<시각>_scenario_<이름>/trace/<trace job id>/result_fsio_ufs.parquet`

## 4. 기기 준비

### 4.1 연결

USB 로 측정하면 기기가 충전 상태라 결과가 달라져요(deviceidle 이 ACTIVE 로 남아 f2fs Discard 가 화면 켜진 동안 안 나가요). **본 측정은 USB 를 빼고 무선 adb 로** 해요.

```sh
adb devices                                          # USB 로 처음 연결 (serial 확인)
UX_SERIAL=<USB serial> scenarios/setup.sh --wifi     # 무선 adb 로 전환 + 배터리 측정용 설정
# 출력된 export 줄을 실행하고 USB 를 뽑는다
UX_SERIAL=<USB serial> scenarios/setup.sh --usb      # (되돌리기) 무선 adb 끄기
```

`--wifi` 가 하는 일: root 확인 → Wi-Fi IP 확인 → `setprop persist.adb.tcp.port 5555`(USB 를 뽑거나 재부팅해도 무선 adb 가 남음) → `adb tcpip`·`adb connect` → 무선 root 확인 → 배터리 설정(`BATTERY_SETTINGS`, 원래 값은 `--restore` 로 되돌림).

배터리 설정 중 OxygenOS 배터리 앱의 **수면 대기 최적화(Deep Sleep)** 는 학습한 수면 시간대에 Wi-Fi 를 꺼서 밤 측정이 끊겨요. 이 설정의 key 를 찾기 전까지는 설정 앱에서 직접 꺼 주세요.

agent 는 adb serial 을 device id 로 써요. 무선이면 `<IP>:5555` 가 device id 예요.

### 4.2 측정 전 준비 스크립트

```sh
UX_SERIAL=<serial> scenarios/setup.sh          # 준비 + 점검 (여러 번 실행해도 됨)
UX_SERIAL=<serial> scenarios/setup.sh --restore   # 측정 뒤 되돌리기
```

Perfetto 설정 배치, 로컬 동영상 fixture(`/sdcard/Movies/uxtest_fixture.mp4`) 생성, 앱 첫 실행 화면 점검을 해요.

### 4.3 갤러리 사진 (NASA 퍼블릭 도메인 1000장)

```sh
python3 dataset/nasa/fetch.py                  # 목록(manifest.csv)대로 받기 (사진은 커밋 안 함)
UX_SERIAL=<serial> python3 dataset/nasa/push.py          # 기기 /sdcard/Pictures/NASA 에 넣기
UX_SERIAL=<serial> python3 dataset/nasa/push.py --repush # 갤러리 cold 측정 직전: 새 파일명으로 다시 넣기
```

- 받는 곳: NASA Image and Video Library(`images-api.nasa.gov`, 이미지는 `images-assets.nasa.gov`). 저작권 표기가 있는 항목은 빼서 퍼블릭 도메인만 받아요.
- 1000장, 약 1.8GB. 저장소의 `manifest.csv` 목록과 sha256 으로 받아서 **어디서 받아도 같은 사진**이에요. 중간에 끊겨도 다시 실행하면 이어 받아요. 시험용은 `--n 50`.
- 회사 망에서 위 주소가 막혀 있으면, 받을 수 있는 곳에서 `dataset/nasa/images/` 를 받아 그대로 복사해도 돼요(fetch.py 를 다시 돌리면 sha256 만 확인하고 건너뛰어요).

### 4.4 사람이 한 번 해 둘 것

- 앱 로그인: Instagram(피드·릴스), YouTube, Gmail. TikTok 은 첫 실행 동의 창만 처리.
- Google 의 "휴대전화 설정 마저 하기"(setupwizard) 화면을 끝내 두세요. 측정 중에 떠서 tap 이 그 화면에 눌린 적이 있어요.
- 화면 잠금은 보안 잠금 없이(스와이프) 두세요. 시나리오가 `wm dismiss-keyguard` 로 풀어요.
- 개인 계정이면 흔적이 남지 않게 시나리오는 스크롤만 하고 게시물·영상을 탭하지 않아요(좋아요·팔로우 방지). 알림 등 권한 창은 시나리오가 '허용 안함'을 눌러 닫아요.

## 5. 시나리오

### 5.1 파일 구조

`scenarios/<유형>/<ID>.scenario.json` 하나가 시나리오 하나예요(agent 이식 포맷, `kind: "scenario"`). 목록과 설명은 `scenarios/SCENARIOS.md`.

```json
{
  "kind": "scenario",
  "name": "[UX-fsio] B7y YouTube Shorts 20개",
  "description": "[B7y · P2] …",
  "repeatCount": 3,            // 3번 측정. 회차마다 trace job 이 따로 생겨요
  "keepAwake": true,           // (선택) 화면을 보며 기다리는 시나리오. run.py 가 10초마다 화면을 깨워요
  "steps": [
    {"type": "shell", "params": {"cmd": "...", "label": "화면 켜기·잠금 해제"}},
    {"type": "stop_app", "params": {"package_name": "..."}},
    {"type": "trace_start", "params": {"trace_type": "fsio_ufs", "window_seconds": "1", "include_vfs": "false", "include_dram": "false"}},
    {"type": "scroll", "params": {"direction": "down", "count": "20", "pause": "5", "duration": "300"}},
    {"type": "trace_stop", "params": {"trace_type": "fsio_ufs"}},
    {"type": "shell", "params": {"cmd": "dumpsys window | grep mCurrentFocus", "label": "화면 확인"}}
  ]
}
```

측정 구간은 `trace_start` ~ `trace_stop` 이에요. 준비(캐시 비우기, 앱 실행)와 확인(`mCurrentFocus`)은 구간 밖에 둬서 측정을 오염시키지 않아요.

### 5.2 agent 에 넣는 두 가지 방법

1. **run.py 로 실행 (권장, 미리 등록할 필요 없음).** `run.py` 가 JSON 의 steps 를 그대로 agent REST API(`POST /api/agent/scenario/run`)로 보내요. 결과 JSON 을 `runs/` 에 남기고 Perfetto 결과도 가져와요.
2. **agent UI 에 가져오기.** UI 의 시나리오 캔버스 → 툴바 "파일에서 가져오기" → `.scenario.json` (여러 개는 `scenarios/gen.py` 가 만드는 `pack.scenariopack.json`). 화면에서 Step 을 보고 고치거나 손으로 돌릴 때 써요. 이 방법으로 돌린 결과는 `runs/` 에 남지 않아서 분석 스크립트가 못 찾아요. 본 측정은 1번으로 하세요.

### 5.3 새 시나리오 만들기·고치기

- 시나리오는 `scenarios/gen.py` 에 정의돼 있고, `python3 scenarios/gen.py` 가 JSON 과 `pack.scenariopack.json` 을 만들면서 agent 스키마로 검사해요. **고칠 때는 gen.py 를 고치고 다시 생성하세요.** JSON 만 직접 고치면 다음 생성 때 덮어써져요. (2026-10-28 기준 gen.py 와 JSON 은 같아요.)
- 자주 쓰는 Step 도우미가 gen.py 에 있어요: `launch`, `stop`, `scroll`, `tap_el`, `trace_start/stop`, `CLOSE_PERM`(권한 창 '허용 안함'), `FOCUS`(화면 확인), `SETTLE`(writeback 대기). 화면을 보며 오래 기다리는 시나리오는 `scenario(..., keep_awake=True)`.
- 고친 뒤에는 반드시 `./run.py --dry <ID>` 로 1회 돌려 Step 오류·화면(`mCurrentFocus`)을 확인해요.

지켜야 할 것 (실제로 걸렸던 함정)

| 규칙 | 이유 |
|---|---|
| Step 파라미터에 **콤마(,) 금지** | agent 가 콤마를 회차별 값 목록으로 잘라 써요. repeat>1 에서만 깨져서 dry-run 으로는 안 보여요. 셸에서 콤마가 필요하면 `tr ' ' '\054'` 로 기기에서 만들어요 |
| `text` Step 은 영문 키보드로 | `adb input text` 라 키보드가 한국어 모드면 영문이 자모로 바뀌어요 |
| 측정 결과 파일은 `/dev` (tmpfs) 에 | `/data` 에 쓰면 그 Write 가 UFS trace 에 섞여요 |
| 화면 확인은 `trace_stop` 뒤에 | 측정 구간에 불필요한 I/O 가 들어가지 않게 |
| 화면이 30초 넘게 입력 없이 기다리면 `keepAwake` | 배터리 상태에서는 화면이 꺼지고 다음 tap 이 잠금 화면에 눌려요 |
| 권한 창은 '허용 안함' 단계로 닫기 | `uiautomator dump` 로 `permission_deny_button` 을 찾아 tap (예: `B7y.scenario.json` 5번째 Step) |

### 5.4 다른 기기로 옮길 때

- 좌표: 화면 크기와 버튼 위치(셔터 `635,2420` 등)가 기기마다 달라요. 가능하면 `tap_element`(content-desc·text 로 찾기)를 쓰고, 좌표 tap 은 다시 재요.
- 패키지 이름: 갤러리 `com.oneplus.gallery`, 카메라 `com.oplus.camera` 처럼 제조사마다 달라요.
- 캐시 경로: 시나리오가 지우는 앱 캐시 폴더(예: Instagram `cache/images.stash`)가 버전마다 달라질 수 있어요.
- 파티션: 분석의 파티션 구분(userdata 시작 LBA 등)은 `/sys/block/sda/sda*/start` 로 다시 확인해요.

## 6. 측정 실행

```sh
cd uxtest
export UX_AGENT=http://127.0.0.1:50051        # 기본값
export UX_SERIAL=<IP>:5555                    # adb serial
export UX_DEVICE=<IP>:5555                    # agent device id (무선이면 serial 과 같음)

./run.py --dry A1                 # 1회 시험
./run.py A1 B7y                   # 본 측정 (시나리오의 repeatCount 대로)
./measure_battery.sh              # 화면 켜짐 시나리오 전체 (배터리·무선). UX_WIFI=<IP>:5555
./measure_standby.sh              # 대기 시나리오 (약 7.5시간)
UX_START=00:00 ./measure_night.sh # 야간 충전 대기 S6 (충전 중, USB adb, 6시간)
```

- 결과: `runs/<ID>/<시각>.json` (실행 로그, trace job id) + agent archive 의 parquet. 분석은 시나리오마다 **가장 최근** 실행 파일을 써요.
- `measure_battery.sh` 는 시나리오마다 충전 여부와 배터리를 보고, 충전 중이거나 20% 아래면 멈춰요.
- `measure_night.sh` 만 반대로 충전 중이어야 시작해요. 밤 idle maintenance(fstrim·GC)는 충전 중에만 돌기 때문이에요.
- **측정 중에는 기기에서 다른 명령을 돌리지 마세요.** adb 로 `find` 를 한 번 돌린 것도 trace 에 12MB 가 섞였어요.
- OxygenOS 의 배터리 앱 "Deep Sleep" 이 학습한 수면 시간대(예: 23:30~07:00)에 Wi-Fi 를 끄면 무선 adb 가 끊겨요. 밤새 측정은 그 시간대를 피하거나 수면 대기 최적화를 끄고 해요.

## 7. 분석과 사이트

```sh
python3 report/extract.py            # parquet → report/data.json (시나리오별 집계)
python3 report/build_report.py       # 해설 본문 → report/site/index.html (수치는 data.json 에서 계산)
python3 report/export_web.py         # 회차별 상세·해설 → web/.private/data/
node web/scripts/copy-data.mjs       # → web/static/data/ (사이트가 읽는 데이터)
cd web && npm run dev                # http://localhost:5173 로 확인
```

- `report/publish.sh` 가 위 단계를 한 번에 하고 `web/static/data` 를 커밋·push 해요. `main` 에 `web/**` 가 push 되면 GitHub Actions(`.github/workflows/pages.yml`)가 Pages 로 배포해요. 사내 배포라면 이 workflow 를 사내 저장소에 맞게 바꾸세요.
- 해설 본문은 `report/build_report.py`(하위 페이지 `report/pages.py`, 스타일 `report/web/`)가 만들어요. 수치는 data.json 에서 계산되지만, 문장 속 해석(예: "카메라 쓰기의 대부분은 중간 파일")은 측정을 다시 하면 맞는지 확인하고 고쳐야 해요. 다시 확인하기 전 문장에는 `chk()` 로 '확인 중' 표시를 붙여요.
- 기술 용어는 `report/terms.py` 표로 영어로 바꿔요(Read/Write, Discard, Latency, QD, request, flag …).

사이트에서 보는 주요 지표

| 지표 | 정의 |
|---|---|
| Volume | trace 구간의 Read/Write request 크기 합 (SCSI 40·136 = Read, 42·138 = Write) |
| Latency (DtoC) | request 를 보낸 뒤 완료까지 (`dtoc`) |
| DtoD | 앞 request 를 보낸 시각부터 다음 request 를 보낸 시각까지 |
| CtoD | 직전 request 완료부터 이번 request 를 보낼 때까지 (`ctod`, 0 = 앞 request 처리 중) |
| Idle | 100ms 칸 중 request 가 없는 칸 비율 |
| Wakeups | request 가 1초 넘게 끊겼다가 다시 온 횟수 |
| Metadata | Write 중 f2fs node·meta·checkpoint 비율 (flag 기반) |
| UFS mgmt command | Hibern8 진입·해제, Query(attribute·flag·descriptor), exception (Volume 등 다른 지표에서는 뺌) |

## 8. 수집 결과 점검 (선택)

fsiotrace 를 바꿨거나 다른 커널에서 쓸 때는 이름·flag 가 맞는지 먼저 확인해요.

1. **실제 시나리오 점검:** 서로 다른 시나리오 몇 개를 1회씩 돌리고, UFS Read/Write 바이트를 (앱/커널 스레드) × (파일 이름 있음/없음)으로 나눠 봐요 (`python3 report/audit.py <parquet>...`). 커널 스레드·이름 없음이 크면 그 줄의 파티션·fs·flag 를 보고 원인을 찾아요.
2. **정답지 대조 (Write):** ftrace `f2fs/f2fs_submit_folio_write` 를 같이 켜고 버퍼 Write + `sync` 를 일으킨 뒤, ftrace 의 `newaddr`(+ userdata 시작 LBA)로 UFS Write request 의 주인 inode 와 fsiotrace 가 붙인 inode 를 비교해요. 2026-10-28 기준 결과는 오귀속 0% 예요.
3. fsiotrace 를 두 개 동시에 붙이지 마세요. 둘 다 이벤트를 크게 놓쳐요. 그리고 fsiotrace 가 붙는 데 10~20초 걸리므로 출력 로그에 `writing events` 가 나온 뒤에 작업을 시작해요.

남은 수집 한계: 여러 파일의 node 가 한 request 로 합쳐지면 첫 파일만 이름으로 남고, 측정 중 연 적 없는 파일의 node Write 는 경로 없이 `ino:N` 으로 나와요. f2fs GC 가 옮기는 데이터는 원래 파일을 알 수 없어 이름 없이 GC 로 표시돼요.

## 9. UFS workload TC (wl/)

측정한 trace 를 블록이 아니라 **파일 동작**(pwrite, fsync, O_DIRECT, unlink …)으로 바꿔 기기 `/data` 에서 재생해요. f2fs 가 Metadata·Checkpoint·Flush·Discard 를 직접 만들게 하고, 재생 trace 를 원본과 자동 비교해요.

```sh
cd uxtest/wl
make                                         # 재생기 uxwl (linux/arm64) → .private/uxwl
python3 segments.py                          # 측정 trace → 재생 조각 (.private/seg/)
python3 gen_tc.py seq --name cal-b7t B7t-1      # 측정 조각(시나리오-회차)을 순서대로 이은 TC
python3 gen_tc.py day --name day1 --seed 1   # 하루 TC (mix.json 가중치, 기본 2시간)
UX_SERIAL=<IP>:5555 python3 run_tc.py day1   # push → 재생 + trace → compare.py 자동
```

- `mix.json`: 카테고리 가중치 × 시나리오 가중치, 하루 이벤트(파일 삭제·다운로드 등), 화면 꺼짐 구간. `weight: null` 은 사용 로그 데이터셋 값을 쓰라는 뜻이에요.
- **`gen_tc.py day` 는 `wl/.private/usage.json`(사용 로그 데이터셋에서 뽑은 행동 모델)이 필요해요.** 이 데이터셋은 라이선스가 불명이라 저장소에 없고 공개하면 안 돼요. 회사에서 데이터셋을 따로 받은 뒤 `wl/usage.py` 의 `SRC` 경로를 받은 파일로 바꾸고 `python3 wl/usage.py` 를 돌리면 `wl/.private/usage.json` 이 생겨요(`.private` 는 커밋되지 않아요).
- 결과: `wl/.private/results/<TC>-<시각>/compare.json`, 추세는 `history.jsonl`. 비교 항목은 `wl/metrics.py` 의 `CHECKS`(Volume, FS 유발 Write, Flush, fsync, Discard, Checkpoint, size·DtoD 분포, Sequential, Idle, Wakeups, QD, Hibern8).
- TC 도 배터리·무선 상태에서 돌려요. 원본 측정 조건과 같아야 비교가 맞아요.

### 9.1 하루 TC 를 짜는 방식 (`gen_tc.py day`)

1. **화면 켜짐 세션을 뽑아요.** 사용 로그 데이터셋의 시간대별 세션 수·세션 길이로 하루 세션을 만들고, 하루 화면 켜짐 합이 `--on-min`(기본: 데이터셋 중앙값 사용자)이 되게 맞춰요.
2. **2시간 안에 넣어요.** `--hours`(기본 2)를 넘으면 하루 전체에 고르게 퍼진 순서로 세션을 골라 예산까지만 써요. 시간대 모양은 유지돼요.
3. **카테고리를 정해요.** 카테고리마다 "가중치 × 화면 켜짐 시간"만큼 방문을 먼저 만들고, 세션을 채울 때 다음 카테고리는 데이터셋 전이 확률 × 남은 할당량으로 골라요. 비중은 가중치대로, 순서는 실제 사용처럼 돼요. 끝에 목표·실제 비중 표를 출력해요.
4. **시나리오 조각을 붙여요.** 카테고리 안에서 시나리오 가중치로 시나리오를, 무작위로 회차를 골라요. 방문이 조각보다 길면 이어 붙이고(새 파일로), 짧으면 앞에서부터 잘라요. 측정이 없는 메시지는 SQLite WAL transaction 합성(`db`)으로 대신해요.
5. **앱이 바뀔 때 앱 실행 조각을 끼워요.** cold(`coldRatio`, 기본 20%)·warm 시나리오 하나를 실행 횟수 `n` 으로 나눈 한 조각이에요. 홈·통화는 빼요.
6. **세션 사이 화면 꺼짐을 대기 조각으로 채워요.** 길이는 `--standby-scale`(기본 2%)로 압축하고(최소 5초), 꺼진 시간 길이에 따라 `mix.json` 의 `standby` 구간(5분 이하·30분 이하·그 이상)에서 대기 시나리오를 골라요.
7. **하루 이벤트**(`daily`: 앱 재설치, 다운로드, 파일 삭제 …)는 하루 횟수만큼 화면 켜진 방문 사이 무작위 시각에 넣어요.

같은 `--seed` 면 같은 TC 가 나와요. `manifest.json` 의 `timeline` 에 구간마다 카테고리·조각·시각이 있어 이걸로 구성을 확인해요.

### 9.2 조각과 비교에서 알아 둘 점

- **조각은 기준 측정이 바뀌면 다시 만들어요** (`python3 segments.py`). 시나리오마다 `runs/<ID>/` 의 마지막 run 을 쓰므로, 기준 세트(배터리 측정)보다 뒤에 시험 run 을 남기지 않아요.
- **fsync 는 fsiotrace 의 FSYNC_TRIGGERED flag 로 가려요** (2026-10-28 이후 trace). 고친 fsiotrace 는 writeback·Checkpoint Write 의 comm 을 주인 앱으로 붙여서 comm 만으로는 앱 스레드를 알 수 없어요. 또 `is_writeback_kworker` 는 fsync 안 Write 와 O_DIRECT Write 에도 붙으므로, fsync flag 도 O_DIRECT 도 아닌 writeback 만 커널 몫으로 봐요.
- **측정 전에 Discard 가 다 나가길 기다려요.** `run_tc.py` 는 앞 TC 재생 파일을 지우고 채운 뒤 `/sys/fs/f2fs/*/pending_discard` 가 0 이 될 때까지(최대 15분) 기다렸다가 trace 를 시작해요. FITRIM 이나 f2fs 설정 변경으로 억지로 비우지 않아요.
- **같은 순간의 Read 는 Linux AIO 로 묶어 내요** (`replay/main.go` 의 `burstGap` 100µs, `burstSpan` 200µs). 원본은 thread 여러 개·readahead 가 Read 를 한꺼번에 내고 커널 block plug 가 묶어 보내 QD 가 50~60 까지 오르는데, pread 를 하나씩 부르면 QD 가 7 에 머물렀어요. 묶어 내면 이웃 Read 가 합쳐지지 않게 조각의 파일 offset 은 원본에서 떨어져 있던 구간 사이에 4KB 빈칸을 둬요 (`segments.py`).
- **Discard 는 판정하지 않고 값만 보여 줘요** (`metrics.py` 의 `INFO`). f2fs 가 idle 때 알아서 내므로 언제 나올지 TC 가 정할 수 없어요.
- **화면 꺼진 TC 에는 기기 배경 I/O 가 섞여요.** systemui `unlockcounter_prefs.xml` fsync(약 1/s), 제조사 서비스 DB 등이에요. 원본 I/O 가 많은 구간에는 영향이 없지만, YouTube·갤러리처럼 적은 구간은 fsync/s·Flush/s·Idle% 가 비율로 크게 어긋나 보여요.
  그래서 `compare.py` 는 TC trace 에서 `uxwl` 과 커널 문맥(kworker·f2fs·jbd2)의 request 만 세요 (`metrics.TC_ONLY`). 원본 조각은 그때 다른 앱 I/O 까지 uxwl 이 재생하므로 원본 쪽은 거르지 않아요. Flush·Checkpoint·Discard 는 누구 몫인지 나눌 수 없어 남기고, Hibern8 은 UFS 관리 명령이라 거를 수 없어요. 전부 세려면 `--all`.

## 10. 자주 생기는 문제

| 증상 | 원인·해결 |
|---|---|
| 한 회차 trace 가 비었음 (parquet 없음) | fsiotrace BPF load `-EAGAIN`. 5468503 이후 버전은 스스로 재시도. 그래도 비면 그 시나리오만 다시 측정 |
| tap 이 엉뚱한 곳에 눌림, 화면 확인에 setupwizard·잠금 화면 | 설정 마저 하기 화면을 끝내고, 보안 잠금을 끄고, 오래 기다리는 시나리오는 `keepAwake` |
| repeat 3 에서만 Step 이 깨짐 | 파라미터의 콤마 (5.3절) |
| 검색어가 자모로 입력됨 | 키보드 한국어 모드 (5.3절) |
| 밤에 무선 adb 가 끊김 | Deep Sleep 수면 시간대 (6절) |
| 분석이 parquet 을 못 찾음 | agent 가 archive 폴더 이름을 바꿀 수 있어요. 분석은 trace job id 로 다시 찾아요(`report/extract.py` 의 `parquet_of`) |
| 이름이 이상하게 붙음 (작은 로그 파일에 수백 MB 등) | 2026-10-28 이전 fsiotrace. 2절의 새 버전으로 다시 측정 |
| 충전 중 Discard 가 0 | USB 전원이면 deviceidle 이 ACTIVE 로 남아 f2fs Discard 가 늦어요. 배터리로 측정 |

## 11. Claude Code 로 작업할 때

저장소에 `CLAUDE.md`(공통 규칙)와 `.claude/`(subagent, hook)가 들어 있어요. Claude Code 를 `uxtest/` 에서 열면 자동으로 읽어요.

| subagent | 언제 부르나 | 권한 |
|---|---|---|
| fsiotrace-dev | fsiotrace 이름·flag 가 틀릴 때, 새 hook·커널 대응 | 수정·빌드 |
| site-writer | 해설 문장, 용어 변환, 사이트 페이지·차트, 배포 | 수정 |
| scenario-author | 새 시나리오, 기존 시나리오 수정, gen.py 동기화 | 수정 |
| trace-analyst | "이 시나리오 Write 는 누가 내나?" 같은 분석, 해설 검증, TC 비교 해석 | 읽기 전용 |
| release-checker | 커밋·push 전 검사 (원자료·secret·데이터셋 값·문장 규칙·빌드) | 읽기 전용 |

- 부르는 법: "trace-analyst 로 TikTok feed 의 fsync 를 내는 파일을 찾아줘"처럼 이름을 말하면 돼요.
- 폰을 쓰는 일(측정, `setup.sh`, TC 실행)은 subagent 에 맡기지 말고 메인 대화에서 해요.
- **hook:** 측정(`measure_*.sh`, `run.py`)이나 TC(`wl/run_tc.py`)가 도는 동안 Claude 가 보내는 `adb` 명령을 막아요 (`.claude/hooks/no-adb-while-measuring.sh`). 손으로 따로 측정할 때는 `touch runs/.measuring` 으로 켜고 끝나면 지워요. 꼭 필요한 명령은 앞에 `UX_ALLOW_ADB=1` 을 붙이면 통과해요.
- 개인 설정은 `.claude/settings.local.json` 에 두세요 (커밋되지 않아요).
