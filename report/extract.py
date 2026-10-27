#!/usr/bin/env python3
"""runs/ 의 본 측정 결과 + agent archive 의 fsio_ufs parquet → report/data.json

  python3 report/extract.py            # 시나리오마다 가장 최근 본 측정(dry 아님) 사용
  python3 report/extract.py S          # S 로 시작하는 시나리오만 다시 뽑아 기존 data.json 에 합친다

trace 1개 = 표본 1개. 시나리오 값은 3회 median(+최소·최대). G 는 1회차 cold / 2·3회차 warm 을 따로 낸다.

판정 기준
- 방향은 SCSI opcode 로 정한다 (READ 0x28/0x88, WRITE 0x2A/0x8A, UNMAP 0x42, SYNC CACHE 0x35).
  is_read 플래그는 write 요청에도 켜져 있는 경우가 많아 쓰지 않는다.
- 지연(dtoc, ms)은 complete_rsp 행에만 있다.
- LBA 는 4KB 단위. 순차 = 같은 LUN·같은 방향의 직전 요청 끝 LBA 에서 바로 이어짐.
- 메타데이터 = f2fs node·meta·checkpoint·journal 플래그. is_metadata 는 카메라 데이터 write 에도 켜져 있어 쓰지 않는다.
- 파일 이름(name) 귀속은 검증되지 않았다 (작은 파일에 수백 MB 가 붙는 사례) → 리포트에 '확인 중'.
"""
import csv
import glob
import json
import os
import re
import statistics as st
import subprocess
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ARCHIVE = Path.home() / ".agent-standalone/archive/jobs"
TP = next(iter(glob.glob(str(Path.home() / ".local/share/perfetto/prebuilts/trace_processor_shell-*"))), None)
SERIAL = os.environ.get("UX_SERIAL", "3C1677001HN00000")

TYPES = {"A": "앱 실행·전환", "B": "웹·피드 탐색", "C": "미디어 재생", "D": "카메라",
         "E": "파일·저장공간", "F": "생산성", "G": "갤러리 1000장", "S": "대기(standby)"}
# 1회차를 cold 로 따로 내는 시나리오 (직전에 NASA 세트를 새 이름으로 다시 넣었다). G4·G5·G6 는 warm 세트에서 시작한다
COLD_FIRST = {"G1", "G2", "G3"}
SIZE_B = ["4K", "8–16K", "20–128K", "132–512K", ">512K"]
DTOC_B = ["<0.1ms", "0.1–0.5", "0.5–1", "1–5", "≥5ms"]
GAP_B = ["<1ms", "1–16ms", "16–200ms", "≥200ms"]
FLOW_B = ["앱 직접(buffered)", "커널 writeback", "fsync 유발", "메타데이터·노드", "GC", "기타"]
LBA_BINS, T_BINS = 48, 60

con = duckdb.connect()


def size_bucket(col):
    return (f"case when {col}<=4096 then 0 when {col}<=16384 then 1 when {col}<=131072 then 2 "
            f"when {col}<=524288 then 3 else 4 end")


DIR = "case when opcode in (40,136) then 'R' when opcode in (42,138) then 'W' when opcode=66 then 'D' when opcode=53 then 'F' else 'X' end"


def q(sql, *a):
    return con.execute(sql, a).fetchall()


def parquet_of(tid):
    hits = glob.glob(str(ARCHIVE / "*" / "trace" / tid / "result_fsio_ufs.parquet"))
    return hits[0] if hits else None


def pct(a, b):
    return round(100 * a / b, 1) if b else 0.0


