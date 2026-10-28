#!/bin/bash
# UX 워크로드 측정 전 기기 준비. 여러 번 실행해도 된다 (이미 된 단계는 건너뛴다).
#
#   scenarios/setup.sh              # 준비 + 점검
#   scenarios/setup.sh --restore    # 측정 후 되돌리기 (화면 항상 켜짐 해제)
#   UX_SERIAL=<serial> scenarios/setup.sh   # 다른 기기
#   scenarios/setup.sh --wifi       # USB 로 연결한 기기를 무선 adb 로 (persist.adb.tcp.port) + 배터리 측정용 설정
#   scenarios/setup.sh --usb        # 무선 adb 끄기
#
# 하는 일
#   1. adb root 확인, USB 연결 중 화면 항상 켜짐(svc power stayon usb), 잠금 해제
#   2. Perfetto 설정(perfetto_jank.cfg)을 기기에 두고 2초 시험 수집
#   3. C3 용 2분 촬영 영상 → /sdcard/Movies/uxtest_fixture.mp4 (없을 때만)
#   4. 처음 실행 화면 점검 (Chrome, 갤러리) — 남아 있으면 알려만 준다
set -u

S="${UX_SERIAL:-3C1677001HN00000}"
HERE="$(cd "$(dirname "$0")" && pwd)"
FIXTURE=/storage/emulated/0/Movies/uxtest_fixture.mp4
SHUTTER="635 2420"
A() { adb -s "$S" shell "$@"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; WARN=$((WARN + 1)); }
die() { printf '  \033[31m✗\033[0m %s\n' "$*"; exit 1; }
WARN=0

