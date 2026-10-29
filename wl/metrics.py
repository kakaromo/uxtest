"""원본 trace 와 TC trace 에 똑같이 쓰는 비교 지표. 시간 구간 [a, b) (trace 시각) 만 본다.

report/extract.py 의 trace_metrics 와 같은 정의를 쓰되(방향, 크기 구간, 순차, flow), 구간으로 자르고 더할 수 있게 따로 둔다.
  raw(pq, a, b)  구간의 더할 수 있는 합계 (바이트, 건수, 구간별 건수 …)
  finish(raw)    합계 → 비교 지표. 여러 구간의 raw 를 add 로 더한 뒤 finish 하면 카테고리·전체 지표가 된다.
FS 유발 Write = journal·checkpoint·f2fs meta·GC + fsync 밖의 node write (fsync 안의 node write 는 fsync 로 센다, FSYNC_NODE)
"""
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report"))
import extract  # noqa: E402

QD_MAX = 64
# Checkpoint Write: comm 이 f2fs_ckpt 가 아닌 다른 이름(logd 등)으로 찍히는 trace 가 있어 flag 도 같이 본다
CK = "(coalesce(is_checkpoint, false) or comm like 'f2fs_ckpt%')"
# fsync 안의 node Write. 2026-10-28 이후 fsiotrace 는 FSYNC_TRIGGERED 를 붙이므로 그걸 쓴다.
# 그 전 trace 는 flag 가 늘 0 이라 "커널 문맥이 아닌 node Write" 로 어림한다. 고친 도구는 writeback·checkpoint
# node Write 의 comm 을 주인 앱으로 붙이므로, comm 대신 writeback·checkpoint·GC flag 로 커널 문맥을 가린다.
KERN = ("(comm like 'kworker%' or comm like 'f2fs%' or comm like 'jbd2%' "
        f"or coalesce(is_writeback_kworker or is_gc, false) or {CK})")
NODE = "coalesce(is_f2fs_node_write, false)"
FSYNC_NODE = {True: f"({NODE} and coalesce(is_fsync_triggered, false))", False: f"({NODE} and not {KERN})"}
FS_BASE = "coalesce(is_journal or is_checkpoint or is_f2fs_meta_write or is_gc or is_f2fs_node_gc or is_f2fs_data_gc, false)"

con = duckdb.connect()
_tables = {}
# TC trace 에서 재생기와 커널 문맥만 남기는 조건. 화면 꺼진 TC 동안 폰의 다른 앱(systemui SharedPreferences fsync,
# SettingsProvider, OPPO 서비스 DB 등)이 낸 I/O 는 빼야 한다. 원본 조각은 그때의 다른 앱 I/O 까지 uxwl 이 재생하므로
# 그대로 두면 두 번 센다. Flush(kworker)·Checkpoint·Discard 는 누구 몫인지 나눌 수 없어 남기고, Hibern8 도 못 거른다
TC_ONLY = "(comm = 'uxwl' or comm like 'kworker%' or comm like 'f2fs%' or comm like 'jbd2%')"


def table(pq, only=None):
    """parquet 을 한 번만 읽어 메모리 표로 둔다 (구간을 여러 번 잘라 보므로). only: request 를 거를 조건"""
    key = (pq, only)
    if key not in _tables:
        name = f"t{len(_tables)}"
        has_flag = con.execute(f"select count(*) filter (where is_fsync_triggered) > 0 from read_parquet('{pq}')").fetchone()[0]
        fn = FSYNC_NODE[bool(has_flag)]
        con.execute(f"""create temp table {name} as
            select time, lun, lba, size, least(qd, {QD_MAX}) qd, {extract.DIR} dir,
                   {FS_BASE} or ({NODE} and not {fn}) fsw, {fn} fsync_node, {CK} ck
            from read_parquet('{pq}') where action = 'send_req' and coalesce(is_mgmt, false) = false
            {f"and {only}" if only else ""} order by time""")
        # Hibern8: enter 완료 → 다음 exit 요청 구간 (UFS 관리 명령, 위 표에서는 빠져 있다)
        con.execute(f"""create temp table {name}h as select time, nt from (
            select time, k, lead(time) over (order by time) nt, lead(k) over (order by time) nk from (
              select time, mgmt_name = 'DME_HIBER_ENTER' k from read_parquet('{pq}')
              where (action = 'uic_complete' and mgmt_name = 'DME_HIBER_ENTER') or (action = 'uic_send' and mgmt_name = 'DME_HIBER_EXIT')))
            where k and nk = false""")
        _tables[key] = name
    return _tables[key]