def trace_metrics(pq, lba_max):
    con.execute(f"""create or replace temp view ev as
        select time, lun, lba, size, qd, dtoc, pid, tid, comm, name, action, {DIR} as dir,
               is_req_sync, is_fsync_triggered, is_metadata, is_journal, is_checkpoint, is_f2fs_node_write,
               is_f2fs_meta_write, is_gc, is_f2fs_node_gc, is_f2fs_data_gc, is_writeback_kworker,
               is_mmap_writeback, is_buffered, is_direct_io
        from read_parquet('{pq}') where coalesce(is_mgmt,false)=false""")
    con.execute("create or replace temp view rq as select * from ev where action='send_req'")
    t0, t1 = q("select min(time), max(time) from ev")[0]
    dur = max(t1 - t0, 1e-3)
    tot = {d: (n, b) for d, n, b in q("select dir, count(*), coalesce(sum(size),0) from rq group by 1")}
    rn, rb = tot.get("R", (0, 0))
    wn, wb = tot.get("W", (0, 0))
    m = {"durSec": round(dur, 1), "readMB": rb / 1e6, "writeMB": wb / 1e6,
         "discardMB": tot.get("D", (0, 0))[1] / 1e6, "flushN": tot.get("F", (0, 0))[0],
         "readN": rn, "writeN": wn}
    m["peakMBs"] = q(f"select coalesce(max(b),0)/1e6 from (select floor(time) s, sum(size) b from rq where dir in ('R','W') group by 1)")[0][0]

    # 크기 분포 (건수 비율)
    m["size"] = {}
    for d in "RW":
        rows = dict(q(f"select {size_bucket('size')} k, count(*) from rq where dir=? group by 1", d))
        n = sum(rows.values())
        m["size"][d] = [pct(rows.get(i, 0), n) for i in range(5)]
    # 순차 비율 (바이트) — 같은 LUN·방향의 직전 요청 끝에서 이어지면 순차
    con.execute("""create or replace temp view sq as select *, lba = lag(lba + size/4096) over (partition by lun, dir order by time) as seq
                   from rq where dir in ('R','W')""")
    m["seq"] = {d: pct(*q("select coalesce(sum(size) filter (where seq),0), coalesce(sum(size),0) from sq where dir=?", d)[0])
                for d in "RW"}
    # 지연 (complete_rsp)
    m["dtoc"], m["dtocP50"], m["dtocP99"] = {}, {}, {}
    for d in "RW":
        r = q(f"""select count(*), quantile_cont(dtoc,0.5), quantile_cont(dtoc,0.99),
                  count(*) filter (where dtoc<0.1), count(*) filter (where dtoc>=0.1 and dtoc<0.5),
                  count(*) filter (where dtoc>=0.5 and dtoc<1), count(*) filter (where dtoc>=1 and dtoc<5),
                  count(*) filter (where dtoc>=5) from ev where action='complete_rsp' and dir=?""", d)[0]
        m["dtocP50"][d], m["dtocP99"][d] = round(r[1] or 0, 3), round(r[2] or 0, 3)
        m["dtoc"][d] = [pct(x, r[0]) for x in r[3:]]
    m["qdP99"] = q("select coalesce(quantile_disc(qd,0.99),0) from rq where dir in ('R','W')")[0][0]
    # 도착 간격
    g = q("""select count(*) filter (where gap<0.001), count(*) filter (where gap>=0.001 and gap<0.016),
             count(*) filter (where gap>=0.016 and gap<0.2), count(*) filter (where gap>=0.2), count(gap)
             from (select time - lag(time) over (order by time) gap from rq where dir in ('R','W'))""")[0]
    m["gap"] = [pct(x, g[4]) for x in g[:4]]
    # 깨어남: 모든 요청(flush·discard 포함) 사이가 1초 이상 비었다가 다시 온 횟수. 대기(S)에서 저장장치가 얼마나 자주 깨는지
    w = q("""select count(*) filter (where gap>=1), coalesce(max(gap),0)
             from (select time - lag(time) over (order by time) gap from rq)""")[0]
    m["wakesPerMin"] = round(w[0] / dur * 60, 1)
    m["maxGapSec"] = round(w[1], 1)
    m["flushPerSec"] = round(m["flushN"] / dur, 1)
    # idle: 요청이 하나도 없는 100ms 칸 비율
    busy = q("select count(distinct floor(time*10)) from rq where dir in ('R','W')")[0][0]
    m["idlePct"] = pct(max(dur * 10 - busy, 0), dur * 10)
    # write 성격 (바이트)
    w = q("""select coalesce(sum(size) filter (where is_req_sync),0),
                    coalesce(sum(size) filter (where is_fsync_triggered),0),
                    coalesce(sum(size) filter (where is_journal or is_checkpoint or is_f2fs_node_write or is_f2fs_meta_write),0)
             from rq where dir='W'""")[0]
    m["syncPct"], m["fsyncPct"], m["metaPct"] = (pct(x, wb) for x in w)
    flow = q("""select case when is_gc or is_f2fs_node_gc or is_f2fs_data_gc then 4
                       when is_journal or is_checkpoint or is_f2fs_node_write or is_f2fs_meta_write then 3
                       when is_fsync_triggered then 2
                       when is_writeback_kworker or comm like 'kworker%' then 1
                       when is_buffered or is_mmap_writeback or is_direct_io then 0 else 5 end k, sum(size)
                from rq where dir='W' group by 1""")
    fl = dict(flow)
    m["flow"] = [pct(fl.get(i, 0), wb) for i in range(6)]
    # 시간 지역성: 이미 읽은 LBA 를 다시 읽은 바이트
    m["rereadPct"] = pct(q("""select coalesce(sum(size) filter (where rn>1),0) from
                              (select size, row_number() over (partition by lun, lba order by time) rn from rq where dir='R')""")[0][0], rb)
    # 상위 IO stream: 방향 × 크기 × 순차/랜덤
    tb = rb + wb
    m["streams"] = [{"dir": d, "size": SIZE_B[k], "seq": "SEQ" if s else "RND", "pct": pct(b, tb)}
                    for d, k, s, b in q(f"""select dir, {size_bucket('size')} k, coalesce(seq,false) s, sum(size) b
                                              from sq group by all order by b desc limit 5""")]
    # 시간축 (1초)
    nsec = int(dur) + 1
    tl = {"R": [0.0] * nsec, "W": [0.0] * nsec}
    for d, s, b in q("select dir, cast(floor(time-?) as int), sum(size) from rq where dir in ('R','W') group by all", t0):
        if 0 <= s < nsec:
            tl[d][s] = round(b / 1e6, 2)
    m["timeline"] = {"readMBs": tl["R"], "writeMBs": tl["W"]}
    # LBA 맵 (LUN 0, 시간 60칸 × LBA 48칸, 바이트)
    cells = q(f"""select least(cast((time-?)/? * {T_BINS} as int), {T_BINS - 1}) tb,
                         least(cast(lba::double/? * {LBA_BINS} as int), {LBA_BINS - 1}) lb, dir, sum(size)/1e6
                  from rq where lun=0 and dir in ('R','W') group by all""", t0, dur, lba_max)
    m["lba"] = [[a, b, d, round(v, 3)] for a, b, d, v in cells]
    # 프로세스 (pid=tgid). 이름은 나중에 붙인다
    m["procs"] = [{"pid": p, "main": mc, "threads": th, "readMB": r / 1e6, "writeMB": w / 1e6}
                  for p, mc, th, r, w in q("""select pid, max(comm) filter (where tid=pid),
                       string_agg(distinct comm, ',' order by comm), coalesce(sum(size) filter (where dir='R'),0),
                       coalesce(sum(size) filter (where dir='W'),0) from rq where dir in ('R','W')
                       group by pid order by sum(size) desc limit 10""")]
    m["comms"] = [{"comm": c, "readMB": r / 1e6, "writeMB": w / 1e6} for c, r, w in q(
        """select comm, coalesce(sum(size) filter (where dir='R'),0), coalesce(sum(size) filter (where dir='W'),0)
           from rq where dir in ('R','W') group by 1 order by sum(size) desc limit 10""")]
    # 파일 (귀속 미검증)
    m["files"] = [{"name": n, "readMB": r / 1e6, "writeMB": w / 1e6, "lbaSpan": sp, "n": c} for n, r, w, sp, c in q(
        """select coalesce(nullif(name,''),'(이름 없음)'), coalesce(sum(size) filter (where dir='R'),0),
                  coalesce(sum(size) filter (where dir='W'),0), count(distinct lba), count(*)
           from rq where dir in ('R','W') group by 1 order by sum(size) desc limit 10""")]
    m["t0"], m["t1"] = t0, t1
    m |= mgmt_metrics(pq, dur)
    return m


