# uxtest

Android 기기에서 UX 워크로드(앱 실행, 웹·피드, 미디어, 카메라, 파일, 생산성, 갤러리, 대기)를 시나리오로 재현하고,
그동안 저장장치(UFS)에 들어간 요청을 eBPF(fsiotrace, `trace_type=fsio_ufs`)로 기록해 유형별 I/O 패턴을 분석한다.

분석 사이트는 GitHub Pages 로 배포한다: https://kakaromo.github.io/uxtest/ (공개)

## 구성

| 경로 | 내용 |
|---|---|
| `scenarios/gen.py` | 시나리오 정의 (agent 이식 포맷 JSON 생성) |
| `scenarios/setup.sh` | 측정 전 기기 준비 / `--restore` 원복 |
| `run.py`, `measure_*.sh` | agent(REST, standalone)로 시나리오 실행, 결과를 `runs/` 에 저장 (커밋 안 함) |
| `report/extract.py` | trace parquet → 시나리오 집계 `report/data.json` (커밋 안 함) |
| `report/export_web.py` | 회차별 상세 → `web/.private/data/*.json` |
| `web/` | SvelteKit + shadcn-svelte(Toss TDS 토큰) 분석 사이트 |
| `web/scripts/copy-data.mjs` | `.private/data` → `static/data/*.json` + `manifest.json` (사이트가 읽는 데이터) |
| `dataset/nasa/` | 갤러리 시나리오용 NASA 퍼블릭 도메인 사진 목록·받기·푸시 스크립트 (사진은 커밋 안 함) |

## 사이트 갱신

```sh
python3 report/extract.py            # 집계
python3 report/export_web.py         # 상세
cd web
node scripts/copy-data.mjs           # static/data 로 복사
npm run dev                          # 로컬 확인
git add static/data && git commit && git push   # main 에 push 하면 Actions 가 Pages 로 배포
```
