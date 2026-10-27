#!/bin/bash
# 배터리 본 측정: 하루 TC(wl/mix.json)에 쓰는 시나리오를 무선 adb 로 (USB 를 빼서 충전 없음) 다시 측정. 로그는 runs/battery-<시각>.log
#   실제 사용자 조건에 맞춘다: USB 전원이면 deviceidle 이 ACTIVE 라 f2fs_discard 가 돌지 않고 배경 동작도 달라진다
#   G1 은 직전에 NASA 세트를 새 파일명으로 다시 넣어 1회차를 cold 로, G4·G5·E1 은 그 뒤 warm
#   UX_EXTRA=0 이면 하루 TC 시나리오만 잰다. 기본은 사이트용 나머지 화면 켜짐 시나리오까지
#   배터리가 20% 아래로 내려가면 멈춘다. UX_WIFI=<ip:port> 로 기기 주소를 바꿀 수 있다 (기본 192.168.1.20:5555)
set -u
cd "$(dirname "$0")"
DEV=${UX_WIFI:-192.168.1.20:5555}
export UX_DEVICE=$DEV UX_SERIAL=$DEV
LOG=runs/battery-$(date +%Y%m%d-%H%M%S).log
exec > >(tee -a "$LOG") 2>&1

adb -s "$DEV" get-state >/dev/null 2>&1 || { echo "무선 기기 $DEV 가 연결돼 있지 않습니다"; exit 1; }
check() {
  local b
  b=$(adb -s "$DEV" shell dumpsys battery)
  if echo "$b" | grep -qE "(AC|USB) powered: true"; then echo "충전 중입니다. USB 를 빼고 다시 실행하세요"; exit 1; fi
  lv=$(echo "$b" | awk '/level:/{print $2; exit}')
  echo "-- 배터리 $lv% $(date +%H:%M:%S)"
  [ "$lv" -ge 20 ] || { echo "배터리 20% 미만, 멈춥니다"; exit 1; }
}
run() { for s in "$@"; do check; ./run.py --rest 60 "$s" | grep -v '^ *[0-9]*s '; done; }

echo "== 배터리 측정 시작 $(date) · $DEV"
run A1 A2 A3 A4 A5 A7 A8 B1 B1i B4 B5 B6 B7 B7r B7t B8 B9 C1 C2 C4a C4b C5 C6 D1 D2 D3 D4 D5 D7 D8 D9 E2 E3 E4 E5 E6 E7 E8 F1 F2 F4 F5 S4

echo "== G1 cold 세트 재푸시 $(date)"
python3 dataset/nasa/push.py --repush | tail -2
sleep 60
run G1
echo "== G4 G5 E1 (warm) $(date)"
run G4 G5 E1
# 하루 TC 밖 화면 켜짐 시나리오 (사이트용). G2·G3 은 1회차 cold 라 각각 앞에서 세트를 새로 넣는다. G6 은 사진을 지워서 맨 끝
[ "${UX_EXTRA:-1}" = 1 ] || { echo "== 끝 $(date)"; exit 0; }
echo "== 추가 시나리오 $(date)"
run A6 B2 B3 C3 C7 D6 B7y
for g in G2 G3; do
  echo "== $g cold 세트 재푸시 $(date)"; python3 dataset/nasa/push.py --repush | tail -2; sleep 60; run $g
done
run G6
echo "== 끝 $(date)"