def mgmt_metrics(pq, dur):
    """UFS 관리 명령(is_mgmt): Hibern8 진입·해제(UIC), Query 요청(속성·플래그·디스크립터), 예외 이벤트.
    upiu_response 는 일반 명령의 응답 UPIU 라 뺀다. dtoc 는 ms"""
    con.execute(f"""create or replace temp view mg as select time, action, mgmt_name n, dtoc
        from read_parquet('{pq}') where coalesce(is_mgmt,false) and mgmt_name <> 'upiu_response'""")
    m = {}
    # Hibern8 시간: 진입 완료 → 다음 해제 요청
    h = q("""select count(*) filter (where k='in'),
                    coalesce(sum(nt - time) filter (where k='in' and nk='out'), 0)
             from (select time, k, lead(time) over (order by time) nt, lead(k) over (order by time) nk
                   from (select time, case when n='DME_HIBER_ENTER' then 'in' else 'out' end k from mg
                         where (action='uic_complete' and n='DME_HIBER_ENTER') or (action='uic_send' and n='DME_HIBER_EXIT')))""")[0]
    m["h8PerMin"] = round(h[0] / dur * 60, 1)
    m["h8Pct"] = pct(h[1], dur)
    lat = dict(q("select n, quantile_cont(dtoc,0.5) from mg where action='uic_complete' group by 1"))
    m["h8ExitMs"] = round(lat.get("DME_HIBER_EXIT") or 0, 3)
    m["h8EnterMs"] = round(lat.get("DME_HIBER_ENTER") or 0, 3)
    qq = q("""select count(*) filter (where action='upiu_query_req'),
                     count(*) filter (where action='upiu_query_req' and n like '%bBackgroundOpStatus%'),
                     count(*) filter (where action='upiu_query_req' and n like '%dCurrentWBBufSize%'),
                     count(*) filter (where action='upiu_query_req' and n like 'Clear Flag(fBackgroundOpsEn)%'),
                     count(*) filter (where action='exception'),
                     quantile_cont(dtoc,0.5) filter (where action='upiu_query_rsp'),
                     quantile_cont(dtoc,0.99) filter (where action='upiu_query_rsp') from mg""")[0]
    m["queryPerMin"], m["bkopsPerMin"], m["wbCheckPerMin"] = (round(x / dur * 60, 1) for x in qq[:3])
    m["suspendN"], m["exceptionN"] = qq[3], qq[4]
    m["queryMsP50"], m["queryMsP99"] = round(qq[5] or 0, 3), round(qq[6] or 0, 3)
    # 이름별 건수 (요청 쪽만: Query 요청·UIC 보냄·예외)
    m["mgmtN"] = dict(q("select n, count(*) from mg where action in ('upiu_query_req','uic_send','exception') group by 1"))
    return m


