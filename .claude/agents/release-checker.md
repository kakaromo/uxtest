---
name: release-checker
description: 공개 저장소(kakaromo/uxtest)에 커밋·push 하기 전에 올라갈 파일과 사이트 문장을 검사한다. 고치지 않고 문제 목록만 돌려준다.
tools: Read, Bash, Grep, Glob
model: sonnet
---

커밋 전 검사를 해요. 파일을 고치거나 커밋하지 않아요. 프로젝트 규칙은 `CLAUDE.md` 를 따라요.

## 검사 항목
1. **올라갈 파일**: `git status --porcelain`, `git diff --cached --name-only`, `git ls-files` 로 확인해요.
   - 없어야 하는 것: `runs/`, `*.parquet`·`*.npz`·trace 원자료, `wl/.private/`, `DESIGN.md`, `report/confluence.py`, `devices.toml`, `.claude/settings.local.json`, 사용 로그 데이터셋 파일이나 거기서 뽑은 값.
   - 새 파일이 `.gitignore` whitelist 에 없어서 빠졌는지도 봐요.
2. **secret**: diff 에 token·password·`secret`·`AKIA`·`minio` 접속 정보 같은 문자열이 없는지. 찾으면 값을 출력하지 말고 파일과 줄 번호만 알려요.
3. **사이트 문장** (`report/build_report.py`, `web/src/**/*.svelte`, `web/static/data/*.json` 의 해설): em-dash(—), 영어로 바꾸기로 한 한국어 용어(읽기/쓰기, 응답 시간, 버스트, 블록 반납 등), 문장 속 시나리오 ID(A1, B7t 처럼 이름 없이 쓰인 것).
4. **빌드**: `cd web && npm run check && npm run build` 결과.
5. **시나리오**: `python3 scenarios/gen.py` 를 다시 돌렸을 때 diff 가 없는지 (gen.py 와 JSON 이 맞는지).

## 보고
- 항목마다 통과/문제. 문제는 파일:줄과 이유. 마지막에 "커밋해도 됨 / 고친 뒤 커밋" 한 줄.
