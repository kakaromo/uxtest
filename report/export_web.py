#!/usr/bin/env python3
"""분석 사이트(web/)용 데이터 → web/.private/data/ (web/scripts/copy-data.mjs 가 static/data 로 복사)

  python3 report/extract.py          # 먼저 data.json (시나리오 집계)
  python3 report/export_web.py       # 회차별 상세 → index.json + s-<ID>.json
  python3 report/export_web.py D1 S  # 일부만 (ID·유형 접두사)

index.json = data.json 의 집계 행(시간축·LBA 같은 큰 배열은 뺌) + meta + jank 요약.
s-<ID>.json = 그 시나리오의 집계 행(G 는 cold/warm 둘) + 회차마다 상세:
  1초 시간축(R/W MB/s, QD, 지연 p99, discard·flush 건수), 100ms 시간축(15분 이하만), 측정 구간 안 스텝별 양,
  크기·QD 구간별 지연 백분위, 느린 요청 상위 30, 파일 종류별 양, 프로세스·스레드·파일 상위.
시간은 모두 그 회차 trace 첫 요청 기준 초.
"""
import json
import sys
from pathlib import Path

import extract as X

OUT = X.ROOT / "web/.private/data"
QD_B = ["1", "2–4", "5–8", "9–16", "17–32", ">32"]
TL100_MAX = 900   # 이보다 긴 회차는 100ms 시간축을 만들지 않는다


def qd_bucket(col):
    return f"case when {col}<=1 then 0 when {col}<=4 then 1 when {col}<=8 then 2 when {col}<=16 then 3 when {col}<=32 then 4 else 5 end"


def series(rows, n, idx=1):
    out = [0] * n
    for r in rows:
        if 0 <= r[0] < n:
            out[r[0]] = round(r[idx] or 0, 3)
    return out


