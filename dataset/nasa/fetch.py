#!/usr/bin/env python3
"""NASA Image and Video Library 에서 사진 1000장을 images/ 에 받는다.

  ./fetch.py            # 1000장 (이미 받은 파일·sha256 일치는 건너뜀 → 중단 후 다시 실행 가능)
  ./fetch.py --n 50     # 시험용 소량

- 키워드 여러 개로 검색해 nasa_id 중복을 뺀다. 키워드 순서·페이지 순서가 고정이라 다시 돌려도 같은 목록이 된다.
- 원본(~orig.jpg)을 받되 25MB 를 넘으면 ~large.jpg 로 받는다 (갤러리 실사용 크기대 유지).
- 설명·크레딧에 저작권 표기(©, copyright, courtesy of)가 있는 항목은 뺀다 → NASA 퍼블릭 도메인만.
- manifest.csv: nasa_id, title, keywords, center, url, variant, bytes, width, height, sha256
"""
import argparse
import concurrent.futures as cf
import csv
import hashlib
import json
import os
import re
import struct
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, "images")
MANIFEST = os.path.join(HERE, "manifest.csv")
API = "https://images-api.nasa.gov"
KEYWORDS = ["galaxy", "nebula", "mars", "earth", "apollo", "jupiter", "saturn",
            "international space station", "hubble", "moon", "sun", "astronaut"]
MAX_ORIG = 25 * 1024 * 1024
COPYRIGHT = re.compile(r"©|copyright|courtesy of|all rights reserved", re.I)
FIELDS = ["nasa_id", "title", "keywords", "center", "url", "variant", "bytes", "width", "height", "sha256"]


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 ** i)


def head_size(url):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers.get("Content-Length") or 0)
    except Exception:
        return 0


def search(n):
    seen, out = set(), []
    for kw in KEYWORDS:
        page = 1
        while len(out) < n and page <= 20:
            q = urllib.parse.urlencode({"q": kw, "media_type": "image", "page": page, "page_size": 100})
            items = json.loads(get(f"{API}/search?{q}"))["collection"]["items"]
            if not items:
                break
            for it in items:
                d = it["data"][0]
                nid = d["nasa_id"]
                text = " ".join(str(d.get(k, "")) for k in ("description", "photographer", "secondary_creator"))
                if nid in seen or COPYRIGHT.search(text):
                    continue
                seen.add(nid)
                out.append({"nasa_id": nid, "title": d.get("title", ""), "center": d.get("center", ""),
                            "keywords": ";".join(d.get("keywords") or [])})
            page += 1
        if len(out) >= n:
            break
    return out[:n]


def jpeg_size(path):
    """SOF 마커에서 가로×세로를 읽는다 (외부 라이브러리 없이)."""
    with open(path, "rb") as f:
        if f.read(2) != b"\xff\xd8":
            return 0, 0
        while True:
            b = f.read(1)
            while b and b != b"\xff":
                b = f.read(1)
            while b == b"\xff":
                b = f.read(1)
            if not b:
                return 0, 0
            m = b[0]
            if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                continue
            ln = struct.unpack(">H", f.read(2))[0]
            if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">xHH", f.read(5))
                return w, h
            f.seek(ln - 2, 1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_one(item, done):
    nid = item["nasa_id"]
    dst = os.path.join(IMG, f"{nid}.jpg")
    prev = done.get(nid)
    if prev and os.path.exists(dst) and sha256(dst) == prev["sha256"]:
        return prev
    assets = [x["href"] for x in json.loads(get(f"{API}/asset/{urllib.parse.quote(nid)}"))["collection"]["items"]]
    pick = None
    for variant in ("orig", "large"):
        url = next((a for a in assets if a.lower().endswith(f"~{variant}.jpg")), None)
        if url and (variant != "orig" or 0 < head_size(url) <= MAX_ORIG):
            pick = (url.replace("http://", "https://"), variant)
            break
    if not pick:
        return None
    tmp = dst + ".part"
    with open(tmp, "wb") as f:
        f.write(get(pick[0]))
    os.replace(tmp, dst)
    w, h = jpeg_size(dst)
    return item | {"url": pick[0], "variant": pick[1], "bytes": os.path.getsize(dst),
                   "width": w, "height": h, "sha256": sha256(dst)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    os.makedirs(IMG, exist_ok=True)
    done = {}
    if os.path.exists(MANIFEST):
        done = {r["nasa_id"]: r for r in csv.DictReader(open(MANIFEST))}

    # 받을 수 없는 항목(jpg 없음 등)을 대비해 여유 있게 검색해 두고 n 장을 채운다.
    cands = search(int(a.n * 1.3))
    print(f"후보 {len(cands)}개, 기존 {len(done)}장")
    rows, fails = [], 0
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        it = iter(cands)
        pending = {ex.submit(fetch_one, c, done): c for c in [next(it) for _ in range(min(a.n, len(cands)))]}
        while pending:
            fin, _ = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
            for fu in fin:
                c = pending.pop(fu)
                try:
                    r = fu.result()
                except Exception as e:
                    r = None
                    print(f"  실패 {c['nasa_id']}: {e}")
                if r:
                    rows.append(r)
                    if len(rows) % 50 == 0:
                        print(f"  {len(rows)}장", flush=True)
                else:
                    fails += 1
                if r is None and len(rows) + len(pending) < a.n:
                    nxt = next(it, None)  # 빠진 만큼 다음 후보로 채운다
                    if nxt:
                        pending[ex.submit(fetch_one, nxt, done)] = nxt

    order = {c["nasa_id"]: i for i, c in enumerate(cands)}
    rows.sort(key=lambda r: order[r["nasa_id"]])
    with open(MANIFEST, "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    keep = {r["nasa_id"] for r in rows}
    for fn in os.listdir(IMG):  # 목록에서 빠진 파일 정리 (다른 --n 으로 받았던 것 등)
        if fn.endswith(".part") or fn[:-4] not in keep:
            os.remove(os.path.join(IMG, fn))
    total = sum(int(r["bytes"]) for r in rows)
    print(f"완료 {len(rows)}장, {total / 2**30:.2f} GiB, 건너뜀 {fails}개 → {MANIFEST}")


if __name__ == "__main__":
    main()
