#!/bin/bash
# 대기(S) 본 측정: 무선 adb 로 (USB 를 빼서 충전 없음). 로그는 runs/standby-<시각>.log
#   S3(5분)·S4(10분)·S1(30분)·S2(30분) × 3회 → S5(3시간) × 1회. 합계 약 7.5시간
#   UX_WIFI=<ip:port> 로 기기 주소를 바꿀 수 있다 (기본 192.168.1.20:5555)
#   UX_IDS="S3 S1" 처럼 일부만 잴 수 있다
set -u
cd "$(dirname "$0")"
DEV=${UX_WIFI:-192.168.1.20:5555}
export UX_DEVICE=$DEV UX_SERIAL=$DEV
LOG=runs/standby-$(date +%Y%m%d-%H%M%S).log
exec > >(tee -a "$LOG") 2>&1

adb -s "$DEV" get-state >/dev/null 2>&1 || { echo "무선 기기 $DEV 가 연결돼 있지 않습니다"; exit 1; }
if adb -s "$DEV" shell dumpsys battery | grep -qE "(AC|USB) powered: true"; then echo "충전 중입니다 — USB 를 빼고 다시 실행하세요"; exit 1; fi

echo "== 대기 측정 시작 $(date) · $DEV"
./run.py --rest 120 ${UX_IDS:-S3 S4 S1 S2 S5} | grep -v '^ *[0-9]*s '
echo "== 끝 $(date)"
