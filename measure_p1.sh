#!/bin/bash
# P1 본 측정: 18개 × 3회. 로그는 runs/p1-<시각>.log
#   1) C3 dry-run 으로 동영상 앱 경로 재확인 (실패하면 중단)
#   2) A·B·C·D·E 본 측정
#   3) G1, G2 — 각각 직전에 NASA 세트를 새 파일명으로 다시 넣어 1회차를 cold 로 만든다 (2·3회차는 warm)
set -u
cd "$(dirname "$0")"
LOG=runs/p1-$(date +%Y%m%d-%H%M%S).log
exec > >(tee -a "$LOG") 2>&1

echo "== C3 재확인 $(date)"
./run.py --dry C3 | grep -v '^ *[0-9]*s ' || { echo "C3 dry-run 실패 — 중단"; exit 1; }
grep -q 'coloros.video' "$(ls -t runs/C3/*.json | head -1)" || { echo "C3 가 동영상 앱에 도달하지 못함 — 중단"; exit 1; }

echo "== 본 측정 A~E $(date)"
./run.py --rest 60 A1 A2 A3 B1 B2 B3 C1 C2 C3 D1 D2 D3 E2 E3 E4 | grep -v '^ *[0-9]*s '

for g in G1 G2; do
  echo "== $g cold 세트 재푸시 $(date)"
  python3 dataset/nasa/push.py --repush | tail -2
  sleep 60
  ./run.py $g | grep -v '^ *[0-9]*s '
done
echo "== 끝 $(date)"