# 배터리 측정용 설정: "<namespace> <key> <value>" 한 줄에 하나. 원래 값은 처음 한 번만 저장하고 --restore 로 되돌린다.
# 목적: 측정 중 무선 adb 가 끊기지 않게 하는 것만 바꾼다(실사용 조건에서 멀어지지 않게).
#   예) OxygenOS 배터리 앱의 수면 대기 최적화(Deep Sleep)는 학습한 수면 시간대에 Wi-Fi 를 꺼서 밤 측정이 끊겼다.
BATTERY_SETTINGS=(
)
battery_setup() {
  echo "== 배터리 설정"
  if [ ${#BATTERY_SETTINGS[@]} -eq 0 ]; then
    warn "바꿀 배터리 설정 key 가 아직 없습니다 (GUIDE.md 4.1 의 수동 설정을 확인하세요)"
    return
  fi
  local ns key val cur
  for line in "${BATTERY_SETTINGS[@]}"; do
    read -r ns key val <<< "$line"
    cur=$(A "settings get $ns $key" | tr -d '\r')
    A "grep -q '^$ns $key ' /data/local/tmp/ux_battery_orig 2>/dev/null || echo '$ns $key $cur' >> /data/local/tmp/ux_battery_orig"
    A "settings put $ns $key $val"
    ok "$ns $key: $cur → $val"
  done
}

# 무선 adb 로 바꾸기. 본 측정은 USB 를 빼고 배터리로 한다 (USB 전원이면 deviceidle 이 ACTIVE 라
# f2fs Discard·배경 동작이 실제 사용과 달라진다). USB 로 연결된 상태에서 실행한다.
#   UX_SERIAL=<USB serial> scenarios/setup.sh --wifi      # 무선 전환 + 배터리 측정용 설정
#   UX_SERIAL=<USB serial> scenarios/setup.sh --usb       # 되돌리기 (TCP adb 끄기)
PORT="${UX_ADB_PORT:-5555}"
if [ "${1:-}" = "--wifi" ]; then
  echo "== 무선 adb ($S → :$PORT)"
  adb -s "$S" get-state >/dev/null 2>&1 || die "USB 로 연결된 기기가 없습니다"
  if [ "$(A id -u | tr -d '\r')" != "0" ]; then
    adb -s "$S" root >/dev/null 2>&1; sleep 3; adb -s "$S" wait-for-device
  fi
  [ "$(A id -u | tr -d '\r')" = "0" ] || die "adb root 가 안 됩니다 (userdebug/eng 빌드 또는 root 기기가 필요)"
  IP=$(A "ip -f inet addr show wlan0" | awk '/inet /{print $2}' | cut -d/ -f1 | tr -d '\r')
  [ -n "$IP" ] || die "기기가 Wi-Fi 에 연결돼 있지 않습니다"
  # persist.adb.tcp.port: adbd 가 시작할 때마다 이 포트로도 listen 한다 → USB 를 뽑거나 재부팅해도 무선 연결이 남는다
  A "setprop persist.adb.tcp.port $PORT"
  ok "persist.adb.tcp.port=$(A getprop persist.adb.tcp.port | tr -d '\r')"
  adb -s "$S" tcpip "$PORT" >/dev/null; sleep 3
  adb connect "$IP:$PORT" >/dev/null; sleep 2
  W="$IP:$PORT"
  adb -s "$W" get-state >/dev/null 2>&1 || die "$W 에 연결하지 못했습니다 (같은 망인지, 방화벽을 확인하세요)"
  if [ "$(adb -s "$W" shell id -u | tr -d '\r')" != "0" ]; then
    adb -s "$W" root >/dev/null 2>&1; sleep 3; adb connect "$W" >/dev/null; sleep 2
  fi
  [ "$(adb -s "$W" shell id -u | tr -d '\r')" = "0" ] && ok "무선 연결 $W (root)" || die "$W 가 root 가 아닙니다"
  S="$W"
  battery_setup
  echo
  echo "이제 USB 를 뽑고 아래를 실행한 뒤 측정하세요:"
  echo "  export UX_SERIAL=$W UX_DEVICE=$W UX_WIFI=$W"
  exit 0
fi
if [ "${1:-}" = "--usb" ]; then
  A "setprop persist.adb.tcp.port ''" && ok "persist.adb.tcp.port 지움"
  adb -s "$S" usb >/dev/null 2>&1 && ok "adbd 를 USB 모드로 (다시 USB 로 연결하세요)"
  exit 0
fi

if [ "${1:-}" = "--restore" ]; then
  A svc power stayon false && ok "화면 항상 켜짐 해제"
  if A '[ -f /data/local/tmp/ux_rotation_orig ]'; then
    A 'read ar ur < /data/local/tmp/ux_rotation_orig; settings put system accelerometer_rotation $ar; settings put system user_rotation $ur; rm /data/local/tmp/ux_rotation_orig'
    ok "화면 회전 설정 복원"
  fi
  if A '[ -f /data/local/tmp/ux_battery_orig ]'; then
    A 'while read ns key val; do if [ "$val" = "null" ]; then settings delete $ns $key; else settings put $ns $key "$val"; fi; done < /data/local/tmp/ux_battery_orig; rm /data/local/tmp/ux_battery_orig'
    ok "배터리 설정 복원"
  fi
  if A '[ -f /data/local/tmp/ux_ime_orig ]'; then
    A 'settings put secure selected_input_method_subtype $(cat /data/local/tmp/ux_ime_orig); ime set com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME >/dev/null; rm /data/local/tmp/ux_ime_orig'
    ok "키보드 하위 유형 복원"
  fi
  exit 0
fi

echo "== 기기 $S"
adb -s "$S" get-state >/dev/null 2>&1 || die "기기가 연결돼 있지 않습니다"
[ "$(A id -u | tr -d '\r')" = "0" ] || die "adb 가 root 가 아닙니다 (fsio·drop_caches 에 필요). adb root 후 다시 실행하세요"
ok "adb root"

A svc power stayon usb
A 'input keyevent KEYCODE_WAKEUP; sleep 1; wm dismiss-keyguard; sleep 1'
if A dumpsys window | grep -q "isKeyguardShowing=true"; then
  A input swipe 636 2400 636 900 200; sleep 1
fi
A dumpsys window | grep -q "isKeyguardShowing=true" && warn "잠금이 풀리지 않았습니다 — 직접 풀어 주세요" || ok "화면 켜짐 유지(USB) · 잠금 해제"

# 좌표 스텝이 세로 1272×2772 기준이라 회전되면 엉뚱한 곳을 누른다 (실제로 녹화 종료 탭이 빗나갔다).
# 원래 값은 처음 한 번만 저장해 --restore 로 되돌린다.
A '[ -f /data/local/tmp/ux_rotation_orig ] || echo "$(settings get system accelerometer_rotation) $(settings get system user_rotation)" > /data/local/tmp/ux_rotation_orig;
   settings put system accelerometer_rotation 0; settings put system user_rotation 0'
ok "화면 세로 고정 (원래 값: $(A cat /data/local/tmp/ux_rotation_orig | tr -d '\r'))"

# text 스텝은 키보드가 한국어 모드면 영문이 자모로 바뀐다 → 원래 하위 유형을 저장해 두고 Alphabet 으로 (시나리오도 매번 다시 맞춘다)
A '[ -f /data/local/tmp/ux_ime_orig ] || settings get secure selected_input_method_subtype > /data/local/tmp/ux_ime_orig;
   settings put secure selected_input_method_subtype -1097284911; ime set com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME >/dev/null'
ok "키보드 Alphabet (원래 값: $(A cat /data/local/tmp/ux_ime_orig | tr -d '\r'))"

echo "== Perfetto"
adb -s "$S" push "$HERE/perfetto_jank.cfg" /data/local/tmp/ux_perfetto.cfg >/dev/null || die "Perfetto 설정 push 실패"
adb -s "$S" push "$HERE/perfetto_jank_light.cfg" /data/local/tmp/ux_perfetto_light.cfg >/dev/null || die "Perfetto 경량 설정 push 실패"
A 'mkdir -p /dev/ux; rm -f /dev/ux/setup_probe.pftrace;
   cat /data/local/tmp/ux_perfetto.cfg | perfetto --txt -c - --background -o /dev/ux/setup_probe.pftrace >/dev/null 2>&1;
   sleep 2; kill -TERM $(pidof perfetto) 2>/dev/null; sleep 2'
SZ=$(A 'stat -c %s /dev/ux/setup_probe.pftrace 2>/dev/null' | tr -d '\r')
if [ -n "$SZ" ] && [ "$SZ" -gt 0 ]; then
  ok "시험 수집 ${SZ} bytes"
  A rm -f /dev/ux/setup_probe.pftrace
else
  warn "Perfetto 시험 수집 실패 — G 시나리오는 gfxinfo 만 남습니다"
fi

echo "== C3 로컬 영상"
if A "[ -s $FIXTURE ]"; then
  ok "이미 있음: $FIXTURE"
else
  echo "  2분 촬영 중… (카메라 앞을 가리지 마세요)"
  A 'touch /data/local/tmp/ux_fixture_mark; am start -W -a android.media.action.VIDEO_CAMERA >/dev/null; sleep 4'
  A "input tap $SHUTTER; sleep 120; input tap $SHUTTER; sleep 6"
  VID=$(A 'find /storage/emulated/0/DCIM/Camera -name "VID*.mp4" -newer /data/local/tmp/ux_fixture_mark | head -1' | tr -d '\r')
  [ -n "$VID" ] || die "촬영한 영상을 찾지 못했습니다"
  # /sdcard 는 FUSE 라 MediaProvider 가 이동을 따라가지만, 확실히 하려고 다시 스캔한다
  A "mkdir -p /storage/emulated/0/Movies && mv '$VID' $FIXTURE"
  A "content delete --uri content://media/external/file --where \"_data='$VID'\"" >/dev/null 2>&1
  A "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://$FIXTURE" >/dev/null
  A 'am force-stop com.oplus.camera; input keyevent HOME'
  sleep 3
  ok "촬영 완료: $(A "ls -l $FIXTURE" | awk '{print $5}') bytes"
fi
ROW=$(A "content query --uri content://media/external/video/media --projection _id --where \"_data='$FIXTURE'\"" | tr -d '\r')
echo "$ROW" | grep -q "_id=" && ok "MediaProvider 등록 확인" || warn "MediaProvider 에 영상이 없습니다 — C3 가 영상을 못 엽니다"

echo "== 처음 실행 화면"
check_first_run() {  # pkg 이름 찾을문구
  A "monkey -p $1 -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; sleep 4"
  local dump focus
  dump=$(adb -s "$S" exec-out uiautomator dump /dev/tty 2>/dev/null)
  focus=$(A dumpsys window | grep mCurrentFocus)
  A "am force-stop $1; input keyevent HOME"
  if echo "$focus" | grep -q -i "firstrun" || echo "$dump" | grep -q "$3"; then
    warn "$2 처음 실행 화면이 남아 있습니다 — 기기에서 직접 넘겨 주세요"
  else
    ok "$2"
  fi
}
check_first_run com.android.chrome "Chrome" "signin_fre"
check_first_run com.oneplus.gallery "갤러리" "동의하고 계속하기"
check_first_run com.coloros.video "동영상 앱(C3)" "동의하고 계속하기"

echo
[ $WARN -eq 0 ] && echo "준비 완료." || echo "확인할 항목 ${WARN}개 (위 ! 표시)."
