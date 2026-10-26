"""UX 워크로드 시나리오 정의 → agent 이식 포맷 JSON.

  python3 scenarios/gen.py          # scenarios/<유형>/*.scenario.json + pack.scenariopack.json 생성, 스키마 검증

규칙
- 측정 3회는 repeatCount=3 (회차마다 trace 잡이 따로 생긴다). linear 시나리오는 loop 중첩이 안 되므로
  loop 는 trace 구간 안의 동작 반복에만 쓴다. shell 스텝은 시간 제한이 없다 (agent 의 ShellUntilDone).
- trace 는 fsio_ufs, VFS·DRAM 없음 (CPH2749 는 DRAM 대역폭 미지원).
- 화면 확인(mCurrentFocus)은 trace 를 멈춘 뒤에 남겨 측정을 오염시키지 않는다.
- 좌표는 CPH2749 1272×2772 기준.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
SCHEMA = HERE.parent.parent / "agent" / "docs" / "schemas" / "scenario.schema.json"
W, H = 1272, 2772
DEVICE = "CPH2749"

CHROME, YT, SETTINGS = "com.android.chrome", "com.google.android.youtube", "com.android.settings"
GALLERY, CAMERA, MAPS, INSTA = "com.oneplus.gallery", "com.oplus.camera", "com.google.android.apps.maps", "com.instagram.android"
SHUTTER = (635, 2420)
WIKI1 = "https://en.m.wikipedia.org/wiki/Solid-state_drive"
WIKI2 = "https://en.m.wikipedia.org/wiki/Flash_memory"
FIXTURE_VIDEO = "/storage/emulated/0/Movies/uxtest_fixture.mp4"
PERFETTO_CFG = "/data/local/tmp/ux_perfetto.cfg"
# Perfetto·gfxinfo 결과는 tmpfs(/dev)에 둔다 — UFS 에 쓰면 그 write 가 다음 측정을 오염시킨다.
# run.py 가 잡이 끝날 때마다 PC 로 가져오고 지운다.
DEV_OUT = "/dev/ux"
PERFETTO_CFG_LIGHT = "/data/local/tmp/ux_perfetto_light.cfg"  # G2(≈12분) 용: FrameTimeline + I/O 대기 사유만
MARK = "/data/local/tmp/ux_mark"


# ---------------- 스텝 ----------------
def step(type_, label=None, **params):
    p = {k: str(v) for k, v in params.items()}
    if label:
        p["label"] = label
    return {"type": type_, "params": p}


def trace_start(label="측정 시작"):
    return step("trace_start", label, trace_type="fsio_ufs", window_seconds=1, include_vfs="false", include_dram="false")


def trace_stop():
    return step("trace_stop", "측정 종료", trace_type="fsio_ufs")


def sh(cmd, label):
    return step("shell", label, cmd=cmd)


def sleep(sec, label=None):
    return step("sleep", label or f"대기 {sec}초", seconds=sec)


def launch(pkg, label, clear="force_stop", wait=5):
    return step("launch_app", label, package_name=pkg, clear_mode=clear, wait_seconds=wait)


def stop(pkg, label=None):
    return step("stop_app", label or "앱 종료", package_name=pkg)


def scroll(count, label, pause=1.5, direction="down", duration=300):
    return step("scroll", label, direction=direction, count=count, pause=pause, duration=duration)


def key(code, label):
    return step("key", label, keycode=code)


def tap_el(label, **sel):
    return step("tap_element", label, **sel)


def text(s, label, submit="true"):
    return step("text", label, input_text=s, submit=submit)


def yt(label, **params):
    return step("youtube", label, **params)


FOCUS = sh("dumpsys window | grep mCurrentFocus", "화면 확인")
# text 스텝(adb input text)은 키보드가 한국어 모드면 영문이 한글 자모로 바뀐다 (https:// → ㅗㅅ센://).
# Gboard 의 Alphabet 하위 유형으로 바꿔 둔다. 원래 값은 setup.sh 가 저장하고 --restore 로 되돌린다.
GBOARD = "com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME"
IME_EN = sh(f"settings put secure selected_input_method_subtype -1097284911; ime set {GBOARD} >/dev/null; "
            "settings get secure selected_input_method_subtype", "키보드 영문(Alphabet)으로")
DROP = sh("sync; echo 3 > /proc/sys/vm/drop_caches", "페이지 캐시 비우기")
SETTLE = sleep(3, "writeback 배수 대기")
HOME = key(3, "홈")
MARK_NOW = sh(f"touch {MARK}", "새 파일 기준 시각 기록")
# 측정 중 생긴 카메라 파일만 MediaProvider 를 통해 지운다 (기존 사진은 건드리지 않는다)
CLEAN_CAMERA = sh(
    # 지우기 전에 저장된 장수·용량을 남긴다 (회차별로 촬영이 실제로 됐는지 확인용)
    f"echo CAPTURED files=$(find /storage/emulated/0/DCIM/Camera -type f -newer {MARK} | wc -l) "
    f"kb=$(find /storage/emulated/0/DCIM/Camera -type f -newer {MARK} -exec du -k {{}} + | awk '{{s+=$1}} END {{print s+0}}'); "
    f"for f in $(find /storage/emulated/0/DCIM/Camera -type f -newer {MARK}); do "
    "content delete --uri content://media/external/file --where \"_data='$f'\"; rm -f \"$f\"; done; "
    "find /storage/emulated/0/DCIM/Camera/Cshot -mindepth 1 -type d -empty -delete 2>/dev/null; echo cleaned",
    "촬영 파일 정리")


def open_url(url, label):
    return sh(f"am start -a android.intent.action.VIEW -d {url} -p {CHROME}", label)


def cam_still():
    return sh("am start -W -a android.media.action.STILL_IMAGE_CAMERA", "카메라(사진) 실행")


def tap_shutter(label):
    return sh(f"input tap {SHUTTER[0]} {SHUTTER[1]}", label)


def clear_app_cache(pkg, dirs, label):
    paths = " ".join(f"/data/data/{pkg}/cache/{d}" for d in dirs)
    return sh(f"rm -rf {paths}; echo ok", label)


def perfetto_start(tag, cfg=None):
    # 메모리 버퍼에만 담는다 (파일은 PERFETTO_STOP 때 한 번에 쓴다 → fsio 측정 구간에 traced write 가 안 섞임)
    return sh(f"mkdir -p {DEV_OUT}; cat {cfg or PERFETTO_CFG} | perfetto --txt -c - --background "
              f"-o {DEV_OUT}/ux_{tag}_$(date +%Y%m%d_%H%M%S).pftrace",
              "Perfetto(FrameTimeline) 시작")


PERFETTO_STOP = sh(f"kill -TERM $(pidof perfetto) 2>/dev/null; while pidof perfetto >/dev/null; do sleep 1; done; ls -l {DEV_OUT}/*.pftrace | tail -1",
                   "Perfetto 종료")


def gfx_reset(pkg):
    return sh(f"dumpsys gfxinfo {pkg} reset >/dev/null; echo reset", "프레임 통계 초기화")


def gfx_dump(pkg, tag):
    return sh(f"dumpsys gfxinfo {pkg} framestats > {DEV_OUT}/ux_gfx_{tag}_$(date +%Y%m%d_%H%M%S).txt; "
              f"grep -E 'Total frames|Janky frames|90th|99th' {DEV_OUT}/ux_gfx_{tag}_*.txt | tail -4",
              "프레임 통계 저장")


# ---------------- 시나리오 ----------------
S = []


def scenario(sid, type_, prio, name, desc, steps, packages, loops=(), repeat=3, verify=None, needs=None):
    if any(x["type"] == "text" for x in steps):  # 맨 앞에 키보드 영문 전환을 넣고 loop 구간을 한 칸 민다
        steps = [IME_EN] + steps
        loops = [{**lp, "startStep": lp["startStep"] + 1, "endStep": lp["endStep"] + 1} for lp in loops]
    S.append(dict(id=sid, type=type_, prio=prio, name=name, desc=desc, steps=steps, loops=list(loops),
                  repeat=repeat, packages=packages, verify=verify or [], needs=needs or []))


def loop_over(steps, first, last, count):
    """steps 리스트에서 [first, last] 구간(포함)을 count 회 반복하는 loop 정의."""
    return {"startStep": first, "endStep": last, "count": count}


# A1 ------------------------------------------------------------------
st = [
    stop(CHROME, "Chrome 종료"),
    trace_start(),
    DROP,                                                           # 2  ┐ ×5
    launch(CHROME, "Chrome cold start", wait=5),                    # 3  │
    HOME,                                                           # 4  ┘
    SETTLE, trace_stop(), FOCUS, stop(CHROME),
]
scenario("A1", "A", 1, "Chrome cold start ×5",
         "페이지 캐시를 비우고 Chrome 을 강제 종료 후 실행하는 것을 5번 반복. 저장장치 기준 cold start(APK·odex·so read).",
         st, [CHROME], loops=[loop_over(st, 2, 4, 5)], needs=["Chrome 처음 실행 화면 완료"])

# A2 ------------------------------------------------------------------
apps = [(CHROME, "Chrome"), (YT, "YouTube"), (SETTINGS, "설정"), (GALLERY, "갤러리"), (CAMERA, "카메라"), (MAPS, "지도")]
st = [trace_start()]
for pkg, nm in apps:
    st += [DROP, launch(pkg, f"{nm} cold start", wait=6), HOME]
st += [SETTLE, trace_stop(), FOCUS] + [stop(p, f"{n} 종료") for p, n in apps]
scenario("A2", "A", 1, "cold start 순회 6앱",
         "Chrome→YouTube→설정→갤러리→카메라→지도를 각각 캐시를 비우고 cold start. Behavior 구간 이름으로 앱별 실행 I/O 를 나눠 본다.",
         st, [p for p, _ in apps], needs=["Chrome·갤러리 처음 실행 화면 완료"])

# A3 ------------------------------------------------------------------
st = [
    launch(CHROME, "Chrome 준비", wait=4), open_url(WIKI1, "위키 문서 열기"), sleep(8, "로딩 대기"),
    launch(YT, "YouTube 준비", wait=5), launch(SETTINGS, "설정 준비", wait=3),
    trace_start(),
    launch(CHROME, "Chrome 으로 전환", clear="none", wait=3), scroll(3, "Chrome 스크롤"),        # 6 ┐ ×2
    launch(YT, "YouTube 로 전환", clear="none", wait=3), scroll(3, "YouTube 스크롤"),          #   │
    launch(SETTINGS, "설정으로 전환", clear="none", wait=3), scroll(3, "설정 스크롤"),          # 11┘
    SETTLE, trace_stop(), FOCUS, stop(CHROME), stop(YT), stop(SETTINGS),
]
scenario("A3", "A", 1, "3앱 왕복 전환 ×6",
         "Chrome·YouTube·설정을 띄워 둔 상태(warm)에서 앱을 오가며 짧게 스크롤. 기존 #15 구조. 백그라운드 동기화 영향으로 변동이 크다.",
         st, [CHROME, YT, SETTINGS], loops=[loop_over(st, 6, 11, 2)])

# B1 / B1i -------------------------------------------------------------
CHROME_CACHE = clear_app_cache(CHROME, ["Cache", "image_manager_disk_cache"], "Chrome 디스크 캐시 비우기")
st = [
    stop(CHROME, "Chrome 종료"), CHROME_CACHE,
    trace_start(),
    open_url(WIKI1, "위키 SSD 문서 열기"), sleep(10, "로딩 대기"), scroll(8, "문서 스크롤"),
    open_url(WIKI2, "위키 플래시 메모리 문서 열기"), sleep(10, "로딩 대기"), scroll(8, "문서 스크롤"),
    SETTLE, trace_stop(), FOCUS, stop(CHROME),
]
scenario("B1", "B", 1, "Chrome 위키 로드+스크롤",
         "개인 계정 로그인 상태 그대로(동기화 I/O 가 섞일 수 있음). 회차마다 Chrome 디스크 캐시를 비우고 영문 위키 문서 2개를 열어 8번씩 스크롤 (한글 URL 은 검색어로 처리되므로 ASCII URL).",
         st, [CHROME], needs=["Chrome 처음 실행 화면 완료"])

st = [
    stop(CHROME, "Chrome 종료"), CHROME_CACHE,
    launch(CHROME, "Chrome 실행", wait=4),
    tap_el("메뉴 열기", element_resource_id="com.android.chrome:id/menu_button"),
    tap_el("새 시크릿 탭", element_text="새 시크릿 탭"),
    sleep(2),
    trace_start(),
    tap_el("주소창", element_resource_id="com.android.chrome:id/url_bar"),
    text(WIKI1, "위키 SSD 문서 열기"), sleep(10, "로딩 대기"), scroll(8, "문서 스크롤"),
    tap_el("주소창", element_resource_id="com.android.chrome:id/url_bar"),
    text(WIKI2, "위키 플래시 메모리 문서 열기"), sleep(10, "로딩 대기"), scroll(8, "문서 스크롤"),
    SETTLE, trace_stop(), FOCUS, stop(CHROME, "Chrome 종료 (시크릿 탭 폐기)"),
]
scenario("B1i", "B", 2, "Chrome 위키 (시크릿 모드)",
         "B1 과 같은 동작을 시크릿 탭에서. 시크릿은 HTTP 캐시·쿠키를 메모리에만 두므로 B1 대비 write 가 얼마나 줄어드는지 비교용.",
         st, [CHROME], verify=["메뉴·시크릿 탭·주소창 요소 이름"], needs=["Chrome 처음 실행 화면 완료"])

# B2 / B3 -------------------------------------------------------------
YT_CACHE = clear_app_cache(YT, ["glide_disk_cache", "volleyCache", "image_manager_disk_cache"], "YouTube 이미지 캐시 비우기")
st = [
    stop(YT, "YouTube 종료"), YT_CACHE, launch(YT, "YouTube 실행", wait=6),
    trace_start(),
    tap_el("검색 열기", element_content_desc="검색"), text("nasa 우주", "검색어 입력"), sleep(4, "결과 로딩"),
    scroll(20, "검색 결과 스크롤"),
    SETTLE, trace_stop(), FOCUS, stop(YT),
]
scenario("B2", "B", 1, "YouTube 검색+결과 스크롤",
         "검색 바가 스크롤 시 숨으므로 검색을 먼저 한다. 회차마다 이미지 캐시를 비워 썸네일을 다시 받는다.", st, [YT])

st = [
    stop(YT, "YouTube 종료"), YT_CACHE, launch(YT, "YouTube 실행", wait=6),
    trace_start(), scroll(40, "홈피드 스크롤 40회"), SETTLE, trace_stop(), FOCUS, stop(YT),
]
scenario("B3", "B", 1, "YouTube 홈피드 40회", "홈피드를 1.5초 간격으로 40번 스크롤. 썸네일·미리보기 캐시 write 가 이어진다.", st, [YT])

# C1 / C2 / C3 --------------------------------------------------------
st = [
    launch(YT, "YouTube 실행", wait=6), tap_el("검색 열기", element_content_desc="검색"),
    text("nasa 4k", "검색어 입력"), sleep(4, "결과 로딩"),
    yt("일반 영상 선택", action="select_video"), yt("재생 준비 확인", action="watch", seconds=0),
    trace_start(), yt("본영상 재생 3분", action="watch", seconds=180, ad_timeout=180),
    trace_stop(), FOCUS, stop(YT),
]
scenario("C1", "C", 1, "YouTube 영상 3분",
         "검색 결과의 일반 영상을 3분 재생. Premium 계정이라 광고가 없다. 재생 화질은 자동.", st, [YT])

st = [
    launch(YT, "YouTube 실행", wait=6), tap_el("Shorts 탭", element_content_desc="Shorts"), sleep(4, "첫 Shorts 로딩"),
    trace_start(),
    sh("for i in $(seq 30); do input swipe 636 2000 636 700 200; sleep 3; done; echo 30", "Shorts 30개 넘기기"),
    SETTLE, trace_stop(), FOCUS, stop(YT),
]
scenario("C2", "C", 1, "Shorts 30회 넘기기", "Shorts 를 3초씩 보고 넘기기를 30번.", st, [YT])

st = [
    DROP,
    trace_start(),
    sh("id=$(content query --uri content://media/external/video/media --projection _id "
       f"--where \"_data='{FIXTURE_VIDEO}'\" | sed -n 's/.*_id=\\([0-9]*\\).*/\\1/p' | head -1); "
       "am start -a android.intent.action.VIEW -t video/mp4 -d content://media/external/video/media/$id -p com.coloros.video",
       "로컬 영상 열기"),
    sleep(120, "로컬 영상 재생 2분"),
    trace_stop(), FOCUS, HOME, stop(GALLERY), stop("com.coloros.video"),
]
scenario("C3", "C", 1, "로컬 동영상 2분",
         "setup.sh 가 만든 2분 촬영 영상(Movies/uxtest_fixture.mp4)을 캐시를 비운 뒤 시스템 동영상 앱(com.coloros.video)으로 재생 — 앱을 지정하지 않으면 앱 선택 창에서 멈춘다. 스트리밍(C1)과 비교용.",
         st, ["com.coloros.video"], needs=["setup.sh 의 fixture 영상"])

# D1 / D2 / D3 --------------------------------------------------------
pre = [MARK_NOW, cam_still(), sleep(3, "카메라 준비"), tap_shutter("워밍업 1장"), sleep(4)]
post = [trace_stop(), FOCUS, CLEAN_CAMERA, stop(CAMERA)]
scenario("D1", "D", 1, "사진 10장",
         "워밍업 1장 뒤 2초 간격 10장 (1초 간격은 처리 중 셔터 입력이 빠져 6장만 저장됨, 모션 사진 꺼짐). 촬영한 파일은 측정 후 지운다.",
         pre + [trace_start(), sh(f"for i in $(seq 10); do input tap {SHUTTER[0]} {SHUTTER[1]}; sleep 2; done; echo 10",
                                  "사진 10장 촬영"), sleep(5, "저장 대기")] + post, [CAMERA])
scenario("D2", "D", 1, "버스트샷 3초",
         "셔터를 3초 길게 눌러 연속 촬영 (실측 3초 ≈ 20장, Cshot 폴더). 측정 후 지운다.",
         pre + [trace_start(), sh(f"input swipe {SHUTTER[0]} {SHUTTER[1]} {SHUTTER[0]} {SHUTTER[1]} 3000", "셔터 3초 누르기"),
                sleep(8, "저장 대기")] + post, [CAMERA])
scenario("D3", "D", 1, "동영상 30초 1080p",
         "동영상 모드는 VIDEO_CAMERA 인텐트로 바로 연다(모드 전환 UI 를 거치지 않음). 기기 기본값 1920×1080 (fixture 실측, 약 2MB/s). 측정 후 지운다.",
         [MARK_NOW, sh("am start -W -a android.media.action.VIDEO_CAMERA", "카메라(동영상) 실행"), sleep(3, "카메라 준비"),
          trace_start(), tap_shutter("녹화 시작"), sleep(30, "녹화 30초"), tap_shutter("녹화 종료"), sleep(5, "저장 대기")] + post,
         [CAMERA])

# E2 / E3 / E4 --------------------------------------------------------
st = [
    sh("dd if=/dev/urandom of=/sdcard/ux_src.bin bs=1M count=512 2>&1 | tail -1; sync", "원본 512MB 만들기"),
    DROP,
    trace_start(), sh("cp /sdcard/ux_src.bin /sdcard/ux_dst.bin && sync && ls -l /sdcard/ux_dst.bin", "512MB 복사"),
    SETTLE, trace_stop(), sh("rm -f /sdcard/ux_src.bin /sdcard/ux_dst.bin; echo removed", "파일 정리"),
]
scenario("E2", "E", 1, "512MB 파일 복사", "/sdcard(FUSE 경유)에서 512MB 파일 복사. 원본 생성과 캐시 비우기는 측정 밖.", st, [])

st = [
    sh(f"rm -rf /data/local/tmp/ux_apk; mkdir -p /data/local/tmp/ux_apk; "
       f"for p in $(pm path {INSTA} | sed 's/package://'); do cp $p /data/local/tmp/ux_apk/; done; sync; ls /data/local/tmp/ux_apk",
       "설치 파일 복사"),
    DROP,
    trace_start(),
    sh("s=$(pm install-create -r | sed 's/.*\\[\\([0-9]*\\)\\].*/\\1/'); i=0; "
       "for f in /data/local/tmp/ux_apk/*.apk; do pm install-write $s $i $f >/dev/null; i=$((i+1)); done; pm install-commit $s",
       "Instagram 재설치"),
    sleep(15, "설치 후 dexopt 대기"),
    trace_stop(), sh("rm -rf /data/local/tmp/ux_apk; echo removed", "설치 파일 정리"),
]
scenario("E3", "E", 1, "앱 재설치 (pm install)",
         "설치된 Instagram 의 APK(분할 포함)를 그대로 다시 설치(-r, 데이터 유지). 버전이 같아 앱 상태는 바뀌지 않는다.",
         st, [INSTA])

st = [
    launch(YT, "캐시 채우기: YouTube", wait=5), scroll(15, "캐시 채우기: 피드 스크롤", pause=1),
    launch(CHROME, "캐시 채우기: Chrome", wait=4), open_url(WIKI1, "캐시 채우기: 위키"), sleep(10),
    HOME, stop(YT), stop(CHROME), sh("sync", "sync"),
    trace_start(), sh("pm trim-caches 999G; echo trimmed", "캐시 정리 (trim-caches)"), sleep(5, "discard 대기"),
    trace_stop(),
]
scenario("E4", "E", 1, "캐시 정리 trim-caches",
         "회차마다 YouTube·Chrome 캐시를 채운 뒤 전체 앱 캐시를 비운다. 파일 삭제의 메타데이터·discard 성격을 본다.",
         st, [YT, CHROME])

# G1 / G2 -------------------------------------------------------------
G_NEEDS = ["NASA 1000장 푸시 (dataset/nasa/push.py)", "갤러리 처음 실행 화면 완료", "1회차 cold 는 push.py --repush 직후"]
st = [
    DROP,  # push 직후엔 원본이 페이지 캐시에 남아 있어 read 가 안 잡힌다 (dry-run 에서 확인)
    launch(GALLERY, "갤러리 실행", wait=5),
    gfx_reset(GALLERY), perfetto_start("G1"),
    trace_start(), scroll(70, "그리드 처음→끝", pause=0.5), SETTLE, trace_stop(),
    PERFETTO_STOP, gfx_dump(GALLERY, "G1"), FOCUS, stop(GALLERY),
]
scenario("G1", "G", 1, "그리드 처음→끝",
         "NASA 1000장 그리드를 끝까지 스크롤 (4열 기준 약 250줄). 1회차 = cold(썸네일 미생성), 2·3회차 = warm. Perfetto FrameTimeline 과 gfxinfo 를 함께 남긴다.",
         st, [GALLERY], verify=["끝까지 닿는 스크롤 횟수", "Perfetto 와 fsiotrace 동시 수집"], needs=G_NEEDS)

st = [
    DROP,
    launch(GALLERY, "갤러리 실행", wait=5),
    step("tap", "첫 사진 열기", x=160, y=600), sleep(2, "뷰어 로딩"),
    gfx_reset(GALLERY), perfetto_start("G2", PERFETTO_CFG_LIGHT),
    trace_start(),
    sh("for i in $(seq 999); do input swipe 1100 1386 170 1386 150; sleep 0.5; done; echo 999", "다음 사진 999장"),
    SETTLE, trace_stop(),
    PERFETTO_STOP, gfx_dump(GALLERY, "G2"), FOCUS, stop(GALLERY),
]
scenario("G2", "G", 1, "뷰어 1→1000장",
         "뷰어에서 0.5초 간격으로 다음 사진 넘기기 999번. 원본 디코딩 read 와 jank 를 같이 본다.",
         st, [GALLERY], verify=["첫 사진 좌표", "넘김 방향"], needs=G_NEEDS)


# ================= P2 =================
# 좌표·요소는 2026-10-25 uiautomator dump 로 확인한 것. "dry-run 확인" 이 붙은 것은 아직 실기 확인 전.
# 제외: Netflix(사용 안 함), Facebook 피드(로그아웃 상태 — 로그인은 하지 않는다. Instagram 은 사용자가 로그인해 B7 로 잰다),
#       F3 메시지(계정 연결 화면이 떠서 계정에 흔적이 남는다). A6 은 Chrome 대신 날씨 앱 — Chrome 을 pm clear 하면 로그인·탭이 사라진다.
FB, WEATHER, GMAIL, PLAY = "com.facebook.katana", "net.oneplus.weather", "com.google.android.gm", "com.android.vending"
YTM, VIDEO, FILEMGR = "com.google.android.apps.youtube.music", "com.coloros.video", "com.oneplus.filemanager"
NOTE, RECORDER, CONTACTS, CALENDAR = "com.oneplus.note", "com.oneplus.soundrecorder", "com.google.android.contacts", "com.google.android.calendar"
NASA_DIR = "/storage/emulated/0/Pictures/NASA"
# 지도는 위치 권한이 정해지지 않아 실행할 때마다 권한 창이 뜬다. 사용자 결정을 대신하지 않도록 뒤로 키로 닫기만 한다 (선택 없음)
CLOSE_PERM = sh("sleep 1; dumpsys window | grep mCurrentFocus | grep -q GrantPermissionsActivity && { input keyevent 4; echo perm-closed; } || echo no-perm",
                "권한 창 있으면 닫기 (선택 안 함)")


def dtap(x, y, label, n=2):
    # input 한 번이 ~150ms 라 순서대로 부르면 double-tap 간격(300ms)을 넘는다 → 백그라운드로 겹쳐 보낸다 (갤러리에서 확인)
    taps = " & sleep 0.12; ".join([f"input tap {x} {y}"] * n)
    return sh(f"{taps}; wait", label)


def rm_media(path_glob, label):
    """/sdcard 파일을 MediaProvider 행과 함께 지운다."""
    return sh(f"for f in {path_glob}; do [ -e \"$f\" ] || continue; "
              "content delete --uri content://media/external/file --where \"_data='$f'\"; rm -rf \"$f\"; done; echo removed", label)


# A4 ------------------------------------------------------------------
heavy = [(MAPS, "지도"), (FB, "Facebook(로그아웃 화면)"), (INSTA, "Instagram(약관 화면)")]
st = [trace_start()]
for pkg, nm in heavy:
    st += [DROP, launch(pkg, f"{nm} cold start", wait=8), HOME]
st += [SETTLE, trace_stop(), FOCUS] + [stop(p) for p, _ in heavy]
scenario("A4", "A", 2, "무거운 앱 cold start",
         "지도·Facebook·Instagram 을 캐시를 비우고 실행만 한다 (Netflix 제외). Facebook·Instagram 은 로그아웃 상태라 첫 화면까지의 실행 read 만 본다.",
         st, [p for p, _ in heavy])

# A5 ------------------------------------------------------------------
recent = [(CHROME, "Chrome"), (YT, "YouTube"), (SETTINGS, "설정"), (GALLERY, "갤러리"), (MAPS, "지도"), (CALENDAR, "캘린더")]
st = [launch(p, f"{n} 띄우기", wait=4) for p, n in recent[:5]] + [CLOSE_PERM, launch(CALENDAR, "캘린더 띄우기", wait=4)] + [
    trace_start(),
    key(187, "최근 앱 화면"), sleep(1),                                                   # 7 ┐ ×6
    sh("input swipe 300 1400 1000 1400 200", "이전 앱 카드로"),                            # 9 │
    step("tap", "가운데 카드 열기", x=636, y=1400), sleep(2, "앱 표시 대기"),                   # 11┘
    SETTLE, trace_stop(), FOCUS] + [stop(p) for p, _ in recent]
scenario("A5", "A", 2, "최근 앱 화면 전환 ×6",
         "6개 앱을 띄워 둔 뒤 최근 앱 화면(KEYCODE_APP_SWITCH)에서 이전 앱 카드를 골라 여는 것을 6번. 메모리에 남은 앱으로의 전환이라 read 가 짧은 burst 로만 나와야 한다.",
         st, [p for p, _ in recent], loops=[loop_over(st, 8, 12, 6)], verify=["최근 앱 카드 스와이프 방향·좌표"])

# A6 ------------------------------------------------------------------
st = [stop(WEATHER), sh(f"pm clear {WEATHER}", "날씨 앱 데이터 초기화"), DROP,
      trace_start(), launch(WEATHER, "초기화 후 첫 실행", clear="none", wait=15), SETTLE, trace_stop(),
      FOCUS, stop(WEATHER)]
scenario("A6", "A", 2, "데이터 초기화 후 첫 실행 (날씨)",
         "pm clear 직후 첫 실행 — 앱 데이터(DB·설정·캐시) 초기 생성 write. A1(같은 앱 재실행)과 비교용. "
         "Chrome 은 초기화하면 로그인·탭이 사라져 계정 앱이 아닌 날씨 앱으로 바꿨다. 첫 실행 동의 화면이 나오면 그 화면까지가 측정 범위다.",
         st, [WEATHER], verify=["첫 실행 화면에서 멈추는지"])

# A7 ------------------------------------------------------------------
st = [launch(YT, "YouTube 실행", wait=6), HOME, sleep(2),
      trace_start(),
      launch(YT, "YouTube 로 복귀", clear="none", wait=3), HOME, sleep(2, "홈 대기"),  # 4 ┐ ×10 ┘ 6
      SETTLE, trace_stop(), FOCUS, stop(YT)]
scenario("A7", "A", 2, "홈↔YouTube 복귀 ×10",
         "YouTube 를 띄워 둔 채 홈과 앱을 10번 오간다. 백그라운드 진입 때 상태 저장 write 를 본다.",
         st, [YT], loops=[loop_over(st, 4, 6, 10)])

# A8 ------------------------------------------------------------------
st = [launch(YT, "YouTube 실행", wait=6), scroll(5, "피드 스크롤"), HOME,
      launch(CHROME, "다른 앱: Chrome", wait=4), launch(MAPS, "다른 앱: 지도", wait=6), launch(CAMERA, "다른 앱: 카메라", wait=4), HOME,
      sleep(300, "백그라운드 5분"),
      sh(f"pidof {YT} >/dev/null && echo YT_ALIVE || echo YT_KILLED", "YouTube 프로세스 생존 여부"),
      trace_start(), launch(YT, "5분 뒤 YouTube 복귀", clear="none", wait=5), scroll(3, "피드 스크롤"),
      SETTLE, trace_stop(), FOCUS, stop(YT), stop(CHROME), stop(MAPS), stop(CAMERA)]
scenario("A8", "A", 2, "백그라운드 5분 뒤 복귀",
         "YouTube 를 띄운 뒤 다른 앱 3개를 거쳐 5분 둔 뒤 돌아온다. 측정은 복귀 구간만. 프로세스가 살아 있었는지(YT_ALIVE/KILLED)를 측정 전에 기록해 warm/cold 복귀를 나눈다.",
         st, [YT, CHROME, MAPS, CAMERA])

# B4 ------------------------------------------------------------------
B4_URLS = ["https://en.m.wikipedia.org/wiki/NAND_flash", "https://en.m.wikipedia.org/wiki/Universal_Flash_Storage",
           "https://en.m.wikipedia.org/wiki/F2FS", "https://en.m.wikipedia.org/wiki/Android_(operating_system)",
           "https://en.m.wikipedia.org/wiki/Mars"]
st = [stop(CHROME, "Chrome 종료"), CHROME_CACHE, launch(CHROME, "Chrome 실행", wait=4), trace_start()]
for i, u in enumerate(B4_URLS):
    st += [tap_el("메뉴 열기", element_resource_id="com.android.chrome:id/menu_button"),
           tap_el("새 시크릿 탭", element_text="새 시크릿 탭"), sleep(1),
           tap_el("주소창", element_resource_id="com.android.chrome:id/url_bar"),
           text(u, f"탭 {i + 1} 열기"), sleep(6, "로딩 대기")]
st += [sh("for i in 1 2 3 4 5 6 7 8; do input swipe 300 250 1000 250 150; sleep 2; done; echo 8", "주소창 스와이프로 탭 8번 전환"),
       SETTLE, trace_stop(), FOCUS, stop(CHROME, "Chrome 종료 (시크릿 탭 폐기)")]
scenario("B4", "B", 2, "Chrome 탭 5개 열기+전환",
         "시크릿 탭 5개에 위키 문서를 열고 주소창 좌우 스와이프로 탭을 오간다. 개인 Chrome 의 기존 탭을 건드리지 않으려고 시크릿 탭을 쓰고, 종료하면 사라진다. 탭 상태 저장 write 를 본다.",
         st, [CHROME], verify=["두 번째 이후 새 시크릿 탭의 주소창 id", "주소창 스와이프 탭 전환 좌표"], needs=["Chrome 처음 실행 화면 완료"])

# B5 ------------------------------------------------------------------
st = [stop(CHROME, "Chrome 종료"), CHROME_CACHE,
      trace_start(), open_url("https://en.m.wikipedia.org/wiki/Gallery_of_sovereign_state_flags", "국기 갤러리 문서 열기"),
      sleep(10, "로딩 대기"), scroll(30, "이미지 문서 스크롤", pause=1),
      SETTLE, trace_stop(), FOCUS, stop(CHROME)]
scenario("B5", "B", 2, "Chrome 이미지 많은 문서",
         "국기 이미지 200여 개가 있는 위키 문서를 캐시를 비우고 열어 30번 스크롤. B1(글 위주 문서)과 캐시 write 양 비교.",
         st, [CHROME], needs=["Chrome 처음 실행 화면 완료"])

# B6 ------------------------------------------------------------------
st = [stop(MAPS), clear_app_cache(MAPS, ["*"], "지도 캐시 비우기"),
      trace_start(),
      # agent 는 콤마가 든 파라미터를 회차별 값 목록으로 보고 잘라 쓴다 (repeat 1 → "...geo:37.5665" 만 남아 따옴표가 안 닫힘).
      # 콤마를 기기에서 만들어 넣는다 (\\054 = ',').
      sh(f"am start -a android.intent.action.VIEW -d \"geo:$(echo 37.5665 126.9780 | tr ' ' '\\054')?z=15\" -p {MAPS}", "서울시청 좌표 열기 (검색 없이)"),
      sleep(8, "지도 로딩"), CLOSE_PERM,
      sh("for d in '300 1400 1000 1400' '1000 1400 300 1400' '636 1000 636 1900' '636 1900 636 1000' '200 1400 1100 1400'; do "
         "input swipe $d 300; sleep 3; done; echo pan5", "지도 이동 5번"),
      dtap(636, 1400, "확대 1"), sleep(3), dtap(636, 1400, "확대 2"), sleep(3), dtap(500, 1200, "확대 3"), sleep(3),
      dtap(800, 1600, "확대 4"), sleep(3), dtap(636, 1400, "확대 5"), sleep(3),
      SETTLE, trace_stop(), FOCUS, stop(MAPS)]
scenario("B6", "B", 2, "지도 이동·확대 10회",
         "검색 기록을 남기지 않으려고 좌표 인텐트로 서울시청을 열고, 이동 5번·두 번 탭 확대 5번. 지도 타일 캐시 read/write 를 본다.",
         st, [MAPS], verify=["두 번 탭 확대 동작"])

# B7 ------------------------------------------------------------------
# 2026-10-27 사용자가 Instagram 에 로그인. 좋아요·팔로우가 남지 않도록 탭 없이 스크롤만 한다 (Facebook 은 여전히 로그아웃이라 뺀다).
# 화면이 꺼져 있으면 잠금 화면 위에서 스와이프가 알림창을 내리므로 먼저 깨운다 (2026-10-27 dry-run 에서 확인)
st = [sh("input keyevent KEYCODE_WAKEUP; sleep 1; wm dismiss-keyguard; sleep 1; dumpsys window | grep -c isKeyguardShowing=true || true", "화면 켜기·잠금 해제"),
      stop(INSTA), clear_app_cache(INSTA, ["images.stash", "ExoPlayerCacheDir"], "Instagram 이미지·영상 캐시 비우기"),
      launch(INSTA, "Instagram 실행", wait=8), CLOSE_PERM, FOCUS,
      trace_start(), scroll(40, "홈 피드 스크롤 40회", pause=1.5), SETTLE, trace_stop(), FOCUS, stop(INSTA)]
scenario("B7", "B", 2, "Instagram 홈 피드 40회",
         "회차마다 이미지·영상 캐시를 비우고 홈 피드를 1.5초 간격으로 40번 스크롤. 좋아요·팔로우가 계정에 남지 않도록 탭은 하지 않는다. YouTube 홈피드(B3)와 캐시 write 비교.",
         st, [INSTA], needs=["Instagram 로그인"])

# B7r -----------------------------------------------------------------
# 릴스는 두 번 탭하면 좋아요가 되므로 영상은 탭하지 않고 탭 바의 릴스 버튼만 누른다
st = [st[0], stop(INSTA), clear_app_cache(INSTA, ["images.stash", "ExoPlayerCacheDir"], "Instagram 이미지·영상 캐시 비우기"),
      launch(INSTA, "Instagram 실행", wait=8), CLOSE_PERM,
      tap_el("릴스 탭", element_content_desc="릴스", x=381, y=2632), sleep(3, "첫 릴스 로딩"), FOCUS,
      trace_start(), scroll(20, "릴스 20개 넘기기 (5초씩 보기)", pause=5), SETTLE, trace_stop(), FOCUS, stop(INSTA)]
scenario("B7r", "B", 2, "Instagram 릴스 20개",
         "회차마다 이미지·영상 캐시를 비우고 릴스 탭에서 5초씩 보며 20개를 넘긴다. 좋아요가 남지 않도록 영상은 탭하지 않는다. 피드(B7)·YouTube 스트리밍(C1)과 영상 캐시 write 비교.",
         st, [INSTA], needs=["Instagram 로그인"])

# B7t -----------------------------------------------------------------
# 2026-10-27 사용자 요청: Facebook 대신 TikTok. 첫 실행의 광고성 정보 수신 동의 창은 사용자가 직접 처리했다.
# 좋아요(두 번 탭)·"관심 없음/흥미로움" 버튼이 계정 추천에 남지 않도록 화면은 탭하지 않고 스와이프만 한다
TIKTOK = "com.ss.android.ugc.trill"
st = [st[0], stop(TIKTOK),
      sh(f"rm -rf /data/data/{TIKTOK}/cache/cachev2 /sdcard/Android/data/{TIKTOK}/cache/video /sdcard/Android/data/{TIKTOK}/cache/picture; echo ok",
         "TikTok 영상·이미지 캐시 비우기"),
      launch(TIKTOK, "TikTok 실행 (추천 피드)", wait=10), CLOSE_PERM, FOCUS,
      trace_start(), scroll(20, "영상 20개 넘기기 (5초씩 보기)", pause=5), SETTLE, trace_stop(), FOCUS, stop(TIKTOK)]
scenario("B7t", "B", 2, "TikTok 추천 영상 20개",
         "회차마다 영상·이미지 캐시를 비우고 추천 피드에서 5초씩 보며 20개를 넘긴다. 화면은 탭하지 않는다. Instagram 릴스(B7r)와 같은 동작으로 영상 캐시 write 비교.",
         st, [TIKTOK], needs=["TikTok 첫 실행 동의 창 처리"])

# B8 ------------------------------------------------------------------
st = [stop(GMAIL), launch(GMAIL, "Gmail 실행", wait=6),
      trace_start(), scroll(30, "받은편지함 스크롤", pause=1.5), scroll(30, "위로 스크롤", pause=0.8, direction="up"),
      SETTLE, trace_stop(), FOCUS, stop(GMAIL)]
scenario("B8", "B", 2, "Gmail 받은편지함 스크롤",
         "받은편지함을 30번 내리고 다시 올린다. 메일을 열면 읽음 표시가 계정에 남으므로 열지 않는다. SQLite 위주 작은 I/O 를 본다.",
         st, [GMAIL], needs=["Gmail 첫 실행 안내 화면 완료"])

# B9 ------------------------------------------------------------------
st = [stop(PLAY), clear_app_cache(PLAY, ["*"], "Play 스토어 캐시 비우기"), launch(PLAY, "Play 스토어 실행", wait=6),
      trace_start(), scroll(25, "홈 추천 스크롤", pause=1.5),
      tap_el("인기 차트 탭", element_content_desc="인기 차트", x=706, y=1540), sleep(4, "차트 로딩"), scroll(15, "차트 스크롤", pause=1.5),
      SETTLE, trace_stop(), FOCUS, stop(PLAY)]
scenario("B9", "B", 2, "Play 스토어 둘러보기",
         "검색 기록을 남기지 않으려고 검색 대신 홈 추천과 인기 차트를 스크롤 (설치 안 함). 아이콘·배너 캐시 write 를 본다.",
         st, [PLAY], verify=["인기 차트 탭 위치(스크롤 전 화면)"])

# C4a / C4b -----------------------------------------------------------
for sid, q in (("C4a", "360p"), ("C4b", "1080p")):
    st = [
        launch(YT, "YouTube 실행", wait=6), tap_el("검색 열기", element_content_desc="검색"),
        text("nasa 4k", "검색어 입력"), sleep(4, "결과 로딩"),
        yt("일반 영상 선택", action="select_video"), yt("재생 준비 확인", action="watch", seconds=0),
        yt(f"화질 {q} 고정", action="quality", quality=q),
        trace_start(), yt(f"{q} 재생 3분", action="watch", seconds=180, ad_timeout=180),
        trace_stop(), FOCUS, stop(YT),
    ]
    scenario(sid, "C", 2, f"YouTube {q} 3분",
             f"C1 과 같은 영상을 화질 {q} 로 고정해 3분 재생. 화질별 버퍼(캐시) write 차이를 본다.", st, [YT])

# C5 ------------------------------------------------------------------
YT_PLAYER = (1000, 420)  # 세로 화면 인라인 플레이어 오른쪽 (왼쪽은 272)
st = [
    launch(YT, "YouTube 실행", wait=6), tap_el("검색 열기", element_content_desc="검색"),
    text("nasa 4k", "검색어 입력"), sleep(4, "결과 로딩"),
    yt("일반 영상 선택", action="select_video"), yt("재생 준비 확인", action="watch", seconds=0), sleep(20, "앞부분 버퍼링"),
    trace_start(),
    dtap(*YT_PLAYER, "앞으로 40초", n=5), sleep(6, "재생"),          # 8 ┐ ×5
    dtap(272, YT_PLAYER[1], "뒤로 20초", n=3), sleep(6, "재생"),     # 11┘
    SETTLE, trace_stop(), FOCUS, stop(YT),
]
scenario("C5", "C", 2, "YouTube 구간 이동 ×10",
         "재생 중 플레이어 오른쪽 연속 탭(+40초)과 왼쪽(-20초)을 번갈아 10번. 버퍼 밖으로 건너뛸 때 다시 받는 캐시 write 를 본다.",
         st, [YT], loops=[loop_over(st, 8, 11, 5)], verify=["플레이어 좌표·연속 탭 이동량", "영상 길이 4분 이상"])

# C6 ------------------------------------------------------------------
st = [stop(YTM),
      trace_start(),
      sh(f"am start -a android.intent.action.VIEW -d 'https://music.youtube.com/watch?v=dQw4w9WgXcQ' -p {YTM}", "곡 열기"),
      sleep(180, "음악 재생 3분"),
      SETTLE, trace_stop(),
      sh("dumpsys media_session | grep -m3 -E 'package=|state=PlaybackState'", "재생 상태 확인"), FOCUS, stop(YTM)]
scenario("C6", "C", 2, "YouTube Music 3분",
         "링크로 곡 하나(3분 33초)를 열어 3분 재생 (화면 켜짐). 오디오 캐시 write 를 C1(영상)과 비교. 재생 기록은 C1 처럼 남는다.",
         st, [YTM], verify=["링크로 바로 재생되는지(PlaybackState state=3)"])

# C7 ------------------------------------------------------------------
st = [
    DROP,
    sh("id=$(content query --uri content://media/external/video/media --projection _id "
       f"--where \"_data='{FIXTURE_VIDEO}'\" | sed -n 's/.*_id=\\([0-9]*\\).*/\\1/p' | head -1); "
       f"am start -a android.intent.action.VIEW -t video/mp4 -d content://media/external/video/media/$id -p {VIDEO}",
       "로컬 영상 열기"),
    sleep(3, "재생 시작"),
    trace_start(),
    sh("for x in 880 300 760 260 620 840 420 900 340 700; do input tap 636 1386; sleep 0.5; input tap $x 2393; sleep 4; done; echo seek10",
       "진행 막대 10곳 이동"),
    SETTLE, trace_stop(), FOCUS, HOME, stop(VIDEO),
]
scenario("C7", "C", 2, "로컬 동영상 이동 ×10",
         "C3 의 2분 영상을 캐시를 비우고 열어, 화면을 눌러 진행 막대를 띄운 뒤 10곳으로 건너뛴다. 비순차 read 를 C3(순차)와 비교.",
         st, [VIDEO], verify=["진행 막대 y 좌표"], needs=["setup.sh 의 fixture 영상"])

# D4 ------------------------------------------------------------------
VID_PRE = [MARK_NOW, sh("am start -W -a android.media.action.VIDEO_CAMERA", "카메라(동영상) 실행"), sleep(3, "카메라 준비")]
scenario("D4", "D", 2, "동영상 2분 1080p",
         "D3 와 같은 조건으로 2분 녹화. 장시간 지속 write 의 대역·주기를 본다. 측정 후 지운다.",
         VID_PRE + [trace_start(), tap_shutter("녹화 시작"), sleep(120, "녹화 2분"), tap_shutter("녹화 종료"), sleep(5, "저장 대기")] + post,
         [CAMERA])

# D5 ------------------------------------------------------------------
VSIZE = tap_el("해상도 메뉴", element_resource_id="com.oplus.camera:id/video_size_and_fps")
scenario("D5", "D", 2, "동영상 30초 4K",
         "해상도 메뉴에서 4K 를 골라 30초 녹화하고, 측정 뒤 1080p 로 되돌린다. D3(1080p)와 대역 비교. 측정 후 지운다.",
         VID_PRE + [VSIZE, tap_el("4K 선택", element_text="4K"), key(4, "메뉴 닫기"), sleep(2),
                    trace_start(), tap_shutter("녹화 시작"), sleep(30, "녹화 30초"), tap_shutter("녹화 종료"), sleep(8, "저장 대기"),
                    trace_stop(), FOCUS,
                    VSIZE, tap_el("1080p 로 되돌리기", element_text="1080p"), key(4, "메뉴 닫기"),
                    CLEAN_CAMERA, stop(CAMERA)],
         [CAMERA])

# D6 ------------------------------------------------------------------
scenario("D6", "D", 2, "사진 5장 → 바로 갤러리",
         "사진 5장을 찍자마자 카메라의 최근 사진 버튼으로 뷰어에 들어가 5장을 넘겨 본다. 저장 write 직후의 read·썸네일 생성을 본다. 측정 후 지운다.",
         pre + [trace_start(),
                sh(f"for i in $(seq 5); do input tap {SHUTTER[0]} {SHUTTER[1]}; sleep 2; done; echo 5", "사진 5장 촬영"),
                tap_el("최근 사진 열기", element_resource_id="com.oplus.camera:id/thumbnail"), sleep(3, "뷰어 로딩"),
                sh("for i in 1 2 3 4 5; do input swipe 170 1386 1100 1386 150; sleep 1.5; done; echo 5", "이전 사진 5장 넘기기"),
                SETTLE] + [trace_stop(), FOCUS, CLEAN_CAMERA, stop(CAMERA), stop(GALLERY)],
         [CAMERA, GALLERY], verify=["최근 사진 버튼이 여는 앱·넘김 방향"])

# D7 ------------------------------------------------------------------
SWITCH = tap_el("카메라 전환", element_resource_id="com.oplus.camera:id/switch_camera_button")
scenario("D7", "D", 2, "전면 카메라 사진 5장",
         "전면 카메라로 바꿔 2초 간격 5장. D1(후면) 대비 장당 write 양을 본다. 측정 뒤 후면으로 되돌리고 지운다.",
         [MARK_NOW, cam_still(), sleep(3, "카메라 준비"), SWITCH, sleep(3, "전면 전환"), tap_shutter("워밍업 1장"), sleep(4),
          trace_start(), sh(f"for i in $(seq 5); do input tap {SHUTTER[0]} {SHUTTER[1]}; sleep 2; done; echo 5", "사진 5장 촬영"),
          sleep(5, "저장 대기"), trace_stop(), FOCUS,
          tap_el("후면으로 되돌리기", element_content_desc="Rear Camera"), sleep(2), CLEAN_CAMERA, stop(CAMERA)],
         [CAMERA], verify=["전환 뒤 버튼 설명이 'Rear Camera' 인지"])

# D8 ------------------------------------------------------------------
st = [stop(CAMERA), cam_still(), sleep(3, "카메라 준비"),
      trace_start(),
      sh("am start -W -a android.media.action.VIDEO_CAMERA", "동영상 모드"), sleep(3),      # 4 ┐ ×5
      cam_still(), sleep(3),                                                              # 7 ┘
      SETTLE, trace_stop(), FOCUS, stop(CAMERA)]
scenario("D8", "D", 2, "사진↔동영상 모드 전환 ×5",
         "촬영 없이 사진·동영상 모드만 5번 오간다. 카메라 앱 자체의 I/O(설정·모델 파일 read) 기준선. D1~D3 에서 이 값을 빼고 볼 수 있다.",
         st, [CAMERA], loops=[loop_over(st, 4, 7, 5)])

# D9 ------------------------------------------------------------------
st = [launch(SETTINGS, "녹화할 화면: 설정", wait=3),
      trace_start(),
      sh("screenrecord --time-limit 60 /sdcard/Movies/ux_screenrec.mp4 & sleep 2; "
         "for i in $(seq 18); do input swipe 636 2000 636 900 300; sleep 3; done; wait; ls -l /sdcard/Movies/ux_screenrec.mp4",
         "화면 녹화 1분 (설정 스크롤하며)"),
      SETTLE, trace_stop(), rm_media("/sdcard/Movies/ux_screenrec.mp4", "녹화 파일 정리"), stop(SETTINGS)]
scenario("D9", "D", 2, "화면 녹화 1분",
         "screenrecord 로 1분 녹화하면서 설정 화면을 스크롤해 화면을 계속 바꾼다. 카메라 외 영상 생성 write 를 D3 와 비교. 측정 후 지운다.",
         st, [SETTINGS])

# E1 ------------------------------------------------------------------
st = [DROP, launch(GALLERY, "갤러리 실행", wait=5),
      trace_start(), scroll(20, "그리드 20번 스크롤", pause=1),
      step("tap", "사진 열기", x=636, y=1300), sleep(2, "뷰어 로딩"),
      sh("for i in 1 2 3 4; do input swipe 1100 1386 170 1386 150; sleep 2; done; echo 4", "다음 사진 4장"),
      SETTLE, trace_stop(), FOCUS, stop(GALLERY)]
scenario("E1", "E", 2, "갤러리 가벼운 사용",
         "그리드를 20번만 스크롤하고 사진 5장을 본다 (썸네일이 이미 있는 warm 상태). G1·G2(1000장 전체)와 비교할 일상 사용 기준선. "
         "기기에 다른 사진이 없어 NASA 세트 위에서 잰다.",
         st, [GALLERY], needs=["NASA 세트 1000장"])

# E5 ------------------------------------------------------------------
st = [sh("rm -rf /sdcard/ux_small; mkdir -p /sdcard/ux_small; sync", "폴더 준비"), DROP,
      trace_start(),
      sh("cd /sdcard/ux_small && for i in $(seq 1000); do head -c 4096 /dev/urandom > f$i; done; sync; ls | wc -l", "4KB 파일 1000개 만들기"),
      sleep(3), sh("rm -rf /sdcard/ux_small; sync; echo removed", "1000개 지우기"),
      SETTLE, trace_stop()]
scenario("E5", "E", 2, "작은 파일 1000개 생성·삭제",
         "/sdcard(FUSE)에 4KB 파일 1000개를 만들고 지운다. 데이터보다 메타데이터(노드·checkpoint) write 가 얼마나 되는지 본다.",
         st, [])

# E6 ------------------------------------------------------------------
st = [sh("dd if=/dev/urandom of=/sdcard/ux_big.bin bs=1M count=1024 2>&1 | tail -1; sync", "1GB 파일 만들기"), DROP,
      trace_start(), sh("rm -f /sdcard/ux_big.bin; sync; echo removed", "1GB 파일 지우기"), sleep(10, "discard 대기"),
      trace_stop()]
scenario("E6", "E", 2, "1GB 파일 삭제",
         "1GB 파일을 측정 밖에서 만들고 지우는 것만 잰다. UNMAP(discard)이 바로 나가는지, E4 처럼 안 나가는지 확인.",
         st, [])

# E7 ------------------------------------------------------------------
st = [sh("mkdir -p /sdcard/Download && dd if=/dev/urandom of=/sdcard/Download/ux_e7.bin bs=1M count=256 2>&1 | tail -1; "
         "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/Download/ux_e7.bin >/dev/null; sync",
         "원본 256MB 만들기"),
      rm_media("/sdcard/Documents/ux_e7*.bin", "이전 복사본 정리"), DROP,
      launch(FILEMGR, "파일 관리자 실행", wait=4),
      tap_el("다운로드 열기", element_text="다운로드"), sleep(2),
      trace_start(),
      sh("input swipe 238 850 238 850 800", "파일 길게 눌러 선택"),
      tap_el("더 보기", element_content_desc="더 보기"), tap_el("복사", element_text="복사"),
      tap_el("Documents 폴더", element_text="Documents"), tap_el("여기에 붙여넣기", element_text="여기에 붙여넣기"),
      sh("for i in $(seq 60); do [ \"$(stat -c %s /sdcard/Documents/ux_e7.bin 2>/dev/null)\" = 268435456 ] && break; sleep 1; done; "
         "sleep 2; sync; ls -l /sdcard/Documents/ux_e7.bin", "복사 끝날 때까지 대기"),
      SETTLE, trace_stop(), FOCUS, stop(FILEMGR),
      rm_media("/sdcard/Download/ux_e7.bin /sdcard/Documents/ux_e7.bin", "파일 정리")]
scenario("E7", "E", 2, "파일 관리자로 256MB 복사",
         "파일 관리자 앱에서 다운로드의 256MB 파일을 Documents 로 복사. E2(셸 cp)와 같은 일을 앱으로 했을 때 차이를 본다.",
         st, [FILEMGR], verify=["다운로드 목록 첫 파일 위치"])

# E8 ------------------------------------------------------------------
st = [rm_media("/sdcard/Download/100Mb*.dat /sdcard/Download/.pending-*100Mb*", "이전 다운로드 정리"), stop(CHROME),
      trace_start(),
      open_url("https://proof.ovh.net/files/100Mb.dat", "100MB 파일 다운로드"),
      # 한 번 받은 파일이면 Chrome 이 "파일을 다시 다운로드하시겠습니까?" 를 띄운다 (URL 에 쿼리를 붙여도 뜬다).
      # 화면 덤프는 tmpfs(/dev/ux)에 써서 측정에 write 가 섞이지 않게 한다.
      # 창이 4초 안에 안 뜬 회차가 있어 최대 20초 동안 2초마다 확인한다 (다운로드가 이미 시작됐으면 그만 본다)
      sh(f"mkdir -p {DEV_OUT}; r=no-prompt; for i in $(seq 10); do sleep 2; ls /sdcard/Download/ | grep -q '100Mb' && break; "
         f"uiautomator dump {DEV_OUT}/ux_ui.xml >/dev/null 2>&1; "
         f"if grep -q '다시 다운로드' {DEV_OUT}/ux_ui.xml; then input tap 1015 1782; r=redownload; break; fi; done; rm -f {DEV_OUT}/ux_ui.xml; echo $r",
         "다시 다운로드 확인 창 누르기"),
      sh("for i in $(seq 300); do [ \"$(stat -c %s /sdcard/Download/100Mb*.dat 2>/dev/null | head -1)\" = 104857600 ] && break; sleep 1; done; "
         "echo waited ${i}s; ls -l /sdcard/Download/ | grep 100Mb", "다운로드 완료 대기 (최대 5분)"),
      SETTLE, trace_stop(), FOCUS, stop(CHROME), rm_media("/sdcard/Download/100Mb*.dat /sdcard/Download/.pending-*100Mb*", "다운로드 파일 정리")]
scenario("E8", "E", 2, "Chrome 100MB 다운로드",
         "공개 속도 시험 파일(OVH 100MB)을 Chrome 으로 받는다 (Hetzner 는 이 망에서 빈 응답, thinkbroadband 는 http 라 Chrome 이 막음). 네트워크 속도에 묶인 순차 write. Chrome 다운로드 목록에는 기록이 남는다.",
         st, [CHROME], verify=["다운로드 확인 창 여부", "저장 파일 이름"], needs=["Chrome 처음 실행 화면 완료"])

# F1 ------------------------------------------------------------------
NOTE_TEXT = "UFS fsio trace note " * 25
st = [stop(NOTE), launch(NOTE, "메모 실행", wait=4),
      trace_start(),
      tap_el("새 메모", element_content_desc="새 메모", element_match_mode="contains"), sleep(2),
      text(NOTE_TEXT, "긴 글 입력", submit="false"), sleep(2),
      key(4, "키보드 닫기"), sleep(1),
      # 뒤로 키는 보기 모드로만 바뀌고 편집 화면에 남는다 → 툴바의 뒤로 버튼으로 목록에 나간다
      tap_el("저장하고 목록으로", element_resource_id="com.oneplus.note:id/coui_toolbar_back_view", element_content_desc="뒤로"), sleep(3, "저장 대기"),
      SETTLE, trace_stop(), FOCUS,
      # 정리: 목록에서 방금 쓴 메모를 길게 눌러 선택 → 아래 삭제 → 확인 (최근 삭제 폴더로 간다).
      # 편집 화면 메뉴의 삭제는 스텝으로 누르면 확인 창이 안 뜰 때가 있었다.
      sleep(1, "목록 표시 대기"),
      sh("input swipe 636 1428 636 1428 800", "방금 쓴 메모 길게 눌러 선택"), sleep(1),
      tap_el("삭제", element_resource_id="com.oneplus.note:id/note_delete"), sleep(1, "확인 창 대기"),
      tap_el("삭제 확인", element_resource_id="android:id/button3"), sleep(2, "삭제 반영 대기"), stop(NOTE)]
scenario("F1", "F", 2, "메모 작성·저장",
         "새 메모에 긴 글(약 500자)을 입력하고 저장. 작은 SQLite write 와 fsync 를 본다. 측정 후 그 메모를 지운다.",
         st, [NOTE], verify=["저장 뒤 목록에서 메모 찾기"], needs=["메모 첫 실행 동의 화면 완료"])

# F2 ------------------------------------------------------------------
st = [MARK_NOW, stop(RECORDER), launch(RECORDER, "녹음기 실행", wait=4),
      trace_start(),
      tap_el("녹음 시작", element_resource_id="com.oneplus.soundrecorder:id/middle_control"), sleep(60, "녹음 1분"),
      # 녹음 중에는 화면이 계속 움직여 uiautomator dump 가 안 된다 → 시작 버튼과 같은 자리의 정지 버튼을 좌표로
      step("tap", "녹음 종료(자동 저장)", x=635, y=2478), sleep(4, "저장 대기"),
      SETTLE, trace_stop(), FOCUS, stop(RECORDER),
      # 파일 이름에 공백이 있다 (Music/Recordings/Standard Recordings/표준 녹음 1.mp3) → find -exec 로 지운다
      sh(f"find /storage/emulated/0/Music /storage/emulated/0/Recordings -type f -newer {MARK} -exec sh -c "
         "'for f; do content delete --uri content://media/external/file --where \"_data='\"'\"'$f'\"'\"'\"; rm -f \"$f\"; echo \"rm $f\"; done' _ {} + 2>/dev/null; echo done",
         "녹음 파일 정리")]
scenario("F2", "F", 2, "녹음 1분",
         "녹음기로 1분 녹음. 낮은 대역의 지속 write 를 D3(동영상)와 비교. 측정 후 녹음 파일을 지운다.",
         st, [RECORDER], verify=["녹음 파일 정리"], needs=["녹음기 첫 실행 동의 화면 완료", "마이크 권한"])

# F4 ------------------------------------------------------------------
st = [stop(CONTACTS), launch(CONTACTS, "연락처 실행", wait=4),
      trace_start(),
      # 목록을 스크롤하면 검색창이 접혀 사라지므로 검색을 먼저 한다. 이름이 한글이라 번호(010)로 찾는다
      tap_el("검색", element_resource_id="com.google.android.contacts:id/open_search_bar"), text("010", "검색어 입력", submit="false"), sleep(3),
      key(4, "키보드 닫기"), key(4, "검색 닫기"), sleep(1),
      scroll(10, "목록 스크롤", pause=1),
      SETTLE, trace_stop(), FOCUS, stop(CONTACTS)]
scenario("F4", "F", 2, "연락처 스크롤·검색",
         "연락처 목록 스크롤과 검색. 작은 read 위주. 연락처가 적으면 I/O 가 거의 없을 수 있다.",
         st, [CONTACTS], verify=["검색창 요소"], needs=["연락처 권한 허용"])

# F5 ------------------------------------------------------------------
st = [stop(CALENDAR), launch(CALENDAR, "캘린더 실행", wait=5),
      trace_start(),
      sh("for i in $(seq 12); do input swipe 1100 1600 200 1600 200; sleep 2; done; echo 12", "다음 달로 12번"),
      SETTLE, trace_stop(), FOCUS, stop(CALENDAR)]
scenario("F5", "F", 2, "캘린더 월 이동 ×12",
         "월 보기에서 왼쪽 스와이프로 12달을 넘긴다. 일정 DB read 와 작은 write.",
         st, [CALENDAR], verify=["기본 보기가 월 보기인지"])

# G3 ------------------------------------------------------------------
st = [DROP, launch(GALLERY, "갤러리 실행", wait=5),
      gfx_reset(GALLERY), perfetto_start("G3"),
      trace_start(), scroll(40, "그리드 빠른 fling", pause=0.3, duration=80), SETTLE, trace_stop(),
      PERFETTO_STOP, gfx_dump(GALLERY, "G3"), FOCUS, stop(GALLERY)]
scenario("G3", "G", 2, "그리드 빠른 fling",
         "G1 과 같은 그리드를 짧고 빠른 fling 으로 끝까지. 썸네일 read 가 몰릴 때 QD·jank 를 본다. 1회차 cold, 2·3회차 warm.",
         st, [GALLERY], verify=["40번이면 끝에 닿는지"], needs=G_NEEDS)

# G4 ------------------------------------------------------------------
st = [DROP, launch(GALLERY, "갤러리 실행", wait=5),
      step("tap", "첫 사진 열기", x=126, y=550), sleep(2, "뷰어 로딩"),
      gfx_reset(GALLERY), perfetto_start("G4"),
      trace_start(),
      sh("for i in $(seq 300); do input swipe 1100 1386 170 1386 100; sleep 0.15; done; echo 300", "다음 사진 300장 빠르게"),
      SETTLE, trace_stop(),
      PERFETTO_STOP, gfx_dump(GALLERY, "G4"), FOCUS, stop(GALLERY)]
scenario("G4", "G", 2, "뷰어 빠른 넘기기 300장",
         "G2 보다 빠르게(0.15초 간격) 앞 300장을 넘긴다. 원본 read 가 화면을 못 따라갈 때 jank 와 겹치는지 본다.",
         st, [GALLERY], needs=G_NEEDS)

# G5 ------------------------------------------------------------------
st = [DROP, launch(GALLERY, "갤러리 실행", wait=5),
      step("tap", "첫 사진 열기", x=126, y=550), sleep(2, "뷰어 로딩"),
      gfx_reset(GALLERY), perfetto_start("G5"),
      trace_start(),
      dtap(636, 1386, "두 번 탭 확대"), sleep(1.5, "원본 타일 로딩"),                                      # 7 ┐
      sh("input swipe 900 1386 400 1386 300; sleep 1; input swipe 636 1800 636 1000 300", "확대한 채 이동"), sleep(1),  # 9 │ ×20
      dtap(636, 1386, "원래 크기"), sleep(0.5),                                                         #   │
      sh("input swipe 1100 1386 170 1386 150", "다음 사진"), sleep(1),                                   # 14┘
      SETTLE, trace_stop(),
      PERFETTO_STOP, gfx_dump(GALLERY, "G5"), FOCUS, stop(GALLERY)]
scenario("G5", "G", 2, "사진 20장 확대",
         "사진마다 두 번 탭으로 확대해 이리저리 옮겨 본 뒤 다음 사진으로 (20장). 원본 부분(타일) read 를 본다. input 으로는 두 손가락 확대가 안 돼 두 번 탭으로 대신한다.",
         st, [GALLERY], loops=[loop_over(st, 7, 14, 20)], needs=G_NEEDS)

# G6 ------------------------------------------------------------------
cells = [(126 + 255 * (i % 5), 550 + 255 * (i // 5)) for i in range(20)]
st = [launch(GALLERY, "갤러리 실행", wait=5),
      trace_start(),
      sh(f"input swipe {cells[0][0]} {cells[0][1]} {cells[0][0]} {cells[0][1]} 800", "첫 사진 길게 눌러 선택"),
      sh("; ".join(f"input tap {x} {y}" for x, y in cells[1:]) + "; echo 19", "19장 더 선택"),
      tap_el("삭제", element_resource_id="com.oneplus.gallery:id/action_recycle"),
      tap_el("삭제 확인", element_resource_id="android:id/button3"), sleep(5, "휴지통 이동 대기"),
      tap_el("앨범 탭", element_text="앨범"), sleep(2), scroll(2, "기타 앨범까지", pause=1),
      tap_el("최근 삭제된 항목", element_text="최근 삭제된 항목"), sleep(2),
      tap_el("모두 삭제", element_text="모두 삭제", element_match_mode="contains"),
      tap_el("영구 삭제 확인", element_resource_id="android:id/button3"), sleep(5, "삭제 대기"),
      SETTLE, trace_stop(), FOCUS, stop(GALLERY),
      sh(f"echo NASA_LEFT=$(ls {NASA_DIR} | wc -l)", "남은 장수 기록")]
scenario("G6", "G", 2, "20장 삭제 → 휴지통 비우기",
         "사진 탭 맨 앞 20장(모두 NASA 세트)을 골라 지우고 최근 삭제된 항목을 비운다. 회차마다 20장씩 줄어 3회 뒤 940장이 남고, "
         "measure_p2.sh 가 끝난 뒤 push.py 로 빠진 60장만 다시 넣는다.",
         st, [GALLERY], verify=["모두 삭제 버튼 이름", "영구 삭제 확인 버튼 id"], needs=["NASA 세트 1000장 (기기에 다른 사진 없음)"])


# ================= S 대기(standby) =================
# 무선 adb(USB 를 빼서 충전 없음)로 돌린다: UX_DEVICE=192.168.1.20:5555 ./run.py S1 ...
# 대기 중 adb 연결·agent 상태 조회도 기기를 깨울 수 있다 (한계로 적는다).
STBY_APPS = [(YT, "YouTube"), (CHROME, "Chrome"), (GMAIL, "Gmail"), (MAPS, "지도")]
WAKE = sh("input keyevent KEYCODE_WAKEUP; sleep 1; wm dismiss-keyguard; sleep 1; dumpsys window | grep -c isKeyguardShowing=true || true", "화면 켜기·잠금 해제")
SCREEN_OFF = sh("input keyevent KEYCODE_SLEEP; sleep 1; dumpsys power | grep -m1 mWakefulness=", "화면 끄기")
STBY_PRE = [WAKE] + [launch(p_, f"{n_} 띄워 두기", wait=5) for p_, n_ in STBY_APPS] + [HOME, sleep(5)]
STBY_LOG = sh("dumpsys deviceidle | grep -E 'mState=|mLightState='; dumpsys battery | grep -E 'level|AC powered|USB powered'; "
              "dumpsys power | grep -m1 mWakefulness=", "대기 상태·배터리 기록")
STBY_NEEDS = ["무선 adb 연결 (USB 분리, 충전 없음)", "UX_DEVICE=<ip:port> UX_SERIAL=<ip:port>"]

scenario("S1", "S", 3, "화면 꺼짐 대기 30분",
         "앱 4개(YouTube·Chrome·Gmail·지도)를 띄워 둔 뒤 화면을 끄고 30분 그대로 둔다. 기기가 스스로 light/deep doze 로 들어가는 동안의 배경 I/O.",
         STBY_PRE + [SCREEN_OFF, sleep(10, "화면 꺼짐 안정"), STBY_LOG,
                     trace_start(), sleep(1800, "화면 꺼짐 대기 30분"), trace_stop(), STBY_LOG, WAKE] + [stop(p_) for p_, _ in STBY_APPS],
         [p_ for p_, _ in STBY_APPS], needs=STBY_NEEDS)

scenario("S2", "S", 3, "강제 deep doze 30분",
         "S1 과 같은 상태에서 화면을 끄자마자 deep doze 로 강제 진입(dumpsys deviceidle force-idle deep)시키고 30분. doze 중 정비 구간(maintenance window) I/O 만 남는지 본다. 끝나면 강제 상태를 푼다.",
         STBY_PRE + [SCREEN_OFF, sleep(10, "화면 꺼짐 안정"), sh("dumpsys deviceidle force-idle deep", "deep doze 강제 진입"), STBY_LOG,
                     trace_start(), sleep(1800, "deep doze 대기 30분"), trace_stop(), STBY_LOG,
                     sh("dumpsys deviceidle unforce; echo unforced", "강제 doze 해제"), WAKE] + [stop(p_) for p_, _ in STBY_APPS],
         [p_ for p_, _ in STBY_APPS], needs=STBY_NEEDS)

scenario("S3", "S", 3, "화면 끈 직후 5분",
         "앱 4개를 띄워 둔 상태에서 측정을 켜고 화면을 끈 뒤 5분. 화면을 끄는 순간 앱·시스템이 상태를 저장하는 쓰기와 초반 배경 I/O.",
         STBY_PRE + [STBY_LOG, trace_start(), SCREEN_OFF, sleep(300, "화면 끈 뒤 5분"), trace_stop(), STBY_LOG, WAKE]
         + [stop(p_) for p_, _ in STBY_APPS],
         [p_ for p_, _ in STBY_APPS], needs=STBY_NEEDS)

scenario("S4", "S", 3, "화면 켜진 홈 대기 10분",
         "앱 4개를 띄워 둔 뒤 홈 화면을 켜 둔 채(svc power stayon true) 아무 입력 없이 10분. S1 과 비교할 화면 켜짐 기준선. 끝나면 stayon 을 끈다.",
         STBY_PRE + [sh("svc power stayon true; echo stayon", "화면 켜짐 유지"), STBY_LOG,
                     trace_start(), sleep(600, "홈 화면 대기 10분"), trace_stop(), STBY_LOG,
                     sh("svc power stayon false; echo stayoff", "화면 켜짐 유지 해제")] + [stop(p_) for p_, _ in STBY_APPS],
         [p_ for p_, _ in STBY_APPS], needs=STBY_NEEDS)

scenario("S5", "S", 3, "아무것도 안 하는 대기 3시간",
         "앱을 따로 띄우지 않고(앞 측정에서 남은 상태 그대로) 홈에서 화면을 끄고 3시간 둔다. 오래 둘 때의 배경 I/O(동기화·로그·유지보수 작업)와 doze 정비 구간 주기를 본다. "
         "시간이 길어 1회만 잰다 (밤새 돌리기용).",
         [WAKE, HOME, sleep(5), SCREEN_OFF, sleep(10, "화면 꺼짐 안정"), STBY_LOG,
          trace_start(), sleep(10800, "아무것도 안 하고 3시간"), trace_stop(), STBY_LOG, WAKE],
         [], repeat=1, needs=STBY_NEEDS)

# ---------------- 출력 ----------------
DIRS = {"A": "A-app-launch", "B": "B-web-feed", "C": "C-media", "D": "D-camera", "E": "E-storage", "F": "F-productivity", "G": "G-gallery", "S": "S-standby"}


def to_doc(s):
    for lp in s["loops"]:
        assert 0 <= lp["startStep"] <= lp["endStep"] < len(s["steps"]), (s["id"], lp)
    notes = []
    if s["needs"]:
        notes.append("준비: " + ", ".join(s["needs"]))
    if s["verify"]:
        notes.append("dry-run 확인: " + ", ".join(s["verify"]))
    desc = f"[{s['id']} · P{s['prio']}] {s['desc']}" + ("" if not notes else " " + " / ".join(notes))
    return {
        "schemaVersion": 1, "kind": "scenario",
        "name": f"[UX-fsio] {s['id']} {s['name']}",
        "description": desc,
        "repeatCount": s["repeat"],
        "steps": s["steps"], "loops": s["loops"],
        "requirements": {"packages": s["packages"], "sourceWidth": W, "sourceHeight": H, "traceType": "fsio_ufs"},
        "origin": {"deviceModel": DEVICE},
    }


def main():
    import jsonschema

    schema = json.loads(SCHEMA.read_text())
    docs = []
    for s in S:
        d = to_doc(s)
        jsonschema.validate(d, schema)
        out = HERE / DIRS[s["type"]] / f"{s['id']}.scenario.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
        docs.append(d)
    (HERE / "pack.scenariopack.json").write_text(json.dumps(docs, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(docs)}개 생성·스키마 검증 통과 → scenarios/*/ , pack.scenariopack.json")
    for s in S:
        n = len(s["steps"])
        print(f"  {s['id']:4} P{s['prio']} {s['name']:28} steps={n:2} repeat={s['repeat']}"
              + (f" loops={[(l['startStep'], l['endStep'], l['count']) for l in s['loops']]}" if s["loops"] else ""))


if __name__ == "__main__":
    main()
