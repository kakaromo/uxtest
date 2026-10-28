# uxtest 작업 규칙

스마트폰 UX 시나리오를 돌리며 UFS trace(fsiotrace `fsio_ufs`)를 모으고, 분석 사이트(https://kakaromo.github.io/uxtest/)와 UFS workload TC(`wl/`)를 만드는 저장소예요. 실행 방법은 `GUIDE.md`.

저장소 세 개를 같은 상위 폴더에 둬요: `uxtest/`(이 저장소), `agent/`(시나리오 실행기, `../agent --standalone`), `bpftrace/`(fsiotrace 소스).

## 글쓰기
- 문장은 한국어 해요체. em-dash(—) 쓰지 않음.
- 용어는 영어: Read/Write, Discard, Latency, QD, Sequential/Random, Idle, Wakeups, LBA, Run, Jank frame, UFS, request, flag, mgmt command, attribution, burst, DtoD/CtoD/DtoC. 채팅 보고에서도 같아요. 사이트 해설은 `report/terms.py` 가 배포 때 바꾸지만 Svelte 화면 문구는 직접 영어로 써요.
- 시나리오는 ID(A1, B7t) 대신 이름("Chrome 첫 실행", "TikTok feed")으로 불러요. ID 는 필요할 때만 괄호로. 이름은 `scenarios/*/*.scenario.json` 의 `name`.
- 지표: DtoD = dispatch 간격, CtoD = 앞 request 완료부터 다음 dispatch 까지(0 = overlap), DtoC = Latency.

## 기기와 측정
- **측정이나 TC 가 도는 동안 폰에 어떤 명령도 보내지 않아요** (adb shell, find, dumpsys 포함). trace 가 오염돼요. `.claude/hooks/no-adb-while-measuring.sh` 가 막아요. 정말 필요하면 명령 앞에 `UX_ALLOW_ADB=1` 을 붙이고 이유를 남겨요.
- 측정과 TC 는 USB 를 빼고 배터리·무선 adb 로 해요 (`scenarios/setup.sh --wifi`). USB 전원이면 deviceidle 이 ACTIVE 라 Discard·배경 I/O 가 달라져요.
- 권한 요청 창은 "허용 안함"(permission_deny_button)을 눌러 닫아요. 그 밖의 동의·로그인·약관 창은 대신 누르지 않아요.
- 개인 계정은 그대로 쓰고 흔적을 남기지 않아요: 좋아요·팔로우·댓글·로그인 금지.
- 요청 없이 기기 시스템 설정을 바꾸지 않아요.
- fsiotrace 는 두 개를 동시에 붙이지 않아요. 로그에 `writing events` 가 나온 뒤에 동작을 시작해요.
- perfetto trace 는 `/dev` 에 저장해요 (/data 에 쓰면 측정이 오염돼요).
- agent 시나리오 함정: step 파라미터에 콤마를 넣으면 회차별 값으로 잘려요. text 스텝은 Gboard 한국어 모드면 깨져요. 시간 제한(예: 60초)이 걸린 Step 코드는 버그로 보고 고쳐요.

## 데이터와 커밋
- 공개 저장소예요. `.gitignore` 는 허용 목록 방식이라 새 파일은 whitelist 에 넣어야 올라가요.
- 커밋 금지: `runs/`, 원자료(parquet 등), `wl/.private/`, `DESIGN.md`, `report/confluence.py`, `../agent/config/devices.toml`(minio secret).
- secret·token·비밀번호는 읽어서 출력하거나 인용하지 않아요.
- 사용 로그 데이터셋은 라이선스가 불명이에요. 거기서 뽑은 값(카테고리 비중, 세션 분포 등)은 커밋·공개하지 않아요. `wl/.private/` 에만 둬요.
- 2026-10-28 이전 trace(`report/extract.py` 의 `FIX_AT` 이전)의 파일 이름·comm·NODE/META/Checkpoint/fsync flag 는 믿지 않아요. Volume·size·LBA·Latency 는 맞아요.

## 자주 쓰는 명령
- 사이트 갱신: `report/publish.sh` (extract → build_report → export_web → copy-data → 커밋·push)
- 시나리오 생성: `python3 scenarios/gen.py` (JSON 을 직접 고치지 말고 gen.py 를 고쳐서 다시 생성)
- 귀속 점검: `python3 report/audit.py <parquet>...`
- 웹 확인: `cd web && npm run check && npm run build`

## subagent (`.claude/agents/`)
| agent | 맡는 일 |
|---|---|
| fsiotrace-dev | `../bpftrace` 수정·빌드·설치, 귀속 검증 |
| site-writer | 해설(`build_report.py`), `terms.py`, Svelte 페이지, 배포 |
| scenario-author | 시나리오 작성, `gen.py` 동기화 |
| trace-analyst | parquet 분석, 해설 문장 검증, TC 와 원본 비교 (읽기 전용) |
| release-checker | 커밋 전 검사 (읽기 전용) |

폰을 쓰는 일(측정, setup 시험, TC 실행)은 메인 대화에서만 해요.
