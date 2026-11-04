#!/bin/bash
# 시나리오를 돌리면서 앱 DB 의 테이블별 INSERT·UPDATE·DELETE 와 WAL commit 을 잰다 (측정 trace 와 따로)
#   wl/run_dbwatch.sh B7t 150 ttm=/data/data/.../ttm_strategy.db ...
# 결과는 wl/.private/dbinfo/watch-<시나리오>.json. 행 내용은 나오지 않고, /dev 의 임시 복사본은 끝나면 지운다
set -u
sid=$1; sec=$2; shift 2
cd "$(dirname "$0")/.."
S=${UX_SERIAL:-192.168.1.20:5555}; D=/data/local/tmp/uxwl
adb -s "$S" push -q wl/.private/uxwl $D/ && adb -s "$S" shell "chmod 755 $D/uxwl; mkdir -p /dev/uxdb"
adb -s "$S" shell "$D/uxwl dbwatch --sec $sec --tc /dev/uxdb/out.json $*" &
w=$!
sleep 8
UX_SERIAL=$S UX_DEVICE=$S python3 run.py --dry "$sid" | tail -6 | cut -c1-160
wait $w
adb -s "$S" pull -q /dev/uxdb/out.json "wl/.private/dbinfo/watch-$sid.json"
adb -s "$S" shell "rm -rf /dev/uxdb; ls /dev/uxdb 2>&1 | head -1"
