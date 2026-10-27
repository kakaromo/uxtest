#!/bin/bash
# 측정 결과 → 사이트 데이터 → 커밋·push (Pages 가 web/** push 로 배포)
#   extract.py → build_report.py → export_web.py → copy-data.mjs. 데이터가 안 바뀌었으면 커밋하지 않는다
#   PUBLISH_NO_PUSH=1 이면 커밋까지만
set -eu
cd "$(dirname "$0")/.."
python3 report/extract.py > /dev/null
python3 report/build_report.py > /dev/null
python3 report/export_web.py > /dev/null
node web/scripts/copy-data.mjs > /dev/null
git add web/static/data
if git diff --cached --quiet; then echo "변경 없음"; exit 0; fi
n=$(python3 -c "import json;d=json.load(open('report/data.json'));print(len({s['id'] for s in d['scenarios'] if s.get('toolFixed')}), len({s['id'] for s in d['scenarios']}))")
git commit -q -m "사이트 데이터 갱신: 고친 수집 도구로 다시 잰 시나리오 ${n% *}/${n#* }개

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
[ "${PUBLISH_NO_PUSH:-0}" = 1 ] || git push -q origin HEAD
git log --oneline -1
