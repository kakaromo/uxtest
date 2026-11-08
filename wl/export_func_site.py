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
         ("m2d", "m2d-", "원본 폴더 구조·시나리오 sync"), ("m2e", "m2e-", "direct Write 하나씩"),
         ("m1f", "m1f-", "새 원본 (fdatasync flag)"), ("m2f", "m2f-", "새 원본 (fdatasync flag)"), ("m2g", "m2g-", "구간별 lag 기록"),
         ("m1h", "m1h-", "동시 direct Write 재현"), ("m2h", "m2h-", "동시 direct Write 재현"), ("m2i", "m2i-", "구멍 Read·Read 재시도 고침")]
# 단독 vs 가중치 항목별 실패율에 쓰는 가중치 TC (가장 최근 두 벌). 함수 단독(func-matrix.json)과 같은 원본으로 잰 것이어야 한다
CMP = ("m1h", "m2i")


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
    fail_dir = collections.defaultdict(lambda: [0, 0])  # CMP 가중치 TC 의 틀린 구간: [TC 가 원본보다 적음, 많음]
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
                    if name in CMP and isinstance(v.get("orig"), (int, float)) and isinstance(v.get("tc"), (int, float)):
                        fail_dir[k][v["tc"] > v["orig"]] += 1
        if name in CMP:
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
            "errs": sum((res.get("errorKinds") or {}).values()),
            "cats": {k: [v["pass"], v["of"]] for k, v in c["categories"].items()},
            "total": [{"k": CHECK_KO.get(k, k), "o": fmt(v["orig"]), "t": fmt(v["tc"]), "ok": v.get("ok")} for k, v in c["total"].items()],
            "fail": {k: round(v / len(c["items"]) * 100) for k, v in fc.items()},
            "comp": {g: sorted([[nm, a[0], round(a[1] / 60, 1)] for nm, a in fs.items()], key=lambda r: -r[2]) for g, fs in comp.items()},
            "tl": tl,
        })

    # 단독 vs 가중치(CMP) 항목별 실패율: 같은 구간 목록 기준
    nsolo = 0
    fail_solo_mix = collections.Counter()
    for mx in mixes:
        if mx["name"] not in CMP:
            continue
        for x in mx["tl"]:
            if x["n"]:
                nsolo += 1
                fail_solo_mix.update(cur[x["f"]]["fail"])
    checkcmp = sorted(({"k": CHECK_KO.get(k, k), "solo": round(fail_solo_mix[k] / nsolo * 100), "mix": round(fail_mix[k] / nmix * 100),
                        "lo": fail_dir[k][0], "hi": fail_dir[k][1]}
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
            "allp": allp, "alln": alln, "padPct": round(pad_tot[0] / pad_tot[1] * 100), "failSolo": fail_solo.most_common(8), "cmp": list(CMP)}
    DATA["failSolo"] = [[CHECK_KO.get(k, k), v] for k, v in DATA["failSolo"]]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(DATA, ensure_ascii=False, separators=(",", ":")))
    print(f"  tcfunc.json: 함수 {len(funcs)}개, 가중치 TC {len(mixes)}개, {OUT.stat().st_size / 1024:.0f} KB")

    export_seq(d, meta, cur, cat_of)


# ---- 함수별 동작 순서 (tcseq-<id>.json, /tc/func/<id> 페이지)
# 공개 값만: 파일은 회차 안 번호(f12), DB 는 DB 파일 순서 번호(DB3). 파일 이름·폴더·SQL·테이블 이름은 넣지 않는다.
SEQ_GAP = 0.3  # 이보다 오래 쉬면 묶음을 끊는다 (초)
SEQ_FOLD = 0.05  # 같은 파일·같은 동작이 이 간격 안에 이어지면 한 줄로 접는다 (초)
SEQ_ITEM_BURSTS = 300  # 앞 묶음 몇 개까지 동작 줄을 싣는다
SEQ_ITEM_CAP = 15000  # 회차마다 싣는 동작 줄 상한 (파일 크기)
W_OPS = (1, 2, 9, 10)  # 시간 축 Write (Write·buffered·atomic)
WB_OPS = (1, 2, 3, 9, 10)  # Write 바이트 (direct 포함)