def file_kind(n):
    n = n.lower()
    for k, pat in [("DB", r"\.db$|\.sqlite"), ("WAL·journal", r"-wal$|-shm$|-journal$"),
                   ("APK·so·odex", r"\.(apk|so|odex|vdex|oat|art|dex|jar|prof)$"),
                   ("사진·영상", r"\.(jpe?g|heic|png|mp4|webp)$|camera_process"), ("캐시", r"cache"),
                   ("이름 없음", r"^\(이름 없음\)$")]:
        if re.search(pat, n):
            return k
    return "기타"


def pid_names():
    """지금 살아 있는 프로세스: pid → (이름, 시작 시각 boot 초). 측정 뒤 재사용된 pid 를 거르려고 시작 시각을 같이 둔다."""
    try:
        out = subprocess.run(["adb", "-s", SERIAL, "shell", "cat /proc/uptime; ps -A -o PID,ELAPSED,NAME"],
                             capture_output=True, text=True, timeout=20).stdout.splitlines()
    except Exception:
        return {}
    if not out:
        return {}
    up = float(out[0].split()[0])
    res = {}
    for l in out[2:]:
        f = l.split(None, 2)
        if len(f) == 3 and f[0].isdigit():
            d, _, hms = f[1].rpartition("-")
            sec = sum(int(x) * 60 ** i for i, x in enumerate(reversed(hms.split(":")))) + int(d or 0) * 86400
            res[int(f[0])] = (f[2].strip(), up - sec)
    return res


def proc_name(p, ps, t0):
    """지금 ps 이름은 trace 시작 전부터 살아 있던 프로세스일 때만 쓴다 (pid 재사용 방지). 아니면 스레드 이름으로."""
    th = [t for t in (p["threads"] or "").split(",") if t]
    if ps and ps[1] <= t0:
        return ps[0]
    pkg = next((t for t in th if "." in t and not t.startswith(("binder", "kworker"))), None)
    return pkg or p["main"] or (th[0] if th else str(p["pid"]))