def run_detail(pq, lba_max, steps, names):
    m = X.trace_metrics(pq, lba_max)       # ev / rq / sq 뷰도 여기서 만들어진다
    t0, dur = m["t0"], m["durSec"]
    q = X.q
    n1 = int(dur) + 1
    rw = q("""select cast(floor(time-?) as int) s, sum(size) filter (where dir='R')/1e6, sum(size) filter (where dir='W')/1e6,
                     count(*) filter (where dir='D'), count(*) filter (where dir='F'), max(qd), avg(qd)
              from rq group by 1""", t0)
    lat = q("""select cast(floor(time-?) as int) s, quantile_cont(dtoc,0.99) filter (where dir='R'),
                      quantile_cont(dtoc,0.99) filter (where dir='W')
               from ev where action='complete_rsp' group by 1""", t0)
    tl1 = {"r": series(rw, n1, 1), "w": series(rw, n1, 2), "disc": series(rw, n1, 3), "flush": series(rw, n1, 4),
           "qdMax": series(rw, n1, 5), "qdAvg": series(rw, n1, 6), "p99R": series(lat, n1, 1), "p99W": series(lat, n1, 2)}
    tl100 = None
    if dur <= TL100_MAX:
        n10 = int(dur * 10) + 1
        r10 = q("""select cast(floor((time-?)*10) as int) s, sum(size) filter (where dir='R')/1e6, sum(size) filter (where dir='W')/1e6
                   from rq group by 1""", t0)
        tl100 = {"r": series(r10, n10, 1), "w": series(r10, n10, 2)}   # MB per 100ms

    # 측정 구간 안 스텝 (boot clock 이 있는 스텝만)
    st = []
    for b in steps:
        s, e = b["startedMono"] - t0, b["finishedMono"] - t0
        r = q("""select coalesce(sum(size) filter (where dir='R'),0)/1e6, coalesce(sum(size) filter (where dir='W'),0)/1e6,
                        count(*) filter (where dir in ('R','W'))
                 from rq where time>=? and time<?""", b["startedMono"], b["finishedMono"])[0]
        p = q("select quantile_cont(dtoc,0.99) from ev where action='complete_rsp' and time>=? and time<?",
              b["startedMono"], b["finishedMono"])[0][0]
        st.append({"i": b["stepIndex"], "type": b["type"], "label": b["label"], "s": round(s, 2), "e": round(e, 2),
                   "readMB": round(r[0], 2), "writeMB": round(r[1], 2), "n": r[2], "p99": round(p or 0, 3)})

    def lat_by(bucket_sql, nb):
        out = {}
        for d in "RW":
            rows = {k: v for k, *v in q(f"""select {bucket_sql} k, quantile_cont(dtoc,0.5), quantile_cont(dtoc,0.9),
                                              quantile_cont(dtoc,0.99), count(*)
                                       from ev where action='complete_rsp' and dir=? group by 1""", d)}
            out[d] = [[round(x, 3) for x in rows[i][:3]] + [rows[i][3]] if i in rows else None for i in range(nb)]
        return out

    slow = [{"t": round(t - t0, 3), "dir": d, "kb": sz // 1024, "lba": lba, "lun": lun, "qd": qd, "dtoc": round(dt, 3),
             "comm": c, "file": n or ""}
            for t, d, sz, lba, lun, qd, dt, c, n in q("""select time, dir, size, lba, lun, qd, dtoc, comm, name from ev
                 where action='complete_rsp' and dir in ('R','W') order by dtoc desc limit 30""")]
    kinds = {}
    for n, r, w in q("""select coalesce(nullif(name,''),'(이름 없음)'), coalesce(sum(size) filter (where dir='R'),0),
                               coalesce(sum(size) filter (where dir='W'),0) from rq where dir in ('R','W') group by 1"""):
        k = X.file_kind(n)
        a = kinds.setdefault(k, [0, 0])
        a[0] += r / 1e6
        a[1] += w / 1e6
    for p in m["procs"]:
        p["name"] = names.get(p["pid"]) or X.proc_name(p, None, t0)
    for f in m["files"]:
        f["kind"] = X.file_kind(f["name"])

    keep = ("durSec", "readMB", "writeMB", "discardMB", "flushN", "readN", "writeN", "peakMBs", "qdP99", "metaPct",
            "rereadPct", "idlePct", "wakesPerMin", "maxGapSec", "flushPerSec", "seq", "dtocP50", "dtocP99", "size",
            "dtoc", "gap", "flow", "streams", "procs", "comms", "files", "lba")
    d = {k: m[k] for k in keep}
    d |= {"tl1": tl1, "tl100": tl100, "steps": st, "latSize": lat_by(X.size_bucket("size"), 5),
          "latQd": lat_by(qd_bucket("qd"), 6), "slow": slow,
          "kinds": [{"kind": k, "readMB": round(v[0], 2), "writeMB": round(v[1], 2)}
                    for k, v in sorted(kinds.items(), key=lambda x: -(x[1][0] + x[1][1]))]}
    return d


def slim(row):
    r = {k: v for k, v in row.items() if k != "rep"}
    r["rep"] = {k: row["rep"][k] for k in ("repeat", "streams") if k in row["rep"]}
    r["tl"] = row["rep"]["timeline"]   # 대표 회차 1초 시간축 (유형 페이지 작은 그래프용)
    return r


