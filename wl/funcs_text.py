#!/usr/bin/env python3
"""시나리오 함수 묶음(funcs.bin) ↔ 공개 텍스트(wl/funcs/)

  python3 wl/funcs_text.py export   # .private/funcs/funcs.bin → wl/funcs/
  python3 wl/funcs_text.py build    # wl/funcs/ → .private/funcs/funcs-from-text.bin (uxwl 이 읽는 형식)
  python3 wl/funcs_text.py check    # 둘이 같은 TC 인지 (동작·파일 표·DB 구조)

wl/funcs/ 구성
  index.json            유형 → 함수 → 유형 안 비중, 함수 → 이름·회차 목록 (seg, durSec, nfiles, nreq)
  <함수>/rep<k>.files.csv   file,size,flags,dir,db
      file  회차 안 파일 번호 (ops 의 file 과 같음)
      flags 1 원래 있던 파일(미리 채움), 2 SQLite DB, 4 rollback journal DB, 8 실제 구조 DB, 16 새 폴더 안 파일,
            32 다른 파일과 동시에 쓴 O_DIRECT 파일
      dir   원본 상위 폴더 번호 (회차 안에서 1부터, 0 = 모름). 같은 번호 파일은 같은 폴더
      db    실제 구조 DB 면 dbspec 이름 (db01..), 아니면 빈칸
  <함수>/rep<k>.ops.csv     t_us,op,file,off,len (시각 순서)
      op 0 R, 1 W(pwrite+sync_file_range), 2 WB, 3 WD(O_DIRECT), 4 FS, 6 UNLINK, 9 FA(atomic commit), 10 WX(atomic Write),
         11 CP, 13 DS(폴더 fsync), 15 SQL, 16 SYNC, 17 RENAME, 18 TOUCH
      SQL: file = DB 파일 번호, off 아래 32bit = page 수, 위 32bit = 서로 다른 page 수, len = 종류(1 WAL+checkpoint,
           2 WAL sync, 3 WAL 쓰기만, 4 rollback) | 0x10(DB 다시 열기)
  dbspec/db<NN>.json    실제 구조 DB: create(테이블·인덱스·trigger·view CREATE 문), tables(테이블별 행 수·행 크기·
                        insert/update/delete 비율), framesPerOp, opsPerCommit
DB 파일 이름은 계정 이메일이 들어간 것이 있어 db<NN> 번호로만 둔다. 파일 이름·경로는 원래 없다.
"""
import csv
import io
import json
import re
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PRIV = HERE / ".private" / "funcs"
TXT = HERE / "funcs"
FILE = np.dtype([("size", "<u8"), ("fl", "u1")])
REQ = np.dtype([("t", "<u8"), ("op", "u1"), ("f", "<u4"), ("off", "<u8"), ("len", "<u4")])


def read_pack(path):
    b = path.read_bytes()
    assert b[:8] == b"UXFN0001"
    n = struct.unpack("<I", b[8:12])[0]
    h = json.loads(b[12:12 + n])
    reps = {}
    for fid, fn in h["funcs"].items():
        for r in fn["reps"]:
            fs = np.frombuffer(b, FILE, r["nfiles"], r["off"])
            rq = np.frombuffer(b, REQ, r["nreq"], r["off"] + FILE.itemsize * r["nfiles"])
            reps[r["seg"]] = (fs, rq)
    return h, reps


def write_pack(path, meta, blobs):
    """gen_funcs.py 와 같은 방식: off 를 파일 처음 기준으로, json 길이가 안정될 때까지"""
    base = 0
    for _ in range(5):
        sh = json.loads(json.dumps(meta))
        pos = 0
        for fn in sh["funcs"].values():
            for r in fn["reps"]:
                r["off"] = base + pos
                pos += len(blobs[r["seg"]])
        js = json.dumps(sh, ensure_ascii=False, separators=(",", ":")).encode()
        if 12 + len(js) == base:
            break
        base = 12 + len(js)
    with open(path, "wb") as fo:
        fo.write(b"UXFN0001" + struct.pack("<I", len(js)) + js)
        for fn in sh["funcs"].values():
            for r in fn["reps"]:
                fo.write(blobs[r["seg"]])


