#!/usr/bin/env python3
"""대기 3시간(S5) 배터리 ↔ USB 전원 비교 → web/.private/data/standby-power.json (사이트 /standby-power)

  python3 report/export_standby_power.py

배터리 = runs/S5/<시각>.json 중 FIX_AT 뒤 본 측정, USB = extract.VARIANTS["S5-usb"] (runs/S5/<시각>-usb.json).
지표는 extract.trace_metrics/mgmt_metrics 와 같은 정의를 쓰고, 이 페이지에만 있는 값은 아래에서 센다.
- suspend_stats: run json rawOutput 의 'suspend_<항목>=<값>' 줄 (측정 전·후 두 번) 의 차이. 기록이 없는 측정은 null
- burst: send_req 중 Read/Write/Flush/Discard 를 시간순으로 놓고 1초 이상 빈 곳에서 나눈다. 주기 = burst 시작 간격 중앙값,
  주기 burst = 시작 간격이 주기 ±0.15초인 burst (그 간격을 여는 burst). who = 주기 burst 안 request 의 주체 비율,
  opener = burst 를 연 첫 request 의 주체 비율 (모든 burst). FFT 는 1초 칸 활동 유무의 스펙트럼에서 가장 센 주기
- Auto-Hibern8 (추정): trace 에 명령이 없어서, 모든 이벤트를 시간순으로 놓고 다음 이벤트까지 5ms 이상 빈 곳
  (드라이버 Hibern8 진입 완료 뒤는 뺌) 의 수와 (gap - 5ms) 합. 드라이버 Hibern8 = uic_complete DME_HIBER_ENTER 뒤 gap 합
- 30초 창: 측정 시작(첫 이벤트) + 3600초부터 30초의 send_req 를 종류(F/D/R/C/W)로
공개 데이터라 프로세스 이름은 아래 PROC 에 있는 것만 내보낸다 (나머지는 '기타').
"""
import collections
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

import extract as X

OUT = X.ROOT / "web/.private/data/standby-power.json"
BASE, VARIANT = "S5", "S5-usb"
FULL_SEC = 10000          # 이보다 짧은 측정(10-29, 131분)은 burst 분석에서 뺀다
BURST_GAP, PERIOD_TOL = 1.0, 0.15
AH8_IDLE = 0.005          # auto_hibern8=5000 µs
WIN_FROM, WIN_LEN = 3600, 30
WINDOW = {"battery": "20261111-001224", "usb": "20261110-092253-usb"}   # 30초 그림에 쓰는 측정
SETTINGS = [("auto_hibern8", "5000", "5ms 동안 request 가 없으면 컨트롤러가 스스로 Hibern8 에 들어가요."),
            ("rpm_lvl", "1", "runtime suspend 는 장치 ACTIVE, link Hibern8 (SSU 없음)."),
            ("spm_lvl", "3", "system suspend 는 장치 SLEEP(SSU), link Hibern8. 그래서 SSU 는 system suspend 때만 나가요."),
            ("runtime PM control", "auto", "UFS 장치의 runtime PM 이 켜져 있어요.")]
SUSP = ("success", "fail", "failed_freeze", "failed_suspend")


def proc(c):
    c = c or ""
    for pre, name in (("kworker", "kworker"), ("f2fs_ckpt", "f2fs_ckpt"), ("f2fs_discard", "f2fs_discard"),
                      ("f2fs_gc", "f2fs_gc"), ("dex2oat", "dex2oat"), ("Compiler driver", "dex2oat"),
                      ("vendor.", "제조사 서비스")):
        if c.startswith(pre):
            return name
    return c if c in ("SQL", "NetworkService") else "기타"


def suspend_stats(raw):
    """측정 전·후 suspend_stats 차이. 두 번 다 없으면 None"""
    snaps, cur = [], None
    for line in raw.splitlines():
        m = re.match(r"suspend_(\w+)=(\d+)\s*$", line.strip())
        if not m:
            continue
        if m.group(1) == "success":
            cur = {}
            snaps.append(cur)
        if cur is not None:
            cur[m.group(1)] = int(m.group(2))
    if len(snaps) < 2:
        return None
    a, b = snaps[0], snaps[-1]
    d = {k: b.get(k, 0) - a.get(k, 0) for k in SUSP}
    d["attempt"] = d["success"] + d["fail"]
    return d


def runs():
    out = []
    for f in sorted(X.ROOT.glob(f"runs/{BASE}/2*.json")):
        if X.RUN_NAME.match(f.stem) and f.stem >= X.FIX_AT:
            out.append(("battery", f, json.loads(f.read_text())))
    for rep, f, run, _ in X.variant_runs(VARIANT):
        out.append(("usb", Path(f), run))
    return out