def _steps_of(fid):
    """시나리오 전체 step label 과, 회차(repeat)별 측정 step (s-<id>.json)."""
    labels = []
    ps = glob.glob(str(ROOT / "scenarios" / "*" / f"{fid}.scenario.json"))
    if ps:
        sc = json.load(open(ps[0]))
        labels = [(s.get("params") or {}).get("label") or s.get("type", "") for s in sc.get("steps", [])]
        loops = [{"a": lp["startStep"], "b": lp["endStep"], "n": lp["count"]} for lp in sc.get("loops") or []]
    else:
        loops = []
    sp = ROOT / "web" / ".private" / "data" / f"s-{fid}.json"
    runs = {}
    if sp.exists():
        sd = json.load(open(sp))
        if not labels:
            labels = [s["label"] for s in sd.get("steps", [])]
        for r in sd["runs"]:
            runs[r["repeat"]] = [{"i": s["i"], "label": s["label"], "s": round(s["s"], 2), "e": round(s["e"], 2),
                                  "r": round(s["readMB"], 2), "w": round(s["writeMB"], 2), "n": s["n"]}
                                 for s in r["steps"] if s["type"] not in ("trace_start", "trace_stop")]
        marks = {s["i"]: s["type"] for r in sd["runs"] for s in r["steps"] if s["type"] in ("trace_start", "trace_stop")}
    else:
        marks = {}
    return labels, loops, runs, marks


