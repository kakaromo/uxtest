#!/bin/bash
# PreToolUse(Bash): 측정·TC 가 도는 동안 adb 명령을 막는다 (trace 오염 방지).
#   측정 중 판단: measure_*.sh / run.py / wl/run_tc.py 를 실행 중인 프로세스, 또는 runs/.measuring 파일
#   명령에 UX_ALLOW_ADB=1 이 있으면 통과
cmd=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null) || exit 0
echo "$cmd" | grep -Eq '(^|[^[:alnum:]_./-])adb([[:space:]]|$)' || exit 0
echo "$cmd" | grep -q 'UX_ALLOW_ADB=1' && exit 0
busy=$(ps -axo command= | grep -E '^(/[^ ]*/)?(bash|sh|python3?) ([^ ]*/)?(measure_[a-z_]+\.sh|run\.py|wl/run_tc\.py|run_tc\.py)( |$)' | head -1)
[ -z "$busy" ] && [ -f "$CLAUDE_PROJECT_DIR/runs/.measuring" ] && busy="runs/.measuring"
[ -z "$busy" ] && exit 0
echo "측정이 돌고 있어서 adb 명령을 막았어요 ($busy). 끝난 뒤 다시 하거나, 꼭 필요하면 명령에 UX_ALLOW_ADB=1 을 붙이세요." >&2
exit 2