def content():
    """해설 본문: build_report.py 가 만든 report/site/index.html 에서 숫자가 채워진 문단을 떼어 온다.
    차트 자리(div.chart, figure, 범례)는 빼고 글·표만 남긴다. 사이트가 차트를 따로 그린다."""
    import re
    page = (X.HERE / "site/index.html").read_text()

    def grab(pat):
        m = re.search(pat, page, re.S)
        return m.group(1).strip() if m else ""

    def clean(h):
        h = re.sub(r"<figure.*?</figure>", "", h, flags=re.S)
        h = re.sub(r'<div class="tl-row">.*?</div></div>', "", h, flags=re.S)
        h = re.sub(r'<div class="legend">.*?</div>', "", h, flags=re.S)
        h = re.sub(r'<a class="more-link"[^>]*>.*?</a>', "", h, flags=re.S)
        h = re.sub(r'href="#t-([A-Z])"', r'href="type/\1"', h)
        h = re.sub(r'href="#limits"', 'href="#limits"', h)
        return h.strip()

    c = {"lede": grab(r'<p class="lede">(.*?)</p>'), "byline": grab(r'<p class="byline">(.*?)</p>'),
         "takes": clean(grab(r'<ol class="takes">(.*?)</ol>')),
         "glance": clean(grab(r'<table class="glance">(.*?)</table>')),
         "method": clean(grab(r'<section id="method".*?<div class="prose">(.*?)</div>')),
         "limits": clean(grab(r'<section id="limits".*?<h2[^>]*>.*?</h2>(.*?)</section>')),
         "types": {}}
    for t in X.TYPES:
        art = grab(rf'<article class="type" id="t-{t}">(.*?)</article>')
        if not art:
            continue
        c["types"][t] = {"tag": grab(rf'id="t-{t}">\s*<header><span class="tid">(.*?)</span>'),
                         "title": grab(rf'id="t-{t}">\s*<header>.*?<h3>(.*?)</h3>'),
                         "body": clean(re.sub(r"^\s*<header>.*?</header>", "", art, flags=re.S))}
    return c


def main():
    only = tuple(a for a in sys.argv[1:] if not a.startswith("-"))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "content.json").write_text(json.dumps(content(), ensure_ascii=False))
    D = json.loads((X.HERE / "data.json").read_text())
    lba_max = int(D["meta"]["lbaMaxGB"] * 2**30 / 4096)
    OUT.mkdir(parents=True, exist_ok=True)
    meta = D["meta"] | {"qdBuckets": QD_B, "generated": __import__("datetime").datetime.now().isoformat(timespec="minutes")}
    (OUT / "index.json").write_text(json.dumps(
        {"meta": meta, "types": D["types"], "scenarios": [slim(s) for s in D["scenarios"]],
         "jank": [{k: v for k, v in j.items() if k not in ("series",)} for j in D["jank"]]},
        ensure_ascii=False, separators=(",", ":"), default=float))
    ids = list(dict.fromkeys(s["id"] for s in D["scenarios"]))
    if only:
        ids = [i for i in ids if i.startswith(only)]
    for sid in ids:
        rows = [s for s in D["scenarios"] if s["id"] == sid]
        sc, run, runpath = X.scenario_info(sid)
        res = run["results"][0]
        names = {p["pid"]: p["name"] for r in rows for p in r["rep"]["procs"]}
        runs = []
        for tj in sorted(res.get("traceJobs") or [], key=lambda x: x["repeatIndex"]):
            pq = X.parquet_of(tj["traceJobId"])
            if not pq:
                continue
            steps = [b for b in res.get("stepBoundaries") or []
                     if b["repeatIndex"] == tj["repeatIndex"] and b.get("startedMono")]
            d = run_detail(pq, lba_max, steps, names)
            d |= {"repeat": tj["repeatIndex"], "traceJobId": tj["traceJobId"],
                  "cache": ("cold" if tj["repeatIndex"] == 1 else "warm") if sid in X.COLD_FIRST else rows[0]["cache"]}
            runs.append(d)
        doc = {"id": sid, "rows": [{k: v for k, v in r.items() if k != "rep"} | {"rep": {"repeat": r["rep"]["repeat"]}}
                                   for r in rows],
               "steps": [{"type": s["type"], "label": (s.get("params") or {}).get("label", "")} for s in sc["steps"]],
               "runFile": rows[0]["runFile"], "runs": runs,
               "jank": [j for j in D["jank"] if j["scenario"] == sid]}
        p = OUT / f"s-{sid}.json"
        p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), default=float))
        print(f"  {sid}: {len(runs)}회차 {p.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
