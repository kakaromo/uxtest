#!/bin/bash
# 야간 충전 대기(S6) 측정: 충전기를 꽂은 채 화면을 끄고 6시간. 로그는 runs/night-<시각>.log
#   기본은 USB adb (run.py 기본값). USB 데이터 케이블이면 OxygenOS Deep Sleep 이 Wi-Fi 를 꺼도 연결이 남는다.
#   UX_WIFI=<ip:port> 를 주면 무선 adb 로 잰다 (벽 충전기 사용 시. Deep Sleep 시간대에 Wi-Fi 가 꺼지면 끊길 수 있음).
#   UX_START=HH:MM 이면 그 시각까지 기다렸다가 시작한다 (예: UX_START=00:00).
set -u
cd "$(dirname "$0")"
if [ -n "${UX_WIFI:-}" ]; then
    export UX_DEVICE=$UX_WIFI UX_SERIAL=$UX_WIFI
fi
SER=${UX_SERIAL:-3C1677001HN00000}
export UX_SERIAL=$SER
LOG=runs/night-$(date +%Y%m%d-%H%M%S).log
exec > >(tee -a "$LOG") 2>&1

check() {   # 연결·충전 확인. 시작 전과 대기 뒤에 두 번 본다 (밤에 실패하면 아무도 못 보므로 미리 거른다)
    adb -s "$SER" get-state >/dev/null 2>&1 || { echo "기기 $SER 가 연결돼 있지 않습니다"; exit 1; }
    adb -s "$SER" shell dumpsys battery | grep -qE "(AC|USB) powered: true" || { echo "충전 중이 아닙니다. 충전기를 꽂고 다시 실행하세요"; exit 1; }
    # USB 는 agent 기기 ID 가 포트 경로(usb:2-1.1.3 같은)라 hub·포트를 바꾸면 달라진다. 지금 경로를 쓴다
    if [ -z "${UX_WIFI:-}" ]; then
        local u; u=$(adb devices -l | awk -v s="$SER" '$1==s { for (i=1;i<=NF;i++) if ($i ~ /^usb:/) print substr($i,5) }')
        [ -n "$u" ] || { echo "USB 경로를 못 찾았습니다 ($SER)"; exit 1; }
        export UX_DEVICE=$u
    fi
}
check
if [ -n "${UX_START:-}" ]; then
    now=$(date +%s); at=$(date -j -f "%H:%M:%S" "$UX_START:00" +%s)
    [ "$at" -le "$now" ] && at=$((at + 86400))
    echo "== $(date -r $at '+%m-%d %H:%M') 까지 대기"
    sleep $((at - now))
    check
fi

echo "== 야간 충전 대기 시작 $(date) · $SER"
caffeinate -i ./run.py S6 | grep -v '^ *[0-9]*s '
echo "== 끝 $(date)"