def kind(op, ck, nm, comm):
    if op == 53:
        return "F"
    if op == 66:
        return "D"
    if op in (40, 136):
        return "R"
    if ck or nm or (comm or "").startswith("f2fs"):
        return "C"
    return "W"


def bursts(pq):
    rows = X.q(f"""select time, comm, opcode, coalesce(is_checkpoint,false), coalesce(is_f2fs_node_write or is_f2fs_meta_write,false)
                   from read_parquet('{pq}') where action='send_req' and opcode in (40,42,136,138,53,66) order by time""")
    t = np.array([r[0] for r in rows])
    gap = np.diff(t)
    starts = np.r_[0, np.where(gap >= BURST_GAP)[0] + 1]
    ends = np.r_[starts[1:] - 1, len(t) - 1]
    nreq, bdur, ibi = ends - starts + 1, t[ends] - t[starts], np.diff(t[starts])
    dur = t[-1] - t[0]
    p50 = float(np.median(ibi))
    per = np.where(np.abs(ibi - p50) <= PERIOD_TOL)[0]      # 주기 간격을 여는 burst
    sel = np.zeros(len(starts), bool)
    sel[per] = True
    bid = np.repeat(np.arange(len(starts)), nreq)
    comp, who = collections.Counter(), collections.Counter()
    for i, r in enumerate(rows):
        if sel[bid[i]]:
            k = kind(r[2], r[3], r[4], r[1])
            # Write 는 Checkpoint 와 node·meta 를 나눠 센다 (C 안을 다시 나눔)
            comp[{"C": "CK" if r[3] else ("NM" if r[4] else "FC")}.get(k, k)] += 1
            who[proc(r[1])] += 1
    b = np.bincount((t - t[0]).astype(int))
    b = (b > 0).astype(float)
    b -= b.mean()
    sp = np.abs(np.fft.rfft(b)) ** 2
    fr = np.fft.rfftfreq(len(b), 1)
    m = (fr > 1 / 600) & (fr < 0.5)
    np_ = max(len(per), 1)
    return {"n": len(starts), "perMin": len(starts) / dur * 60, "ibiP50": p50, "ibiP90": float(np.percentile(ibi, 90)),
            "period": round(float(1 / fr[m][np.argmax(sp[m])]), 2), "periodPct": 100 * len(per) / len(ibi),
            "reqP50": float(np.median(nreq)), "reqP90": float(np.percentile(nreq, 90)),
            "durP50": float(np.median(bdur)),
            "comp": {k: round(comp.get(k, 0) / np_, 2) for k in ("F", "CK", "NM", "FC", "D", "W", "R")},
            "who": top(who), "opener": top(collections.Counter(proc(rows[i][1]) for i in starts))}


def top(c, n=4):
    """[[이름, 비율 %]] 상위 n 개. 이름은 proc() 로 줄인 것만, '기타' 는 뺀다"""
    tot = max(sum(c.values()), 1)
    return [[k, round(100 * v / tot, 1)] for k, v in c.most_common() if k != "기타"][:n]


def hibern8(pq):
    """Auto-Hibern8 추정과 드라이버 Hibern8, 드라이버 Hibern8 한 번 머문 시간 중앙값"""
    a = X.q(f"""with e as (select time, action, mgmt_name, lead(time) over (order by time) - time g from read_parquet('{pq}')),
                 s as (select *, action='uic_complete' and mgmt_name='DME_HIBER_ENTER' sw from e)
               select count(*) filter (where g>={AH8_IDLE} and not sw), coalesce(sum(g-{AH8_IDLE}) filter (where g>={AH8_IDLE} and not sw),0),
                      count(*) filter (where g>=0.1 and not sw), count(*) filter (where sw), coalesce(sum(g) filter (where sw),0) from s""")[0]
    dwell = X.q(f"""select quantile_cont(nt-time,0.5) filter (where k='in' and nk='out') from
        (select time,k,lead(time) over (order by time) nt, lead(k) over (order by time) nk from
         (select time, case when mgmt_name='DME_HIBER_ENTER' then 'in' else 'out' end k from read_parquet('{pq}')
          where (action='uic_complete' and mgmt_name='DME_HIBER_ENTER') or (action='uic_send' and mgmt_name='DME_HIBER_EXIT')))""")[0][0]
    return {"ah8": a[0], "ah8Sec": a[1], "ah8Long": a[2], "swh8": a[3], "swh8Sec": a[4], "dwellP50": dwell}


