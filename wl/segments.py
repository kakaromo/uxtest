#!/usr/bin/env python3
"""측정 trace(fsio_ufs parquet) → 재생용 파일 동작 조각 (wl/.private/seg/<ID>-<rep>.npz)

  python3 wl/segments.py            # 전체
  python3 wl/segments.py B7t D1     # ID 접두사

블록 요청을 그대로 쓰지 않고, 앱이 한 파일 동작으로 바꾼다. FS(f2fs)가 만드는 I/O 는 재생하지 않고
재생 때 f2fs 가 직접 만들게 둔다 (Metadata/node, Checkpoint, Flush, Discard, GC).

  원본 요청                                   재생 op
  Read                                        R   O_DIRECT pread (원본은 page cache 뒤 요청이라 크기 그대로)
  앱 스레드 node Write (fsync 안에서 나옴)      FS  그 파일 fsync  → node 를 f2fs 가 냄 (fsync_mode=nobarrier 라 Flush 없음)
    └ 바로 뒤(1ms) Checkpoint                  FS  (+ CP) Flush 는 Checkpoint 가 냄. 예: SQLite 가 새 journal 을 fsync 할 때마다
    └ Checkpoint 없이 바로 뒤(3ms) Flush        FA  atomic commit (F2FS_IOC_COMMIT_ATOMIC_WRITE) → node + PREFLUSH|FUA → Flush
  앱 스레드 Data Write, 1초 안에 같은 파일 FS   WB  buffered pwrite (sync 없음, 뒤 fsync 가 내보냄)
    └ 그 fsync 가 FA                           WX  atomic write 안의 pwrite (처음이면 F2FS_IOC_START_ATOMIC_WRITE)
  앱 스레드 Data Write, O_DIRECT               WD  O_DIRECT pwrite
  그 밖의 Data Write (kworker writeback 등)    W   buffered pwrite + sync_file_range(WRITE) 로 바로 내보냄
  Discard                                     DB  반납할 바이트 (gen_tc 가 앞서 쓴 파일 삭제로 바꿈)
  fsync 직후 3ms 안에 Checkpoint 가 왔던 fsync  DS  그 뒤 디렉터리 fsync → f2fs 가 Checkpoint. SQLite 는 새 journal 을 만들면
                                                  디렉터리를 fsync 하고, AtomicFile(.tmp → rename) 도 같은 결과를 낸다
  그 밖의 f2fs_ckpt Checkpoint 묶음 시작        CP  원인을 모르는 Checkpoint (sync·배경). 디렉터리 fsync 로 같은 시각에 일으킴
  잠깐 쓰고 지워진 파일 (아래)                 UL  마지막 접근 직후 unlink → 디렉터리 변경·Discard 를 f2fs 가 만듦
  kworker·f2fs node/meta/Checkpoint/GC, Flush  -   재생 안 함 (f2fs 가 만듦, compare 에서 비교)

파일 offset: f2fs 는 덮어쓰기도 새 LBA 에 쓰므로 LBA 로 offset 을 알 수 없다. inode 별로 건드린 LBA 구간을
LBA 순서로 이어 붙여 offset 을 준다 (구간 안 Sequential 유지). inode 가 없는 요청은 파일 0(scratch).

지워진 파일: trace 에 unlink 는 없다. 새로 만든 파일 중 이름이 -journal·.tmp 로 끝나거나, 같은 이름이 inode 여러 개로
나오면(앞 것이 지워지고 새로 만들어짐) 마지막 접근 직후 지운다. 예: TikTok 은 105초에 ttm_strategy.db-journal 을 inode 1045개로 만들고 지웠다.
"""
import bisect
import json
import os
import re
import sys
from pathlib import Path

import duckdb
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "report"))
import extract  # noqa: E402

SEG = HERE / ".private" / "seg"
OPS = {"R": 0, "W": 1, "WB": 2, "WD": 3, "FS": 4, "DB": 5, "UL": 6, "FA": 9, "WX": 10, "CP": 11, "DS": 13}
FSYNC_WIN = 1.0   # 앱 스레드 Data Write 뒤 이 시간 안에 같은 파일 fsync 가 오면 그 fsync 의 일부
FLUSH_WIN = 0.003  # fsync node write 뒤 이 안에 Flush 가 오면 atomic commit (PREFLUSH|FUA 를 앞뒤 Flush 로 처리)
CKPT_WIN = 0.001   # fsync node write 뒤 이 안에 f2fs_ckpt Write 가 오면 그 fsync 가 Checkpoint 를 부른 것 (새 journal 파일 fsync 등)
APP = "not (comm like 'kworker%' or comm like 'f2fs%' or comm like 'jbd2%')"
TEMP = re.compile(r"(-journal|\.tmp|\.temp)$")

