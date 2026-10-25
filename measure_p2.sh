#!/bin/bash
# P2 본 측정: 34개 × 3회. 로그는 runs/p2-<시각>.log
#   1) 갤러리 외 시나리오 (A·B·C·D·E·F)
#   2) G3 — 직전에 NASA 세트를 새 파일명으로 다시 넣어 1회차를 cold 로 (2·3회차 warm)
#   3) G4·G5·E1 — warm (G3 가 만든 썸네일 그대로)
#   4) G6 — 회차마다 20장을 지우므로 마지막에, 끝나면 빠진 사진만 다시 넣는다
set -u
cd "$(dirname "$0")"
LOG=runs/p2-$(date +%Y%m%d-%H%M%S).log
exec > >(tee -a "$LOG") 2>&1

echo "== 본 측정 A~F $(date)"
./run.py --rest 60 A4 A5 A6 A7 A8 B1i B4 B5 B6 B8 B9 C4a C4b C5 C6 C7 D4 D5 D6 D7 D8 D9 E5 E6 E7 E8 F1 F2 F4 F5 \
  | grep -v '^ *[0-9]*s '

echo "== G3 cold 세트 재푸시 $(date)"
python3 dataset/nasa/push.py --repush | tail -2
sleep 60
./run.py G3 | grep -v '^ *[0-9]*s '

echo "== G4 G5 E1 (warm) $(date)"
./run.py --rest 60 G4 G5 E1 | grep -v '^ *[0-9]*s '

echo "== G6 $(date)"
./run.py G6 | grep -v '^ *[0-9]*s '
python3 dataset/nasa/push.py | tail -2   # G6 가 지운 60장만 다시 넣는다
echo "== 끝 $(date)"