def _rep_seq(d, r, rep_steps):
    ft = np.dtype([("size", "<u8"), ("fl", "u1")])
    rt = np.dtype([("t", "<u8"), ("op", "u1"), ("f", "<u4"), ("off", "<u8"), ("len", "<u4")])
    fl = np.frombuffer(d, ft, r["nfiles"], r["off"])
    rq = np.frombuffer(d, rt, r["nreq"], r["off"] + fl.nbytes)
    isdb = (fl["fl"] & 2) > 0
    dbnum = np.zeros(len(fl), np.int64)
    dbnum[isdb] = np.arange(1, isdb.sum() + 1)
    pre = ((fl["fl"] & 1) > 0) & ~isdb
    op = rq["op"].astype(np.int64)
    t = rq["t"].astype(np.float64) / 1e6
    fidx = rq["f"].astype(np.int64)
    sql = op == 15
    pages = (rq["off"] & 0xFFFFFFFF).astype(np.int64)
    nbytes = np.where(sql, pages * 4096, rq["len"].astype(np.int64))
    isr = op == 0
    isw = np.isin(op, WB_OPS) | sql
    dur = float(r["durSec"])
    ops = collections.Counter(op.tolist())

    # 시간 축 (10분 넘으면 10초 칸)
    bin_s = 10 if dur > 600 else 1
    nb = max(1, int(np.ceil(max(dur, float(t[-1]) if len(t) else 0) / bin_s)))
    bi = np.minimum((t // bin_s).astype(np.int64), nb - 1)

    def tl(mask, w=None):
        a = np.bincount(bi[mask], weights=None if w is None else w[mask], minlength=nb)
        return a

    mbr = lambda a: [round(float(x) / 1e6, 3) for x in a]
    timeline = {"bin": bin_s, "r": mbr(tl(isr, nbytes)), "w": mbr(tl(np.isin(op, W_OPS), nbytes)), "wd": mbr(tl(op == 3, nbytes)),
                "db": mbr(tl(sql, nbytes)), "fsync": [int(x) for x in tl(op == 4)], "sql": [int(x) for x in tl(sql)]}

    # 묶음
    cuts = np.nonzero(np.diff(t) > SEQ_GAP)[0] + 1 if len(t) else np.array([], np.int64)
    starts = np.concatenate([[0], cuts]) if len(t) else np.array([], np.int64)
    ends = np.concatenate([cuts, [len(t)]]) if len(t) else np.array([], np.int64)
    bursts = []
    nitems = 0
    cut_at = None
    for k, (a, b) in enumerate(zip(starts.tolist(), ends.tolist())):
        oc = collections.Counter(op[a:b].tolist())
        bu = {"s": round(float(t[a]), 3), "e": round(float(t[b - 1]), 3), "ops": {str(o): c for o, c in sorted(oc.items(), key=lambda x: -x[1])},
              "r": int(nbytes[a:b][isr[a:b]].sum()), "w": int(nbytes[a:b][isw[a:b]].sum())}
        # 동작 줄: 같은 op·같은 파일이 50ms 안에 이어지면 접기, SQLite 는 접지 않음
        items = []
        last = None
        for j in range(a, b):
            o = int(op[j])
            fj = int(fidx[j])
            if o == 15:
                items.append([round(float(t[j]), 3), 15, -int(dbnum[fj]) if fj < len(fl) and isdb[fj] else None, int(rq["len"][j] & 0x1F), int(pages[j])])
                last = None
                continue
            tgt = None if o == 16 or fj >= len(fl) else (-int(dbnum[fj]) if isdb[fj] else fj)
            if last is not None and last[1] == o and last[2] == tgt and t[j] - last_t <= SEQ_FOLD:
                last[3] += 1
                last[4] += int(nbytes[j])
                last_t = t[j]
                continue
            last = [round(float(t[j]), 3), o, tgt, 1, int(nbytes[j])]
            last_t = t[j]
            items.append(last)
        bu["ni"] = len(items)
        if cut_at is None and (k >= SEQ_ITEM_BURSTS or nitems + len(items) > SEQ_ITEM_CAP):
            cut_at = k
        if cut_at is None:
            bu["it"] = items
            nitems += len(items)
        bursts.append(bu)

    st = {"dur": round(dur, 1), "files": int((~isdb).sum()), "prefill": int(pre.sum()), "prefillMB": round(float(fl["size"][pre].sum()) / 1e6, 1),
          "dbs": int(isdb.sum()), "ops": {str(o): c for o, c in sorted(ops.items(), key=lambda x: -x[1])}, "n": int(len(op)),
          "rMB": round(float(nbytes[isr].sum()) / 1e6, 1), "wMB": round(float(nbytes[isw].sum()) / 1e6, 1)}
    return {"seg": r["seg"], **st, "tl": timeline, "bursts": bursts, "itemsUpTo": cut_at, "steps": rep_steps}


def export_seq(d, meta, cur, cat_of):
    out = OUT.parent
    sizes = []
    for fid, v in meta["funcs"].items():
        labels, loops, runs, marks = _steps_of(fid)
        reps = []
        for r in v["reps"]:
            repeat = int(r["seg"].split("-")[-1])
            reps.append(_rep_seq(d, r, runs.get(repeat, [])))
        cm = cur.get(fid) or {}
        checks = [{"k": CHECK_KO.get(k, k), "o": c.get("orig"), "t": c.get("tc"), "ok": c.get("ok")} for k, c in (cm.get("checks") or {}).items()]
        doc = {"id": fid, "name": v["name"], "g": cat_of.get(fid), "gk": GROUP_KO.get(cat_of.get(fid), ""), "allSteps": labels, "loops": loops,
               "marks": {str(i): ty for i, ty in marks.items()}, "reps": reps, "checks": checks, "pass": cm.get("pass"), "of": cm.get("of"),
               "checkRep": cm.get("rep"), "gap": SEQ_GAP, "fold": SEQ_FOLD}
        p = out / f"tcseq-{fid}.json"
        p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
        sizes.append((p.stat().st_size, fid))
    sizes.sort()
    print(f"  tcseq-*.json: 함수 {len(sizes)}개, 합 {sum(s for s, _ in sizes) / 1e6:.1f} MB, 가장 큰 것 {sizes[-1][1]} {sizes[-1][0] / 1024:.0f} KB")


if __name__ == "__main__":
    export()