def gfx(path):
    t = Path(path).read_text()
    g = lambda pat: (lambda mm: mm.group(1) if mm else None)(re.search(pat, t))
    return {"frames": int(g(r"Total frames rendered: (\d+)") or 0),
            "janky": int(g(r"Janky frames: (\d+)") or 0),
            "jankyLegacy": int(g(r"Janky frames \(legacy\): (\d+)") or 0),
            "p50": int(g(r"50th percentile: (\d+)ms") or 0), "p90": int(g(r"90th percentile: (\d+)ms") or 0),
            "p99": int(g(r"99th percentile: (\d+)ms") or 0),
            "slowBitmap": int(g(r"Slow bitmap uploads: (\d+)") or 0),
            "deadlineMissed": int(g(r"Number Frame deadline missed: (\d+)") or 0)}


def tp_query(trace, sql):
    out = subprocess.run([TP, "query", trace, sql], capture_output=True, text=True, timeout=600).stdout
    rows = list(csv.reader(out.splitlines()))
    return rows[1:] if rows else []


def frames(trace, pkg="com.oneplus.gallery"):
    """FrameTimeline 의 갤러리 프레임 (ts ns, dur ns, jank_type)."""
    rows = tp_query(trace, f"""select a.ts, a.dur, a.jank_type from actual_frame_timeline_slice a join process p using(upid)
                               where p.name='{pkg}' order by a.ts""")
    return [(int(a) / 1e9, int(b) / 1e9, c) for a, b, c in rows]


