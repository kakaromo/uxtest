#!/usr/bin/env python3
"""TC trace 를 원본 UX workload 패턴과 비교 (TC 를 돌릴 때마다 run_tc.py 가 부른다)

  python3 wl/compare.py wl/.private/results/<run>

타임라인 구간마다 원본 조각의 [srcFrom, srcTo) 와 TC trace 의 같은 길이 구간을 metrics.raw 로 재고,
구간별·카테고리별·전체로 합쳐 judge 로 판정한다. 구간이 많으면(하루 TC) 카테고리·전체 표만 출력한다.
결과는 <run>/compare.json, 요약 한 줄은 wl/.private/results/history.jsonl 에 쌓는다.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import metrics as M  # noqa: E402

SEG = HERE / ".private" / "seg"
RES = HERE / ".private" / "results"
REQ = np.dtype([("t", "<u8"), ("op", "u1"), ("f", "<u4"), ("off", "<u8"), ("len", "<u4")])


def load_tc(path):
    b = Path(path).read_bytes()
    nf, _, nr = np.frombuffer(b[8:24], np.dtype([("a", "<u4"), ("b", "<u4"), ("c", "<u8")]))[0]
    return np.frombuffer(b, REQ, count=int(nr), offset=24 + 9 * int(nf))


def align(pq, res, reqs):
    """TC t=0 이 trace 시각으로 언제인지. 재생기가 남긴 시계 값 중 trace 범위에 드는 것을 고르고,
    10ms 칸 R/W 바이트 상호상관으로 ±W초 안에서 맞춘다 (재생기 boottime 과 trace 시각이 몇 초 어긋나는 일이 있다)"""
    lo, hi = M.con.execute(f"select min(time), max(time) from read_parquet('{pq}')").fetchone()
    cands = [c for c in (res["startBoottime"], res["startMonotonic"]) if lo - 5 <= c <= hi]
    if not cands:
        raise SystemExit(f"재생 시작 시각이 trace 범위({lo:.1f}~{hi:.1f})에 없어요: {res['startBoottime']}, {res['startMonotonic']}")
    base = cands[0]
    W = 10
    sel = np.isin(reqs["op"], [0, 1, 3])        # 바로 블록 요청이 되는 R·W·WD
    span = min(reqs["t"][-1] / 1e6, 600)        # 앞 10분으로 충분
    nb = int(span * 100) + 1
    k = (reqs["t"][sel] / 1e4).astype(int)
    ok = k < nb
    want = np.bincount(k[ok], weights=reqs["len"][sel][ok].astype(float), minlength=nb)[:nb]
    got = M.con.execute(f"""select floor((time - {base - W}) * 100)::int k, sum(size) from read_parquet('{pq}')
        where action = 'send_req' and opcode in (40, 136, 42, 138) and time >= {base - W} and time < {base + span + W}
        group by 1""").fetchall()
    g = np.zeros(nb + 200 * W)
    for kk, v in got:
        if 0 <= kk < len(g):
            g[kk] = v
    best = max(range(0, 200 * W), key=lambda s: float(np.dot(want, g[s:s + nb])))
    return base - W + best / 100


def fmt(x):
    return "/".join(f"{y:.0f}" for y in x) if isinstance(x, list) else f"{x:.2f}"


def show(title, j):
    ok = [v[3] for v in j.values() if v[3] is not None]
    print(f"\n{title}  통과 {sum(ok)}/{len(ok)}")
    print(f"  {'항목':12} {'원본':>22} {'TC':>22} {'차이':>7}")
    for k, (o, t, d, okk) in j.items():
        mark = "" if okk is None else ("ok" if okk else "XX")
        print(f"  {k:12} {fmt(o):>22} {fmt(t):>22} {'' if d is None else d:>7} {mark}")
    return sum(ok), len(ok)


def pack(j):
    return {k: {"orig": v[0], "tc": v[1], "d": v[2], "ok": v[3]} for k, v in j.items()}


def main():
    run = Path(sys.argv[1])
    man = json.loads((run / "manifest.json").read_text())
    res = json.loads((run / "result.json").read_text())
    info = json.loads((run / "run.json").read_text())
    pq = info["pq"]
    idx = json.loads((SEG / "index.json").read_text())
    reqs = load_tc(run / "tc.bin")
    T0 = align(pq, res, reqs)
    print(f"TC t=0 → trace {T0:.3f} (재생기 boottime {res['startBoottime']:.3f})")

    # agent 가 보관 폴더 이름을 바꿀 수 있어 경로는 trace ID 로 다시 찾는다
    for v in idx.values():
        v["pq"] = M.extract.parquet_of(v["traceJobId"]) or v["pq"]

    tl = man["timeline"]
    many = len(tl) > 20
    items, by_cat, tot_o, tot_t = [], {}, {}, {}
    t_start = time.time()
    synth = []
    for it in tl:
        if it["seg"] not in idx:                # 합성 구간(DB 동작 등): 원본이 없어 TC 지표만
            L = it["srcTo"] - it["srcFrom"]
            m = M.finish(M.raw(pq, T0 + it["tcStart"], T0 + it["tcStart"] + L))
            synth.append({"i": it["i"], "seg": it["seg"], "synth": it.get("synth"), "tc": m})
            print(f"\n[{it['i']}] {it['seg']} {L:.0f}s (합성, 원본 없음) {it.get('synth')}")
            for k in ("writeMB", "dataWriteMB", "fsWriteMB", "fsPct", "flushPerSec", "fsyncPerSec", "ckptPerSec", "qdP99"):
                print(f"  {k:12} {m[k]:10.2f}")
            continue
        seg = idx[it["seg"]]
        o0 = M.t0(seg["pq"])
        L = it["srcTo"] - it["srcFrom"]
        ro = M.raw(seg["pq"], o0 + it["srcFrom"], o0 + it["srcTo"])
        rt = M.raw(pq, T0 + it["tcStart"], T0 + it["tcStart"] + L)
        cat = it.get("cat", it["seg"])
        co, ct = by_cat.get(cat, ({}, {}))
        by_cat[cat] = (M.add(co, ro), M.add(ct, rt))
        tot_o, tot_t = M.add(tot_o, ro), M.add(tot_t, rt)
        j = M.judge(M.finish(ro), M.finish(rt))
        ok = [v[3] for v in j.values() if v[3] is not None]
        items.append({"i": it["i"], "seg": it["seg"], "cat": cat, "sec": round(L, 1), "pass": sum(ok), "of": len(ok),
                      "checks": pack(j)})
        if not many:
            show(f"[{it['i']}] {it['seg']} {L:.0f}s", j)
    cats = {}
    if many:
        for c, (ro, rt) in sorted(by_cat.items(), key=lambda x: -x[1][0]["dur"]):
            j = M.judge(M.finish(ro), M.finish(rt))
            p, n = show(f"[{c}] {ro['dur'] / 60:.0f}분", j)
            cats[c] = {"pass": p, "of": n, "min": round(ro["dur"] / 60, 1), "checks": pack(j)}
    if tot_o:
        jt = M.judge(M.finish(tot_o), M.finish(tot_t))
        tp, tn = show(f"[전체] {tot_o['dur'] / 60:.0f}분", jt)
    else:
        jt, tp, tn = {}, 0, 0
    npass = sum(x["pass"] for x in items)
    ntot = sum(x["of"] for x in items)
    out = {"run": run.name, "T0": T0, "itemPass": npass, "itemOf": ntot, "totalPass": tp, "totalOf": tn,
           "lateOver5ms": res["lateOver5ms"], "elapsedSec": res["elapsedSec"], "total": pack(jt), "categories": cats, "synth": synth,
           "items": items}
    (run / "compare.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    with open(RES / "history.jsonl", "a") as fo:
        fo.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "run": run.name, "itemPass": npass, "itemOf": ntot,
                             "totalPass": tp, "totalOf": tn, "late": res["lateOver5ms"],
                             "cats": {c: [v["pass"], v["of"]] for c, v in cats.items()},
                             "items": [(x["seg"], x["pass"], x["of"]) for x in items] if not many else None},
                            ensure_ascii=False) + "\n")
    late = 100 * res["lateOver5ms"] / max(1, res["requests"])
    print(f"\n구간별 통과 {npass}/{ntot} ({100 * npass / max(ntot, 1):.0f}%), 전체 {tp}/{tn}, "
          f"늦은 요청(>5ms) {res['lateOver5ms']} ({late:.2f}%), 비교 {time.time() - t_start:.0f}s → {run / 'compare.json'}")


if __name__ == "__main__":
    main()
