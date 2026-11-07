#!/usr/bin/env python3
"""시나리오 함수 TC 검증 결과 → 분석 사이트용 공개 JSON (web/.private/data/tcfunc.json, copy-data.mjs 가 static/data 로 복사)

  python3 wl/export_func_site.py       # report/export_web.py 가 끝에서 부른다

wl/.private 의 funcs.bin·func-matrix.json·가중치 TC 결과에서 공개해도 되는 값만 뽑는다:
  함수별 동작 수·크기(회차 평균), 판정 수와 틀린 항목의 원본·TC 값, 채움 비중, 가중치 TC 의 유형 비중·실행 순서·판정.
파일 이름, DB 테이블 구조·SQL·행 내용은 넣지 않는다. 가중치는 사용자가 준 실행 옵션이라 데이터셋 값이 아니다.
"""
import collections
import glob
import json
import struct
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RES = HERE / ".private" / "results"
OUT = ROOT / "web" / ".private" / "data" / "tcfunc.json"
# 싣는 가중치 TC (이름, 결과 폴더 접두어, 설명). 같은 이름의 가장 최근 결과를 쓴다
MIXES = [("m1", "m1-", "고치기 전"), ("m1w", "m1w-", "DB warm-up"), ("m2", "m2-", "고치기 전"), ("m2w", "m2w-", "DB warm-up"),
         ("m2d", "m2d-", "원본 폴더 구조·시나리오 sync"), ("m2e", "m2e-", "direct Write 하나씩")]


GROUP_KO = {"browser": "브라우저", "sns": "SNS", "video": "동영상", "music": "음악", "maps": "지도", "camera": "카메라",
            "gallery": "갤러리", "mail_store": "메일·스토어", "productivity": "생산성", "launch": "앱 실행",
            "storage": "저장소·파일", "home": "홈", "standby": "대기"}
CHECK_KO = {"readMB": "Read Volume", "writeMB": "Write Volume", "dataWriteMB": "Data Write", "fsWriteMB": "FS Write",
            "fsPct": "FS Write 비율", "flushPerSec": "Flush/s", "fsyncPerSec": "fsync/s", "ckptPerSec": "Checkpoint/s",
            "sizeR": "Request size R", "sizeW": "Request size W", "seqR": "Sequential R", "seqW": "Sequential W",
            "gap": "Inter-arrival", "idlePct": "Idle%", "wakesPerMin": "Wakeups/분", "qdP99": "QD p99",
            "discardMB": "Discard", "gcMB": "GC", "h8PerMin": "h8/분", "h8Pct": "h8%"}
# 유형 색 (TC 타임라인에 나오는 8개 유형만 색을 받는다, 고정 순서)
GROUP_COLOR = {"sns": 0, "video": 1, "camera": 2, "standby": 3, "browser": 4, "launch": 5, "home": 6, "gallery": 7}