def export():
    h, reps = read_pack(PRIV / "funcs.bin")
    names = {k: f"db{i + 1:02d}" for i, k in enumerate(sorted(h["specs"]))}
    TXT.mkdir(exist_ok=True)
    for old in TXT.glob("*/*.csv"):
        old.unlink()
    for old in (TXT / "dbspec").glob("*.json"):
        old.unlink()
    (TXT / "dbspec").mkdir(exist_ok=True)
    for k, v in h["specs"].items():
        (TXT / "dbspec" / f"{names[k]}.json").write_text(json.dumps(v, ensure_ascii=False, indent=1) + "\n")
    index = {"format": "uxtest scenario functions v1 (wl/funcs_text.py)", "groups": h["groups"], "funcs": {}}
    for fid, fn in h["funcs"].items():
        d = TXT / fid
        d.mkdir(exist_ok=True)
        index["funcs"][fid] = {"name": fn["name"], "reps": []}
        for k, r in enumerate(fn["reps"], 1):
            fs, rq = reps[r["seg"]]
            dirs = r.get("dirs") or [0] * len(fs)
            dbs = r.get("dbs") or {}
            s = io.StringIO()
            w = csv.writer(s, lineterminator="\n")
            w.writerow(["file", "size", "flags", "dir", "db"])
            for i, f in enumerate(fs):
                w.writerow([i, int(f["size"]), int(f["fl"]), int(dirs[i]) if i < len(dirs) else 0, names.get(dbs.get(str(i)), "")])
            (d / f"rep{k}.files.csv").write_text(s.getvalue())
            s = io.StringIO()
            s.write("t_us,op,file,off,len\n")
            for x in rq.tolist():
                s.write(f"{x[0]},{x[1]},{x[2]},{x[3]},{x[4]}\n")
            (d / f"rep{k}.ops.csv").write_text(s.getvalue())
            index["funcs"][fid]["reps"].append({"rep": k, "seg": r["seg"], "durSec": r["durSec"], "nfiles": int(len(fs)), "nreq": int(len(rq)),
                                                "hasDirs": "dirs" in r})
    (TXT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {TXT}: 함수 {len(index['funcs'])}개, 회차 {len(reps)}개, DB 구조 {len(names)}개")


def build(out=PRIV / "funcs-from-text.bin"):
    index = json.loads((TXT / "index.json").read_text())
    specs = {p.stem: json.loads(p.read_text()) for p in sorted((TXT / "dbspec").glob("*.json"))}
    meta = {"groups": index["groups"], "funcs": {}, "specs": specs}
    blobs = {}
    for fid, fn in index["funcs"].items():
        meta["funcs"][fid] = {"name": fn["name"], "reps": []}
        for r in fn["reps"]:
            rows = list(csv.DictReader(open(TXT / fid / f"rep{r['rep']}.files.csv")))
            fs = np.array([(int(x["size"]), int(x["flags"])) for x in rows], FILE)
            ops = np.loadtxt(TXT / fid / f"rep{r['rep']}.ops.csv", delimiter=",", skiprows=1, dtype=np.uint64, ndmin=2)
            rq = np.zeros(len(ops), REQ)
            for j, k in enumerate(("t", "op", "f", "off", "len")):
                rq[k] = ops[:, j]
            blobs[r["seg"]] = fs.tobytes() + rq.tobytes()
            e = {"seg": r["seg"], "durSec": r["durSec"], "off": 0, "nfiles": len(fs), "nreq": len(rq)}
            dbs = {x["file"]: x["db"] for x in rows if x["db"]}
            if dbs:
                e["dbs"] = dbs
            if r.get("hasDirs"):
                e["dirs"] = [int(x["dir"]) for x in rows]
            meta["funcs"][fid]["reps"].append(e)
    write_pack(out, meta, blobs)
    print(f"wrote {out}")
    return out


def check():
    out = build()
    ha, ra = read_pack(PRIV / "funcs.bin")
    hb, rb = read_pack(out)
    names = {k: f"db{i + 1:02d}" for i, k in enumerate(sorted(ha["specs"]))}
    bad = []
    if ha["groups"] != hb["groups"]:
        bad.append("groups")
    if {names[k]: v for k, v in ha["specs"].items()} != hb["specs"]:
        bad.append("specs")
    for fid in ha["funcs"]:
        for x, y in zip(ha["funcs"][fid]["reps"], hb["funcs"][fid]["reps"]):
            s = x["seg"]
            if not (np.array_equal(ra[s][0], rb[s][0]) and np.array_equal(ra[s][1], rb[s][1])):
                bad.append(s + " 표")
            if {k: names[v] for k, v in (x.get("dbs") or {}).items()} != (y.get("dbs") or {}) or x.get("dirs") != y.get("dirs") or x["durSec"] != y["durSec"]:
                bad.append(s + " 머리")
    print("같아요" if not bad else f"달라요: {bad[:10]}")
    return not bad


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"export": export, "build": build, "check": check}.get(cmd, lambda: sys.exit(__doc__))()
