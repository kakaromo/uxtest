#!/usr/bin/env python3
"""images/ 의 NASA 사진을 기기 /sdcard/Pictures/NASA/ 에 넣고 MediaProvider 등록을 확인한다.

  ./push.py            # 넣기 (이미 다 있으면 건너뜀)
  ./push.py --repush   # cold 세트 재생성: 지우고 새 파일명(g<세대>_<id>.jpg)으로 다시 넣는다
  ./push.py --remove   # 기기에서 제거
  ./push.py --status   # 기기 쪽 장수·세대만 출력

cold 측정을 위해 --repush 는 파일명을 바꾼다. 같은 이름으로 다시 넣으면 갤러리 앱이
경로 기준 썸네일 캐시를 재사용할 수 있어 cold 가 아니게 된다.
"""
import argparse
import csv
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SERIAL = os.environ.get("UX_SERIAL", "3C1677001HN00000")
DIR = "/storage/emulated/0/Pictures/NASA"
GEN = "/data/local/tmp/ux_nasa_gen"


def sh(cmd, check=True):
    r = subprocess.run(["adb", "-s", SERIAL, "shell", cmd], capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"adb shell 실패: {cmd}\n{r.stderr}")
    return r.stdout.strip()


def rows_on_device():
    out = sh(f"content query --uri content://media/external/images/media --projection _id "
             f"--where \"_data LIKE '{DIR}/%'\"", check=False)
    return out.count("_id=")


def files_on_device():
    out = sh(f"ls {DIR} 2>/dev/null | grep -c '\\.jpg$'", check=False)
    return int(out or 0)


def gen():
    return int(sh(f"cat {GEN} 2>/dev/null || echo 0", check=False) or 0)


def remove():
    sh(f"rm -rf {DIR}")
    sh(f"content delete --uri content://media/external/file --where \"_data LIKE '{DIR}/%'\"", check=False)
    for _ in range(10):
        if rows_on_device() == 0:
            break
        time.sleep(1)
    print(f"  제거: 파일 {files_on_device()} / MediaProvider {rows_on_device()}")


def push(g):
    ids = [r["nasa_id"] for r in csv.DictReader(open(os.path.join(HERE, "manifest.csv")))]
    # 같은 볼륨이어야 하드링크가 되므로 이 폴더 안에 임시 폴더를 만든다
    with tempfile.TemporaryDirectory(dir=HERE, prefix=".stage-") as tmp:
        # 이름만 바꾼 하드링크 묶음을 한 번에 push (adb 는 디렉터리 push 가 파일별 호출보다 훨씬 빠르다).
        # 심볼릭 링크는 adb 가 링크 자체를 올려서 안 된다.
        stage = os.path.join(tmp, "NASA")
        os.mkdir(stage)
        for nid in ids:
            name = f"{nid}.jpg" if g == 0 else f"g{g}_{nid}.jpg"
            os.link(os.path.join(HERE, "images", f"{nid}.jpg"), os.path.join(stage, name))
        t0 = time.time()
        subprocess.run(["adb", "-s", SERIAL, "push", "--sync", "-Z", stage, "/storage/emulated/0/Pictures/"],
                       check=True)
        print(f"  push {len(ids)}장 {time.time() - t0:.0f}s")
    sh(f"echo {g} > {GEN}")
    # /sdcard 는 FUSE 라 파일을 닫을 때 MediaProvider 가 행을 만든다. 빠진 게 있으면 폴더 스캔으로 메운다.
    for i in range(30):
        n = rows_on_device()
        if n >= len(ids):
            break
        if i == 5:
            sh(f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{DIR}", check=False)
        time.sleep(2)
    n = rows_on_device()
    print(f"  MediaProvider {n}/{len(ids)}")
    if n < len(ids):
        sys.exit("등록이 덜 됐습니다 — 갤러리를 한 번 열거나 잠시 뒤 --status 로 다시 확인하세요")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--repush", action="store_true")
    g.add_argument("--remove", action="store_true")
    g.add_argument("--status", action="store_true")
    a = ap.parse_args()
    want = sum(1 for _ in csv.DictReader(open(os.path.join(HERE, "manifest.csv"))))
    print(f"기기 {SERIAL}: 파일 {files_on_device()} / MediaProvider {rows_on_device()} / 세대 {gen()} (원본 {want}장)")
    if a.status:
        return
    if a.remove:
        remove()
        sh(f"rm -f {GEN}")
        return
    if a.repush:
        nxt = gen() + 1
        remove()
        push(nxt)
        return
    if files_on_device() == want and rows_on_device() == want:
        print("  이미 다 있음")
        return
    push(gen())


if __name__ == "__main__":
    main()