def window(pq):
    t0 = X.q(f"select min(time) from read_parquet('{pq}')")[0][0] + WIN_FROM
    ev = [[round(t - t0, 4), kind(op, ck, nm, c)] for t, op, ck, nm, c in X.q(
        f"""select time, opcode, coalesce(is_checkpoint,false), coalesce(is_f2fs_node_write or is_f2fs_meta_write,false), comm
            from read_parquet('{pq}') where action='send_req' and opcode in (40,42,136,138,53,66)
              and time >= {t0} and time < {t0 + WIN_LEN} order by time""")]
    return {"from": WIN_FROM, "len": WIN_LEN, "ev": ev, "n": len(ev), "kinds": dict(collections.Counter(k for _, k in ev))}


def main():
    out, win = [], {}
    usb_n = 0
    for power, f, run in runs():
        res = run["results"][0]
        tj = sorted(res["traceJobs"], key=lambda x: x["repeatIndex"])[0]
        pq = X.parquet_of(tj["traceJobId"])
        if not pq:
            print(f"  ! parquet 없음 {f.name}")
            continue
        m = X.trace_metrics(pq, 2**40)
        dur = m["durSec"]
        start = datetime.strptime(f.stem[:15], "%Y%m%d-%H%M%S") - timedelta(seconds=run.get("elapsedSec") or 0)
        label = f"{'배터리' if power == 'battery' else 'USB'} {start:%m-%d}"
        wmb = dict(X.q(f"""select comm, sum(size)/1e6 from read_parquet('{pq}') where action='send_req' and opcode in (42,138)
                           group by 1"""))
        by = collections.Counter()
        for c, v in wmb.items():
            by[proc(c)] += v
        ssu = X.q(f"select count(*) from read_parquet('{pq}') where opcode=27 and action='send_req'")[0][0]
        if power == "usb":
            usb_n += 1
        link = {"id": VARIANT, "repeat": usb_n} if power == "usb" else (
            {"id": BASE, "repeat": 1} if f == Path(X.scenario_info(BASE)[2]) else None)
        r = {"label": label, "power": power, "start": f"{start:%Y-%m-%d}", "durSec": dur, "link": link,
             "suspend": suspend_stats(res.get("rawOutput", "")),
             "readMB": m["readMB"], "writeMB": m["writeMB"], "discardMB": m["discardMB"], "flushN": m["flushN"],
             "readN": m["readN"], "writeN": m["writeN"], "wakesPerMin": m["wakesPerMin"],
             "h8PerMin": m["h8PerMin"], "h8Pct": m["h8Pct"], "h8EnterMs": m["h8EnterMs"], "h8ExitMs": m["h8ExitMs"],
             "ufsSuspend": m["suspendN"], "ssu": ssu,
             "ckptMB": by["f2fs_ckpt"], "gcMB": by["f2fs_gc"], "dexMB": by["dex2oat"],
             "size4k": {d: m["size"][d][0] for d in "RW"}, "seq": m["seq"], "dtocP50": m["dtocP50"], "dtocP99": m["dtocP99"],
             "qdP99": m["qdP99"], "gap1ms": m["gap"][0], "ctod0": m["ctod"][0], "ctod200": m["ctod"][4], "syncPct": m["syncPct"]}
        r |= hibern8(pq)
        r["burst"] = bursts(pq) if dur >= FULL_SEC else None
        if f.stem in WINDOW.values():
            win[power] = {"label": label} | window(pq)
        out.append(r)
        b = r["burst"] or {}
        print(f"  {label}: {dur / 60:.0f}분 suspend={r['suspend'] and r['suspend']['attempt']} burst간격={b.get('ibiP50', 0):.2f}초 "
              f"주기비율={b.get('periodPct', 0):.0f}% Flush/분={r['flushN'] / dur * 60:.0f}")
    order = {"battery": 0, "usb": 1}
    out = sorted(out, key=lambda r: (order[r["power"]], [-int(x) for x in r["start"].split("-")]))   # 같은 전원 안에서 최근 것 먼저
    doc = {"generated": datetime.now().isoformat(timespec="minutes"), "scenario": BASE, "variant": VARIANT,
           "settings": [{"k": k, "v": v, "note": n} for k, v, n in SETTINGS],
           "params": {"burstGapSec": BURST_GAP, "periodTolSec": PERIOD_TOL, "ah8IdleMs": AH8_IDLE * 1000},
           "runs": out, "window": win}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), default=float))
    print(f"wrote {OUT} ({len(out)}개 측정)")


if __name__ == "__main__":
    main()