con = duckdb.connect()


def runs():
    """(sid, repeat, traceJobId, parquet) 전부"""
    ids = sorted({p.name.split(".")[0] for p in ROOT.glob("scenarios/*/*.scenario.json")
                  if list((ROOT / "runs" / p.name.split(".")[0]).glob("2*[0-9].json"))})
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    if only:
        ids = [i for i in ids if i.startswith(tuple(only))]
    for sid in ids:
        _, run, _ = extract.scenario_info(sid)
        for tj in sorted(run["results"][0].get("traceJobs") or [], key=lambda x: x["repeatIndex"]):
            pq = extract.parquet_of(tj["traceJobId"])
            if pq:
                yield sid, tj["repeatIndex"], tj["traceJobId"], pq


def build(pq):
    t0, t1 = con.execute(f"select min(time), max(time) from read_parquet('{pq}')").fetchone()
    # 2026-10-28 이후 fsiotrace 는 fsync 안 Write 에 FSYNC_TRIGGERED 를 붙이고, writeback·Checkpoint Write 의 comm 을
    # 주인 앱으로 붙인다. 그래서 comm 만으로는 앱 스레드를 가릴 수 없다 → flag 가 있으면 flag 로 가린다 (metrics.py 와 같은 기준)
    has_flag = con.execute(f"select count(*) filter (where is_fsync_triggered) > 0 from read_parquet('{pq}')").fetchone()[0]
    # is_writeback_kworker 는 fsync 안 Write·O_DIRECT Write 에도 붙는다 → 둘 다 아닌 writeback 만 커널 몫
    app = (f"({APP} and not coalesce(is_checkpoint or is_gc, false) and not (coalesce(is_writeback_kworker, false) "
           f"and not coalesce(is_fsync_triggered or is_direct_io, false)))") if has_flag else APP
    fsn = "coalesce(is_fsync_triggered, false)" if has_flag else app
    rows = con.execute(f"""
        select time - {t0} t, {extract.DIR} dir, lba, size, coalesce(ino, 0) ino, coalesce(tid, 0) tid,
               {app} app, coalesce(is_direct_io, false) dio,
               coalesce(is_journal or is_checkpoint or is_f2fs_meta_write or is_gc or is_f2fs_node_gc or is_f2fs_data_gc, false) fsw,
               coalesce(is_f2fs_node_write, false) node, comm, name, {fsn} fsn, coalesce(is_checkpoint, false) ck
        from read_parquet('{pq}')
        where action = 'send_req' and coalesce(is_mgmt, false) = false
        order by time""").fetchall()

    # 1. 요청 분류
    ev = []  # (t, op, ino, lba, nblk, tid)
    flush = [t for t, d, *_ in rows if d == "F"]
    ckpt = [r[0] for r in rows if (r[10] or "").startswith("f2fs_ckpt") or r[13]]
    names, lastck = {}, -1.0
    for t, d, lba, size, ino, tid, app, dio, fsw, node, comm, name, fsn, ck in rows:
        ino = ino if ino and ino > 1 else 0
        if ino and name and ino not in names:
            names[ino] = os.path.basename(name)
        if (comm or '').startswith('f2fs_ckpt') or ck:
            if t - lastck > 0.001:   # Checkpoint 하나 안의 Write 간격은 0.2ms 안팎, Checkpoint 사이는 2ms 이상
                ev.append([t, 'CP', 0, 0, 0, 0])
            lastck = t
        nb = max(1, (size or 0) // 4096)
        if d == "R":
            ev.append([t, "R", ino, lba, nb, tid])
        elif d == "D":
            ev.append([t, "DB", 0, 0, nb, tid])
        elif d == "W":
            if fsw or (node and not fsn):
                continue                       # f2fs 몫
            if node:                           # fsync 안 node write
                if ino:
                    # 바로 뒤 Checkpoint 가 오면 그 Flush 는 Checkpoint 몫 → 일반 fsync (+ CP). 아니고 Flush 만 따라오면 atomic commit
                    j = bisect.bisect_left(flush, t)
                    k = bisect.bisect_left(ckpt, t)
                    cp_next = k < len(ckpt) and ckpt[k] - t <= CKPT_WIN
                    fl_next = j < len(flush) and flush[j] - t <= FLUSH_WIN
                    ev.append([t, "FA" if fl_next and not cp_next else "FS", ino, 0, 0, tid])
                continue
            ev.append([t, "WD" if (app and dio) else ("WA" if app else "W"), ino, lba, nb, tid])
    # 같은 파일 fsync 가 연달아(같은 fsync 안 node 여러 개) 나오면 하나로. 하나라도 FA 면 FA
    last = {}
    out = []
    for e in ev:
        if e[1] in ("FS", "FA"):
            k = (e[5], e[2])
            if k in last and e[0] - last[k][0] < 0.0003:   # 한 fsync 의 node 여러 개 (WAL 은 0.7ms 마다 따로 fsync)
                if e[1] == "FA":
                    last[k][1][1] = "FA"
                continue
            last[k] = (e[0], e)
        out.append(e)
    ev = out
    # 2. 앱 스레드 Data Write 중 뒤에 같은 tid·파일 fsync 가 FSYNC_WIN 안에 오면 WB(그 fsync 가 FA 면 WX), 아니면 W
    nxt = {}
    for e in reversed(ev):
        k = (e[5], e[2])
        if e[1] in ("FS", "FA"):
            nxt[k] = (e[0], e[1])
        elif e[1] == "WA":
            if k in nxt and nxt[k][0] - e[0] <= FSYNC_WIN:
                e[1] = "WX" if nxt[k][1] == "FA" else "WB"
            else:
                e[1] = "W"

    # 잠깐 쓰고 지워진 파일 → 마지막 접근 직후 UL
    span = {}
    for t, op, ino, *_ in ev:
        if ino and op not in ("DB", "CP"):
            a = span.setdefault(ino, [t, t, op])
            a[1] = t
    byname = {}
    for ino, (a, b, op0) in span.items():
        if op0 != "R" and ino in names:          # 새로 만든 파일만
            byname.setdefault(names[ino], []).append((a, ino))
    for nm, lst in byname.items():
        lst.sort()
        dead = lst if TEMP.search(nm) else lst[:-1]
        for _, ino in dead:
            ev.append([span[ino][1] + 0.0005, "UL", ino, 0, 0, 0])
    ev.sort(key=lambda e: e[0])

    # DB 동작: SQLite rollback journal transaction. 새 journal 의 첫 fsync 뒤 디렉터리 fsync(DS) 를 넣고,
    # 그 직후(3ms) 원본 Checkpoint 는 DS 가 만들 것이므로 CP 표시를 뺀다. 남는 CP 는 원인을 모르는 Checkpoint
    db = {"journalTx": 0, "journalKB": [], "walCommit": 0, "walKB": [], "dbSync": 0}
    first_fs, ds_t, jbytes, wbytes = set(), [], {}, {}
    for e in ev:
        t, op, ino = e[0], e[1], e[2]
        nm = names.get(ino, "")
        if op in ("W", "WB", "WX") and nm.endswith("-journal"):
            jbytes[ino] = jbytes.get(ino, 0) + e[4] * 4
        elif op in ("W", "WB", "WX") and nm.endswith("-wal"):
            wbytes[ino] = wbytes.get(ino, 0) + e[4] * 4
        elif op in ("FS", "FA"):
            if nm.endswith("-journal") and ino not in first_fs:
                first_fs.add(ino)
                ds_t.append(t)
                db["journalTx"] += 1
                db["journalKB"].append(jbytes.get(ino, 0))
            elif nm.endswith("-wal"):
                db["walCommit"] += 1
                db["walKB"].append(wbytes.pop(ino, 0))
            elif nm.endswith(".db"):
                db["dbSync"] += 1
    # 이름과 상관없이: fsync 직후 3ms 안에 Checkpoint 가 오면 그 fsync 가 부른 것 (super-journal -mj…, AtomicFile .tmp, 새 로그 파일 …)
    cps = [e[0] for e in ev if e[1] == "CP"]
    have = set(ds_t)
    for e in ev:
        if e[1] in ("FS", "FA") and e[0] not in have:
            j = bisect.bisect_left(cps, e[0])
            if j < len(cps) and cps[j] - e[0] <= 0.003:
                ds_t.append(e[0])
                have.add(e[0])
    ds_t.sort()
    cp_all = len(cps)
    out = []
    for e in ev:
        if e[1] == "CP":
            j = bisect.bisect_right(ds_t, e[0]) - 1
            if j >= 0 and e[0] - ds_t[j] <= 0.003:
                continue
        out.append(e)
    ev = out + [[t + 0.00005, "DS", 0, 0, 0, 0] for t in ds_t]
    ev.sort(key=lambda e: e[0])
    med = lambda v: sorted(v)[len(v) // 2] if v else 0  # noqa: E731
    db = {"journalTx": db["journalTx"], "journalKBmed": med(db["journalKB"]), "walCommit": db["walCommit"],
          "walKBmed": med(db["walKB"]), "dbSync": db["dbSync"], "ckptAll": cp_all,
          "ckptByFsync": cp_all - sum(1 for e in ev if e[1] == "CP")}

    # 3. inode 별 LBA 구간 → 파일 offset
    ext = {}
    for t, op, ino, lba, nb, _ in ev:
        if op in ("R", "W", "WB", "WD", "WX"):
            ext.setdefault(ino, []).append((lba, lba + nb))
    fmap = {}
    for ino, iv in ext.items():
        iv.sort()
        st, en, base = [], [], []
        acc = 0
        for a, b in iv:
            if en and a <= en[-1]:
                if b > en[-1]:
                    acc += b - en[-1]
                    en[-1] = b
                continue
            st.append(a), en.append(b), base.append(acc)
            acc += b - a
        fmap[ino] = (st, base, acc)
    # 파일 번호 = 원본에서 처음 쓰인 LBA 순서. uxwl prep 이 이 순서로 미리 채우므로 f2fs 가 원본처럼 붙여 배치하고,
    # 서로 다른 파일을 이어 읽던 Sequential Read 가 살아난다. 파일 0 = scratch
    inos = sorted(fmap, key=lambda i: (i != 0, fmap[i][0][0] if fmap[i][0] else float("inf")))
    for i in {e[2] for e in ev if e[1] in ("FS", "FA", "UL")} - set(fmap):
        inos.append(i)                                    # fsync 만 있는 파일
        fmap[i] = ([], [], 1)
    fid = {ino: k for k, ino in enumerate(inos)}
    first = {}
    for t, op, ino, *_ in ev:
        if op != "DB":
            first.setdefault(ino, op)

    n = len(ev)
    T = np.empty(n, np.float64)
    OP = np.empty(n, np.uint8)
    F = np.zeros(n, np.uint32)
    OFF = np.zeros(n, np.uint64)
    LN = np.zeros(n, np.uint32)
    for k, (t, op, ino, lba, nb, _) in enumerate(ev):
        T[k], OP[k] = t, OPS[op]
        if op == "DB":
            LN[k] = nb * 4096
            continue
        if op in ("CP", "DS"):
            continue
        F[k] = fid[ino]
        if op not in ("FS", "FA", "UL"):
            st, base, _ = fmap[ino]
            j = bisect.bisect_right(st, lba) - 1
            OFF[k] = (base[j] + lba - st[j]) * 4096
            LN[k] = nb * 4096
    files = {"ino": np.array(inos, np.uint64),
             "size": np.array([fmap[i][2] * 4096 for i in inos], np.uint64),
             # 처음 접근이 Read 면 원래 있던 파일 → 준비 단계에서 미리 채움. Write 로 시작하면 새로 만든 파일
             "existing": np.array([first.get(i, "R") == "R" or i == 0 for i in inos], bool)}
    return {"t": T, "op": OP, "f": F, "off": OFF, "len": LN, **{"file_" + k: v for k, v in files.items()}}, t1 - t0, db


def main():
    SEG.mkdir(parents=True, exist_ok=True)
    idx_path = SEG / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else {}
    for sid, rep, tj, pq in runs():
        a, dur, db = build(pq)
        name = f"{sid}-{rep}"
        np.savez_compressed(SEG / f"{name}.npz", **a)
        c = {o: int((a["op"] == v).sum()) for o, v in OPS.items()}
        mb = {o: round(float(a["len"][a["op"] == v].sum()) / 1e6, 1) for o, v in OPS.items() if o not in ("FS", "FA", "UL", "CP", "DS")}
        ex = a["file_existing"]
        idx[name] = {"sid": sid, "repeat": rep, "traceJobId": tj, "pq": pq, "durSec": round(dur, 2), "count": c, "MB": mb,
                     "files": int(len(ex)), "existingMB": round(float(a["file_size"][ex].sum()) / 1e6, 1),
                     "newMB": round(float(a["file_size"][~ex].sum()) / 1e6, 1), "db": db}
        print(f"  {name:8} {dur:7.1f}s  R {mb['R']:7.1f}  W {mb['W']:6.1f}  WB {mb['WB']:6.1f}  WX {mb['WX']:6.1f}  WD {mb['WD']:6.1f}  "
              f"fsync {c['FS']:5}  atomic {c['FA']:5}  unlink {c['UL']:5}  ckpt {c['CP']:4}  DBtx(j/w) {db['journalTx']}/{db['walCommit']}  disc {mb['DB']:6.1f}MB  files {len(ex):5} (기존 {idx[name]['existingMB']}MB, 새 {idx[name]['newMB']}MB)")
    idx_path.write_text(json.dumps(dict(sorted(idx.items())), indent=1))
    print(f"wrote {len(idx)} segments → {SEG}")


if __name__ == "__main__":
    main()