def t0(pq):
    return con.execute(f"select min(time) from read_parquet('{pq}')").fetchone()[0]


def raw(pq, a, b, only=None):
    T = table(pq, only)
    q = lambda s: con.execute(s).fetchall()  # noqa: E731
    w = f"from {T} where time >= {a} and time < {b}"
    r = {"dur": max(b - a, 1e-3)}
    for d, n, by in q(f"select dir, count(*), coalesce(sum(size), 0) {w} group by 1"):
        r[f"n{d}"], r[f"b{d}"] = n, by
    r["fsw"], r["fsyncN"] = q(f"select coalesce(sum(size) filter (where fsw), 0), count(*) filter (where fsync_node) {w} and dir = 'W'")[0]
    for d in "RW":
        r[f"size{d}"] = [0] * 5
        for k, n in q(f"select {extract.size_bucket('size')} k, count(*) {w} and dir = '{d}' group by 1"):
            r[f"size{d}"][k] = n
        r[f"seq{d}"] = q(f"""select coalesce(sum(size) filter (where seq), 0) from (
                select size, lba = lag(lba + size / 4096) over (partition by lun order by time) seq {w} and dir = '{d}')""")[0][0]
    r["qd"] = [0] * (QD_MAX + 1)
    for k, n in q(f"select qd, count(*) {w} and dir in ('R', 'W') group by 1"):
        r["qd"][int(k or 0)] = n
    r["gap"] = list(q(f"""select count(*) filter (where gap < 0.001), count(*) filter (where gap >= 0.001 and gap < 0.016),
                count(*) filter (where gap >= 0.016 and gap < 0.2), count(*) filter (where gap >= 0.2)
                from (select time - lag(time) over (order by time) gap {w} and dir in ('R', 'W'))""")[0])
    r["wakes"] = q(f"select count(*) filter (where gap >= 1) from (select time - lag(time) over (order by time) gap {w})")[0][0]
    r["busy"] = q(f"select count(distinct floor((time - {a}) * 10)) {w} and dir in ('R', 'W')")[0][0]
    # Checkpoint 횟수: f2fs_ckpt Write 묶음 (안쪽 간격 0.2ms 안팎, 사이 2ms 이상)
    r["h8"], r["h8sec"] = q(f"""select count(*), coalesce(sum(least(nt, {b}) - greatest(time, {a})), 0)
        from {T}h where time < {b} and nt > {a}""")[0]
    r["ckpt"] = q(f"select count(*) from (select time - lag(time) over (order by time) g {w} and ck) where g is null or g > 0.001")[0][0]
    return r


def add(x, y):
    out = dict(x)
    for k, v in y.items():
        if isinstance(v, list):
            out[k] = [p + q for p, q in zip(out.get(k, [0] * len(v)), v)]
        else:
            out[k] = out.get(k, 0) + v
    return out


def finish(r):
    g = r.get
    dur = r["dur"]
    rb, wb = g("bR", 0), g("bW", 0)
    pct = lambda a, b: 100 * a / b if b else 0  # noqa: E731
    m = {"durSec": round(dur, 2), "readMB": rb / 1e6, "writeMB": wb / 1e6, "discardMB": g("bD", 0) / 1e6,
         "flushPerSec": g("nF", 0) / dur, "readN": g("nR", 0), "writeN": g("nW", 0),
         "fsWriteMB": r["fsw"] / 1e6, "dataWriteMB": (wb - r["fsw"]) / 1e6, "fsPct": pct(r["fsw"], wb),
         "fsyncPerSec": r["fsyncN"] / dur, "ckptPerSec": r.get("ckpt", 0) / dur}
    for d in "RW":
        n = sum(r[f"size{d}"])
        m[f"size{d}"] = [pct(x, n) for x in r[f"size{d}"]]
        m[f"seq{d}"] = pct(r[f"seq{d}"], g(f"b{d}", 0))
    n = sum(r["qd"])
    acc, m["qdP99"] = 0, 0
    for k, c in enumerate(r["qd"]):
        acc += c
        if n and acc >= 0.99 * n:
            m["qdP99"] = k
            break
    n = sum(r["gap"])
    m["gap"] = [pct(x, n) for x in r["gap"]]
    m["wakesPerMin"] = r["wakes"] / dur * 60
    m["idlePct"] = pct(max(dur * 10 - r["busy"], 0), dur * 10)
    m["h8PerMin"] = r.get("h8", 0) / dur * 60
    m["h8Pct"] = pct(r.get("h8sec", 0), dur)
    return m