def export():
    if not all(p.exists() for p in (RES / "func-matrix.json", HERE / ".private/funcs/funcs.bin", HERE / "groups.json")):
        print("  tcfunc.json: 결과가 없어 지난 파일을 그대로 둬요")
        return
    groups = json.load(open(HERE / "groups.json"))["groups"]
    order = list(groups)
    cat_of = {f: c for c, fs in groups.items() for f in fs}

    # ---- 함수 구조 (funcs.bin)
    d = open(HERE / ".private/funcs/funcs.bin", "rb").read()
    L = struct.unpack("<I", d[8:12])[0]
    meta = json.loads(d[12:12 + L])
    ON = ["R", "W", "WB", "WD", "FS", "", "UNLINK", "TRUNC", "MARK", "FA", "WX", "CP", "TRIM", "DS", "SCREEN", "SQL", "SYNC", "RENAME", "TOUCH"]
    ft = np.dtype([("size", "<u8"), ("flags", "u1")])
    rt = np.dtype([("t", "<u8"), ("op", "u1"), ("file", "<u4"), ("off", "<u8"), ("len", "<u4")])
    struct_rows = {}
    for f, v in meta["funcs"].items():
        agg = collections.Counter()
        n = len(v["reps"])
        dur = nf = rmb = wmb = 0.0
        dbs = set()
        for r in v["reps"]:
            o = r["off"]
            fl = np.frombuffer(d, ft, r["nfiles"], o)
            rq = np.frombuffer(d, rt, r["nreq"], o + fl.nbytes)
            dur += r["durSec"]
            nf += r["nfiles"]
            for op, c in zip(*np.unique(rq["op"], return_counts=True)):
                agg[ON[op]] += int(c)
            rmb += rq["len"][rq["op"] == 0].sum() / 1e6
            wmb += rq["len"][np.isin(rq["op"], [1, 2, 3, 9, 10])].sum() / 1e6
            dbs |= set((r.get("dbs") or {}).values())
        k = lambda x: round(agg[x] / n)
        struct_rows[f] = {"name": v["name"], "reps": n, "dur": round(dur / n), "files": round(nf / n), "rmb": round(rmb / n, 1),
                          "wmb": round(wmb / n, 1), "R": k("R"), "W": k("W") + k("WB"), "WD": k("WD"), "FS": k("FS"),
                          "UN": k("UNLINK"), "RN": k("RENAME"), "AW": k("FA") + k("WX"), "SQL": k("SQL"), "db": len(dbs)}

    # ---- 함수 단독 결과
    cur = json.load(open(RES / "func-matrix.json"))
    full1 = json.load(open(RES / "func-matrix-full1.json"))
    full2 = json.load(open(RES / "func-matrix-full2.json"))


    def fmt(v):
        if isinstance(v, list):
            return "[" + " ".join(f"{x:.0f}" for x in v) + "]"
        if v is None:
            return "-"
        return f"{v:.2f}" if abs(v) < 10 else f"{v:.1f}"


    funcs = []
    for c in order:
        for f in groups[c]:
            r = cur[f]
            fails = [{"k": CHECK_KO.get(k, k), "o": fmt(r["checks"][k]["orig"]), "t": fmt(r["checks"][k]["tc"])} for k in r["fail"]]
            sf = r.get("sqlFrames") or {}
            tot = sf.get("pad", 0) + sf.get("real", 0)
            runs = [f"{x[f]['pass']}/{x[f]['of']}" for x in (full1, full2) if f in x]
            funcs.append({"id": f, "g": c, "gk": GROUP_KO[c], "w": groups[c][f], "p": r["pass"], "n": r["of"], "fails": fails,
                          "pad": round(sf.get("pad", 0) / tot * 100) if tot else None, "prev": runs, "s": struct_rows[f]})

    fail_solo = collections.Counter()
    for r in cur.values():
        fail_solo.update(r["fail"])

    # ---- 가중치 TC
    MIX = []
    for name, pre_, label in MIXES:
        ds = sorted(p for p in glob.glob(str(RES / (pre_ + "2*"))) if (Path(p) / "compare.json").exists())
        if ds:
            MIX.append((name, ds[-1], label))
    mixes = []
    fail_mix = collections.Counter()
    nmix = 0
    for name, path, label in MIX:
        p = RES / Path(path).name
        c = json.load(open(p / "compare.json"))
        m = json.load(open(p / "manifest.json"))
        res = json.load(open(p / "result.json"))
        items = {it["i"]: it for it in c["items"]}
        tl = []
        for x in m["timeline"]:
            it = items.get(x["i"])
            tl.append({"t": round(x["tcStart"]), "d": round(x["srcTo"] - x["srcFrom"]), "g": x["cat"], "f": x["func"], "nm": x["name"],
                       "rep": x["seg"].split("-")[-1], "p": it["pass"] if it else None, "n": it["of"] if it else None})
        solo_exp = sum(cur[x["f"]]["pass"] / cur[x["f"]]["of"] * x["n"] for x in tl if x["n"]) / max(1, sum(x["n"] for x in tl if x["n"]))
        fc = collections.Counter()
        for it in c["items"]:
            for k, v in it["checks"].items():
                if v.get("ok") is False:
                    fc[k] += 1
        if name.endswith("w"):
            fail_mix.update(fc)
            nmix += len(c["items"])
        comp = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0.0]))
        for x in tl:
            comp[x["g"]][x["nm"]][0] += 1
            comp[x["g"]][x["nm"]][1] += x["d"]
        mixes.append({
            "name": name, "label": label, "weight": m["weight"], "seed": m["seed"], "dur": round(m["durSec"]), "n": len(tl),
            "target": {k: round(v * 100, 1) for k, v in m["target"].items()}, "actual": {k: round(v * 100, 1) for k, v in m["actual"].items()},
            "ip": c["itemPass"], "io": c["itemOf"], "solo": round(solo_exp * 100, 1), "tp": c["totalPass"], "to": c["totalOf"],
            "late": c["lateOver5ms"], "req": res.get("requests"), "warms": res.get("sqlWarms"),
            "cats": {k: [v["pass"], v["of"]] for k, v in c["categories"].items()},
            "total": [{"k": CHECK_KO.get(k, k), "o": fmt(v["orig"]), "t": fmt(v["tc"]), "ok": v.get("ok")} for k, v in c["total"].items()],
            "fail": {k: round(v / len(c["items"]) * 100) for k, v in fc.items()},
            "comp": {g: sorted([[nm, a[0], round(a[1] / 60, 1)] for nm, a in fs.items()], key=lambda r: -r[2]) for g, fs in comp.items()},
            "tl": tl,
        })

    # 단독 vs 가중치(warm-up) 항목별 실패율: 같은 구간 목록 기준
    nsolo = 0
    fail_solo_mix = collections.Counter()
    for mx in mixes:
        if not mx["name"].endswith("w"):
            continue
        for x in mx["tl"]:
            if x["n"]:
                nsolo += 1
                fail_solo_mix.update(cur[x["f"]]["fail"])
    checkcmp = sorted(({"k": CHECK_KO.get(k, k), "solo": round(fail_solo_mix[k] / nsolo * 100), "mix": round(fail_mix[k] / nmix * 100)}
                       for k in set(fail_mix) | set(fail_solo_mix)), key=lambda r: (-r["mix"], -r["solo"], r["k"]))

    gsum = []
    for c in order:
        ps = [x for x in funcs if x["g"] == c]
        gsum.append({"g": c, "gk": GROUP_KO[c], "nf": len(ps), "p": sum(x["p"] for x in ps), "n": sum(x["n"] for x in ps)})

    allp = sum(x["p"] for x in funcs)
    alln = sum(x["n"] for x in funcs)
    pad_tot = [0, 0]
    for r in cur.values():
        sf = r.get("sqlFrames") or {}
        pad_tot[0] += sf.get("pad", 0)
        pad_tot[1] += sf.get("pad", 0) + sf.get("real", 0)

    DATA = {"funcs": funcs, "groups": gsum, "mixes": mixes, "checkcmp": checkcmp, "groupKo": GROUP_KO, "groupColor": GROUP_COLOR,
            "allp": allp, "alln": alln, "padPct": round(pad_tot[0] / pad_tot[1] * 100), "failSolo": fail_solo.most_common(8)}
    DATA["failSolo"] = [[CHECK_KO.get(k, k), v] for k, v in DATA["failSolo"]]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(DATA, ensure_ascii=False, separators=(",", ":")))
    print(f"  tcfunc.json: 함수 {len(funcs)}개, 가중치 TC {len(mixes)}개, {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    export()
