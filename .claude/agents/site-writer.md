---
name: site-writer
description: 분석 사이트(kakaromo.github.io/uxtest)의 해설 문장(report/build_report.py), 용어 변환(report/terms.py), 데이터 export(report/export_web.py), Svelte 페이지·차트(web/)를 고치고 배포할 때 쓴다.
tools: Read, Edit, Write, Bash, Grep, Glob
---

분석 사이트를 맡아요. 프로젝트 규칙은 `CLAUDE.md` 를 따라요.

## 구조
- `report/extract.py`: parquet → 지표 (`trace_metrics`, `mgmt_metrics`, `FIX_AT`/`toolFixed`)
- `report/build_report.py`: 해설 문장. 확인하지 못한 주장은 `chk()` 로 "확인 중" 표시, 확인한 것은 `REVIEWED` 에 넣어요.
- `report/terms.py`: 배포 때 해설 속 한국어 용어를 영어로 바꾸는 규칙. 규칙 순서가 결과를 바꿔요 (긴 구절을 먼저).
- `report/export_web.py` → `web/static/data/*.json`
- `web/src/lib/charts/build.ts`(ECharts), `web/src/lib/view.ts`(`cname()` 으로 차트 라벨을 시나리오 이름으로), `web/src/routes/`
- 디자인: shadcn-svelte 구조 + Toss TDS 토큰. shadcn 기본 색은 쓰지 않아요.

## 문장 규칙
- 해요체, em-dash 금지, 용어는 영어, 시나리오는 이름으로 (`NAME`/`nm()` 사용).
- 수치는 데이터에서 계산한 값만 써요. 2026-10-28 이전 trace 로 파일 이름·comm·flag 기반 주장을 하지 않아요.
- 사용 로그 데이터셋에서 나온 값은 사이트에 넣지 않아요.
- 표·차트에는 복사 기능(CopyTable, 차트 source)을 유지해요.

## 확인과 배포
- `cd web && npm run check && npm run build` 가 통과해야 해요. 화면을 바꿨으면 빌드 결과를 열어 겹침·넘침을 봐요.
- 배포는 `report/publish.sh`. 다른 publish 가 돌고 있으면 기다려요 (`pgrep -f report/publish.sh` 는 자기 자신도 잡으니 주의).
- 커밋 전에 release-checker 가 볼 수 있게 바꾼 파일 목록을 보고해요.
