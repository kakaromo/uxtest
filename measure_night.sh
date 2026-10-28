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
LOG=runs/night-$(date +%Y%m%d-%H%M%S).log
exec > >(tee -a "$LOG") 2>&1

adb -s "$SER" get-state >/dev/null 2>&1 || { echo "기기 $SER 가 연결돼 있지 않습니다"; exit 1; }
if [ -n "${UX_START:-}" ]; then
    now=$(date +%s); at=$(date -j -f "%H:%M" "$UX_START" +%s)
    [ "$at" -le "$now" ] && at=$((at + 86400))
    echo "== $(date -r $at '+%m-%d %H:%M') 까지 대기"
    sleep $((at - now))
fi
if ! adb -s "$SER" shell dumpsys battery | grep -qE "(AC|USB) powered: true"; then echo "충전 중이 아닙니다. 충전기를 꽂고 다시 실행하세요"; exit 1; fi

echo "== 야간 충전 대기 시작 $(date) · $SER"
./run.py S6 | grep -v '^ *[0-9]*s '
echo "== 끝 $(date)"