def metrics(pq, a, b):
    return finish(raw(pq, a, b))


# 비교 항목: (이름, 종류, 기준). ratio = TC/원본 비율이 1±기준, diff = 차이가 기준 이하, dist = 분포 차이(%p) 가 기준 이하
CHECKS = [
    ("readMB", "ratio", 0.10), ("writeMB", "ratio", 0.10), ("dataWriteMB", "ratio", 0.10),
    ("fsWriteMB", "ratio", 0.20), ("fsPct", "diff", 5.0), ("flushPerSec", "ratio", 0.20), ("fsyncPerSec", "ratio", 0.20),
    ("discardMB", "ratio", 0.20), ("ckptPerSec", "ratio", 0.20),
    ("sizeR", "dist", 15.0), ("sizeW", "dist", 15.0), ("seqR", "diff", 10.0), ("seqW", "diff", 10.0),
    ("gap", "dist", 15.0), ("idlePct", "diff", 5.0), ("wakesPerMin", "ratio", 0.20), ("qdP99", "ratio", 0.5),
    ("h8PerMin", "ratio", 0.20), ("h8Pct", "diff", 5.0),
]
# 판정하지 않고 값만 보여 주는 항목. Discard 는 f2fs 가 idle 때 알아서 내므로 언제 나올지 TC 가 정할 수 없다
# (cal4: 앞 구간에서 지운 파일의 Discard 가 카메라 구간에 652MB, 원본 fstrim 구간 1075MB 는 TC 에서 3MB)
INFO = {"discardMB"}
# 배경 I/O(폰의 다른 앱·시스템) 때문에 생기는 절대 차이는 허용: 이 안이면 비율이 기준을 넘어도 통과
SLACK = {"readMB": "mb", "writeMB": "mb", "dataWriteMB": "mb", "fsWriteMB": "mb", "discardMB": "mb",
         "flushPerSec": 0.5, "fsyncPerSec": 0.5, "ckptPerSec": 0.2, "wakesPerMin": 5.0, "h8PerMin": 5.0}
FLOOR = {"readMB": 1.0, "writeMB": 1.0, "dataWriteMB": 1.0, "fsWriteMB": 0.5, "discardMB": 1.0,
         "flushPerSec": 0.2, "fsyncPerSec": 0.2, "ckptPerSec": 0.05, "wakesPerMin": 2.0, "qdP99": 2}


def judge(orig, tc):
    """항목별 (원본, TC, 차이, 통과). 원본·TC 가 아주 작으면(FLOOR 미만) 판정 안 함(None)"""
    out = {}
    for k, kind, th in CHECKS:
        o, t = orig[k], tc[k]
        if kind == "dist":
            d = sum(abs(x - y) for x, y in zip(o, t)) / 2      # 분포 차이(%p): 옮겨야 하는 비율
            few = (k == "sizeR" and orig["readN"] < 20) or (k == "sizeW" and orig["writeN"] < 20)
            out[k] = (o, t, round(d, 1), None if few else d <= th)
        elif kind == "diff":
            if k == "seqR" and orig["readMB"] < FLOOR["readMB"] or k == "seqW" and orig["writeMB"] < FLOOR["writeMB"]:
                out[k] = (o, t, round(t - o, 1), None)
            else:
                out[k] = (o, t, round(t - o, 1), abs(t - o) <= th)
        else:
            if max(o, t) < FLOOR.get(k, 0) or (k in INFO and not o):
                out[k] = (o, t, None, None)
                continue
            r = t / o if o else float("inf")
            sl = SLACK.get(k, 0)
            sl = max(1.0, 0.5 * orig["durSec"] / 60) if sl == "mb" else sl
            out[k] = (o, t, round(r, 2) if o else None, None if k in INFO else abs(r - 1) <= th or abs(t - o) <= sl)
    return out