def jank_io(fr, pq, app_pid):
    """jank 프레임과 정상 프레임 구간의 갤러리 read 비교. fsio time 과 perfetto ts 모두 boot clock 초.

    jank = FrameTimeline jank_type 에 'App Deadline Missed' 가 들어 있는 프레임 (앱이 마감을 놓친 것).
    Buffer Stuffing·Unknown·Display HAL 은 앱 밖 원인이라 types 에만 센다."""
    con.execute("create or replace temp table fr(ts double, dur double, j boolean)")
    con.executemany("insert into fr values (?,?,?)", [(a, b, "App Deadline Missed" in c) for a, b, c in fr])
    con.execute(f"""create or replace temp view ar as select time, size, dtoc, action from read_parquet('{pq}')
                    where pid={app_pid} and opcode in (40,136)""")
    out = {}
    for j in (True, False):
        r = q("""select count(*), sum(nr), sum(mb), avg((nr>0)::int) from (
                   select f.ts, count(a.time) nr, coalesce(sum(a.size),0)/1e6 mb from fr f
                   left join ar a on a.action='send_req' and a.time between f.ts - 0.1 and f.ts + f.dur
                   where f.j=? group by f.ts)""", j)[0]
        out["jank" if j else "normal"] = {"frames": r[0], "readsPerFrame": round((r[1] or 0) / max(r[0], 1), 2),
                                          "mbPerFrame": round((r[2] or 0) / max(r[0], 1), 3),
                                          "withReadPct": round(100 * (r[3] or 0), 1)}
    dur = sorted(b for _, b, _ in fr)
    out["frameDurP50"] = round(1e3 * dur[len(dur) // 2], 2) if dur else 0
    out["frameDurP99"] = round(1e3 * dur[int(len(dur) * 0.99)], 2) if dur else 0
    types = {}
    for _, _, c in fr:
        for t in c.split(", "):
            types[t] = types.get(t, 0) + 1
    out["types"] = types
    out["total"] = len(fr)
    # 1초 bin: jank 수 + 갤러리 read MB (시간축 겹침 차트)
    t0 = fr[0][0] if fr else 0
    out["sec"] = [[int(s), int(nj), round(mb or 0, 2)] for s, nj, mb in q(f"""
        with j as (select floor(ts-{t0}) s, sum(j::int) nj from fr group by 1),
             r as (select floor(time-{t0}) s, sum(size)/1e6 mb from ar where action='send_req' group by 1)
        select coalesce(j.s,r.s) s, coalesce(nj,0), mb from j full join r on j.s=r.s where coalesce(j.s,r.s)>=0 order by 1""")]
    return out


def scenario_info(sid):
    p = glob.glob(str(ROOT / "scenarios" / "*" / f"{sid}.scenario.json"))[0]
    sc = json.load(open(p))
    run = sorted(f for f in glob.glob(str(ROOT / "runs" / sid / "*.json")) if not f.endswith("-dry.json"))[-1]
    return sc, json.load(open(run)), run


def checks(raw):
    """rawOutput 에서 회차별 확인 값: 포커스 창, 촬영 수, am start -W 시간."""
    per = {}
    rep = 0
    for line in raw.splitlines():
        mm = re.match(r"=== repeat (\d+)/", line)
        if mm:
            rep = int(mm.group(1))
            continue
        d = per.setdefault(rep, {"focus": None, "captured": None, "launchMs": []})
        if "mCurrentFocus" in line:
            mm = re.search(r"u0 ([^ }]+)", line)
            d["focus"] = mm.group(1) if mm else line.strip()
        elif line.startswith("CAPTURED"):
            d["captured"] = line.split(" ", 1)[1]
        elif line.startswith("TotalTime:"):
            d["launchMs"].append(int(line.split()[1]))
    return {k: v for k, v in per.items() if k}


def med(vals):
    vals = [v for v in vals if v is not None]
    return {"med": st.median(vals), "min": min(vals), "max": max(vals)} if vals else None


def aggregate(ms):
    """여러 회차 지표 → median·범위. 분포는 평균, 시간축·LBA 는 총량 median 회차의 것."""
    out = {}
    for k in ("readMB", "writeMB", "discardMB", "flushN", "durSec", "peakMBs", "qdP99", "syncPct", "fsyncPct",
              "metaPct", "rereadPct", "idlePct", "readN", "writeN", "wakesPerMin", "maxGapSec", "flushPerSec",
              "h8PerMin", "h8Pct", "h8ExitMs", "h8EnterMs", "queryPerMin", "bkopsPerMin", "wbCheckPerMin", "suspendN",
              "exceptionN", "queryMsP50", "queryMsP99"):
        out[k] = med([m[k] for m in ms])
    for k in ("seq", "dtocP50", "dtocP99"):
        out[k] = {d: med([m[k][d] for m in ms]) for d in "RW"}
    for k in ("size", "dtoc"):
        # 그 방향 요청이 없던 회차(전부 0)는 빼고 평균한다
        out[k] = {}
        for d in "RW":
            have = [m[k][d] for m in ms if sum(m[k][d]) > 0] or [m[k][d] for m in ms]
            out[k][d] = [round(st.mean(h[i] for h in have), 1) for i in range(5)]
    out["gap"] = [round(st.mean(m["gap"][i] for m in ms), 1) for i in range(4)]
    # 관리 명령 이름별 건수: 회차 합
    out["mgmtN"] = {}
    for m in ms:
        for k, v in m["mgmtN"].items():
            out["mgmtN"][k] = out["mgmtN"].get(k, 0) + v
    out["flow"] = [round(st.mean(m["flow"][i] for m in ms), 1) for i in range(6)]
    rep = sorted(ms, key=lambda m: m["readMB"] + m["writeMB"])[len(ms) // 2]
    out["rep"] = {k: rep[k] for k in ("timeline", "lba", "streams", "procs", "comms", "files", "repeat")}
    tot = [m["readMB"] + m["writeMB"] for m in ms]
    out["cv"] = round(st.pstdev(tot) / st.mean(tot), 2) if len(tot) > 1 and st.mean(tot) else 0
    return out


def main():
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    ids = sorted({Path(p).name.split(".")[0] for p in glob.glob(str(ROOT / "scenarios/*/*.scenario.json"))
                  if glob.glob(str(ROOT / "runs" / Path(p).name.split(".")[0] / "2*[0-9].json"))})
    # 인자로 유형·ID 접두사를 주면 그것만 다시 뽑고 기존 data.json 의 나머지 행은 그대로 둔다
    if only:
        ids = [i for i in ids if i.startswith(tuple(only))]
    names = pid_names()
    # LBA 축 공통 범위
    pqs = {}
    for sid in ids:
        _, run, _ = scenario_info(sid)
        for tj in run["results"][0].get("traceJobs") or []:
            pqs[tj["traceJobId"]] = parquet_of(tj["traceJobId"])
    lba_max = q("select max(lba) from read_parquet(?) where lun=0", [p for p in pqs.values() if p])[0][0] + 1
    if only:  # LBA 맵 눈금을 기존 행과 맞춘다
        lba_max = max(lba_max, int(json.loads((HERE / "data.json").read_text())["meta"]["lbaMaxGB"] * 2**30 / 4096))

    scen, jank = [], []
    for sid in ids:
        sc, run, runpath = scenario_info(sid)
        res = run["results"][0]
        ck = checks(res.get("rawOutput", ""))
        ms = []
        for tj in sorted(res.get("traceJobs") or [], key=lambda x: x["repeatIndex"]):
            pq = pqs[tj["traceJobId"]]
            if not pq:
                print(f"  ! {sid} parquet 없음 {tj['traceJobId']}")
                continue
            m = trace_metrics(pq, lba_max)
            m["repeat"] = tj["repeatIndex"]
            m["traceJobId"] = tj["traceJobId"]
            m["pq"] = pq
            for p in m["procs"]:
                p["name"] = proc_name(p, names.get(p["pid"]), m["t0"])
            for f in m["files"]:
                f["kind"] = file_kind(f["name"])
            ms.append(m)
            print(f"  {sid} r{m['repeat']}: R {m['readMB']:.0f}MB W {m['writeMB']:.0f}MB {m['durSec']}s")
        desc = sc.get("description", "")
        mm = re.search(r"· P(\d)\]", desc)
        base = {"id": sid, "type": sid[0], "typeName": TYPES[sid[0]], "name": sc.get("name", sid),
                "prio": int(mm.group(1)) if mm else 1,
                "description": desc, "steps": [{"type": s["type"], "label": (s.get("params") or {}).get("label", "")}
                                                for s in sc["steps"]],
                "repeats": len(ms), "elapsedSec": run.get("elapsedSec"), "runFile": os.path.relpath(runpath, ROOT),
                "success": all(x.get("success") for x in run["results"]), "checks": ck,
                "perRun": [{k: m[k] for k in ("repeat", "readMB", "writeMB", "discardMB", "durSec", "traceJobId")}
                           for m in ms]}
        groups = [("cold", [m for m in ms if m["repeat"] == 1]), ("warm", [m for m in ms if m["repeat"] > 1])] \
            if sid in COLD_FIRST else [("warm" if sid[0] == "G" else None, ms)]
        for cache, g in groups:
            if g:
                scen.append(base | {"key": sid + (f"-{cache}" if sid in COLD_FIRST else ""), "cache": cache} | aggregate(g))
        if sid[0] == "G" and TP:
            outdir = Path(runpath[:-5])
            pf = sorted(outdir.glob("*.pftrace"))
            gx = sorted(outdir.glob("ux_gfx_*.txt"))
            for i, m in enumerate(ms):
                fr = frames(str(pf[i])) if i < len(pf) else []
                app = next((int(r[0]) for r in tp_query(str(pf[i]), "select pid from process where name='com.oneplus.gallery'")), None) \
                    if i < len(pf) else None
                j = {"scenario": sid, "repeat": m["repeat"], "cache": "cold" if m["repeat"] == 1 and sid in COLD_FIRST else "warm",
                     "gfx": gfx(gx[i]) if i < len(gx) else None, "appPid": app}
                if fr and app:
                    j |= jank_io(fr, m["pq"], app)
                jank.append(j)
                print(f"  {sid} r{m['repeat']} frames={len(fr)} jank={j.get('jank', {}).get('frames')}")

    meta = {"device": "OnePlus CPH2749", "serial": SERIAL, "trace": "fsiotrace fsio_ufs (eBPF)",
            "lbaMaxGB": round(lba_max * 4096 / 2**30, 1),
            "buckets": {"size": SIZE_B, "dtoc": DTOC_B, "gap": GAP_B, "flow": FLOW_B}}
    for m in scen:
        m.pop("pq", None)
    if only:
        old = json.loads((HERE / "data.json").read_text())
        scen = [m for m in old["scenarios"] if m["id"] not in ids] + scen
        jank = [j for j in old["jank"] if j["scenario"] not in ids] + jank
        meta["lbaMaxGB"] = old["meta"]["lbaMaxGB"]
    (HERE / "data.json").write_text(json.dumps({"meta": meta, "types": TYPES, "scenarios": scen, "jank": jank},
                                               ensure_ascii=False, default=float))
    print(f"wrote {HERE / 'data.json'} ({len(scen)} rows, {len(jank)} jank runs)")


if __name__ == "__main__":
    main()
