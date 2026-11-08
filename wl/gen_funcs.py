#!/usr/bin/env python3
"""조각(.private/seg/*.npz) → 시나리오 함수 묶음 (.private/funcs/funcs.bin)

  python3 wl/gen_funcs.py

시나리오 하나가 함수 하나이고, 측정 회차마다 request 표를 하나씩 가진다. 유형 묶음은 groups.json.
유형 가중치는 여기서 정하지 않는다. 실행할 때 uxwl plan/mix 의 --weight 로 준다.

형식 (little endian, wl/replay/mix.go 가 읽는다)
  "UXFN0001" | json 길이 u32 | json | 회차 데이터
  json: {groups: {유형: {함수: 비중}}, funcs: {함수: {name, reps: [{seg, durSec, off, nfiles, nreq, dirs}]}}}
  dirs: 파일마다 원본 상위 폴더 번호 (회차 안에서 1부터, 0 = 경로 모름). uxwl 은 같은 번호 파일을 같은 폴더 f/g<번호>/ 에 둔다.
    앱은 파일을 수백 개 폴더에 나눠 둔다. 파일을 만들고 지울 때 dirty 가 되는 폴더 inode·dentry page 가 Checkpoint 때 같이 쓰이므로
    폴더 하나에 모으면 Checkpoint 한 번의 크기가 원본의 절반쯤으로 줄었다 (--flat 이 예전 방식). 경로 문자열은 넣지 않는다.
  회차 데이터 (off 는 파일 처음부터): files(size u64, flags u8) × nfiles, reqs(t_us u64, op u8, file u32, off u64, len u32) × nreq
  files flags: 1 = 원래 있던 파일, 2 = SQLite DB, 4 = rollback journal DB, 8 = 실제 구조 DB, 16 = 새 폴더 안 파일
새 폴더 안 파일: 원본 Checkpoint 바로 앞(CAUSE_WIN)의 마지막 request 가 새 파일의 Write·unlink 이면, 앱이 폴더를 새로 만들고
  그 안에 파일을 써서 fsync 한 것이다 (ftrace 로 확인: Shorts 의 Checkpoint 대부분이 cp_reason "node needs cp", 폴더는 모두
  측정 중 새로 만든 것). 이런 fsync 는 node 를 쓰지 않고 바로 Checkpoint 로 가서 UFS trace 에 fsync 로 남지 않는다.
  그래서 그 파일에 flag 16 을 주고 마지막 Write 직후에 FS 를 넣는다. Checkpoint 는 uxwl 이 부르지 않고 f2fs 가 정한다.
시나리오 단계의 sync: cold start 시나리오는 측정 구간 안에서 "sync; echo 3 > drop_caches" 를 부르고, 그 sync 가 Checkpoint 를 낸다
  (Chrome cold start 는 원본 Checkpoint 17번 중 4번). 앱 동작은 아니지만 원본 trace 에 들어 있으므로 op 16(SYNC)으로 같은 시각에 sync() 를 부른다.
Discard(DB) 는 넣지 않는다. f2fs 가 지운 파일의 블록을 스스로 반납한다 (gen_tc.py Builder 와 같음).

DB 파일의 Write 는 파일 동작으로 재생하지 않고 실제 SQLite transaction 으로 바꾼다 (--no-sqlite 면 그대로 재생).
trace 에서 DB 파일(이름, -wal, -journal)의 Write 를 시간 묶음으로 나눠 묶음마다 op 15(SQL) 하나를 만든다:
  WAL + DB 본체 Write 가 같이 있으면 checkpoint, WAL 만 있고 REQ_SYNC 면 WAL fsync, 아니면 writeback.
  -journal 은 파일(inode) 하나가 transaction 하나.
Read 와 atomic write(WX·FA)는 파일 동작 재생으로 둔다. 쓰임이 적거나 SQLite 빌드 옵션에 달려 있기 때문이다.
"""
import argparse
import collections
import glob
import json
import os
import re
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SEG = HERE / ".private" / "seg"
OUT = HERE / ".private" / "funcs"
sys.path.insert(0, str(HERE))
DB_OP = 5
FS, WX, FA, CP, DS, SQL, SYNC = 4, 10, 9, 11, 13, 15, 16
CAUSE_WIN = 0.01             # fsync 뒤 이 시간 안의 Checkpoint 는 그 fsync 때문으로 본다
WRITES = (1, 2, 3)            # W WB WD
UL, RN, TOUCH = 6, 17, 18
GAP = 0.05                    # 이 간격보다 벌어지면 다른 묶음 (checkpoint 하나의 WAL·DB Write 는 붙어 있다)
SQL_WAL_CKPT, SQL_WAL_SYNC, SQL_WAL_LAZY, SQL_ROLLBACK = 1, 2, 3, 4
SQL_FRESH_WAL = 0x10          # 앱이 DB 를 닫았다 다시 열어 WAL 이 새로 생긴 transaction (uxwl 이 닫고 다시 열고 폴더 fsync)
DBNAME = re.compile(r"\.(db|sqlite3?)$", re.I)
FILE = np.dtype([("size", "<u8"), ("existing", "u1")])
REQ = np.dtype([("t", "<u8"), ("op", "u1"), ("f", "<u4"), ("off", "<u8"), ("len", "<u4")])


def names():
    out = {}
    for p in glob.glob(str(HERE.parent / "scenarios" / "*" / "*.scenario.json")):
        n = json.loads(Path(p).read_text()).get("name", "")
        m = re.match(r"\[UX-fsio\]\s+(\S+)\s+(.*)", n)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def load_specs():
    """.private/dbinfo 의 구조(dbinfo)·쓰임(dbwatch) → 실제 테이블 구조. {DB 파일 이름: (구조 이름, spec, 행 동작 비율)}"""
    d = HERE / ".private" / "dbinfo"
    out = {}
    p = d / "real.json"
    if not p.exists():
        return out
    for base, c in json.loads(p.read_text()).items():
        info = json.loads((d / f"{c['info']}.json").read_text())
        watch = json.loads((d / f"watch-{c['scenario']}.json").read_text())[c["watch"]]
        changed = watch.get("tablesChanged", {})
        tables = [{"name": o["name"], "rows": o.get("rows") or 0, "avgRowBytes": changed.get(o["name"], {}).get("avgRowBytes", 64),
                   **{k: changed.get(o["name"], {}).get(k, 0) for k in ("insert", "update", "delete")}}
                  for o in info["objects"] if o["type"] == "table" and not o["name"].startswith("sqlite_")]
        create = [o["sql"] for o in info["objects"] if o["sql"] and not o["name"].startswith("sqlite_")]
        order = {"table": 0, "index": 1, "trigger": 2, "view": 3}
        create = [o["sql"] for o in sorted(info["objects"], key=lambda o: order.get(o["type"], 9)) if o["sql"] and not o["name"].startswith("sqlite_")]
        # 앱 밖에는 Android 전용 collation 과 앱이 등록한 SQL 함수가 없다. collation 은 빼고, 그런 함수를 부르는 trigger 는 만들지 않는다
        fixed = []
        for q in create:
            q = re.sub(r"(?i)\s+COLLATE\s+(LOCALIZED|UNICODE|PHONEBOOK|NAME|[A-Z_]*LOCALE[A-Z_]*)\b", "", q)
            if q.upper().startswith("CREATE TRIGGER") and re.search(r"\b_[A-Z_]+\s*\(", q):
                continue
            if q.upper().startswith("CREATE VIRTUAL"):   # 앱 전용 tokenizer·모듈이 없을 수 있다
                continue
            fixed.append(q)
        create = fixed
        virt = {o["name"] for o in info["objects"] if (o["sql"] or "").upper().startswith("CREATE VIRTUAL")}
        tables = [t for t in tables if t["name"] not in virt and not any(t["name"].startswith(v + "_") for v in virt)]
        ops = sum(t["insert"] + t["update"] + t["delete"] for t in tables)
        if not ops:
            continue
        out[base] = {"spec": {"create": create, "tables": tables, "framesPerOp": watch.get("wal", {}).get("pages", 0) / ops, "opsPerCommit": max(1, round(ops / max(1, watch.get("wal", {}).get("commits", 0))))}, "ops": ops * c.get("opsScale", 1), "walPages": watch.get("wal", {}).get("pages", 0)}
    return out


SPECS = {}
SYNC_SIDS = set()


walprefill = 256              # sqlite.go walPrefill 와 같다. 채움 테이블은 이만큼 이상


def dbmodel(con, pq, a):
    """조각 하나의 DB 동작. 돌려주는 것: (재생에서 뺄 파일, [(DB 이름, flags, 행 수, [(t, pages, uniq, 동작)])], 통계)"""
    t0 = con.execute(f"select min(time) from read_parquet('{pq}')").fetchone()[0]
    names = dict(con.execute(f"select ino, any_value(name) from read_parquet('{pq}') where name is not null and ino > 1 group by 1").fetchall())
    base = {}
    for f, ino in enumerate(a["file_ino"]):
        nm = os.path.basename(names.get(int(ino), "") or "")
        if nm:
            b = re.sub(r"-(wal|journal)$", "", nm)
            base[f] = (b, nm[len(b) + 1:] if nm != b else "main")
    ck = np.array([x for (x,) in con.execute(f"""select time - {t0} from read_parquet('{pq}')
        where action = 'send_req' and opcode in (42, 138) and comm like 'f2fs_ckpt%' order by time""").fetchall()])

    def ck_after(t):
        j = np.searchsorted(ck, t, side="right")
        return j < len(ck) and ck[j] - t <= CAUSE_WIN
    per = collections.defaultdict(dict)
    for f, (b, k) in base.items():
        per[b].setdefault(k, []).append(f)
    out, drop, stat = [], set(), collections.Counter()
    for b, fs in per.items():
        if "wal" not in fs and "journal" not in fs:      # 이름만으로는 DB 인지 모르고 WAL·journal 도 없으면 원래대로 재생
            continue
        ino = [int(a["file_ino"][f]) for k in fs.values() for f in k]
        rows = con.execute(f"""select time - {t0}, ino, size, coalesce(is_req_sync, false) from read_parquet('{pq}')
            where action = 'send_req' and opcode in (42, 138) and ino in ({",".join(map(str, ino))})
              and not coalesce(is_f2fs_node_write or is_f2fs_meta_write or is_checkpoint or is_journal or is_gc, false) order by time""").fetchall()
        if not rows:
            continue
        kind = {int(a["file_ino"][f]): k for k, v in fs.items() for f in v}
        tx = []
        jw = sum(s for _, i, s, _ in rows if kind[i] == "journal")
        ww = sum(s for _, i, s, _ in rows if kind[i] == "wal")
        rollback = jw > ww
        if rollback:
            first = {}
            for t, i, s, _ in rows:
                if kind[i] == "journal":
                    first.setdefault(i, t)
            main_b = sum(s for _, i, s, _ in rows if kind[i] == "main")
            n = max(1, len(first))
            p = max(1, round(main_b / 4096 / n) - 1)     # commit 마다 page 1 도 바뀐다
            if b in SPECS:                               # 실제 테이블: transaction 하나의 행 동작 수
                p = max(1, round(SPECS[b]["ops"] / n))
            tx = [(t, p, p, SQL_ROLLBACK) for t in sorted(first.values())]
            stat["rollbackTx"] += len(tx)
        else:
            burst = []
            seen = set()
            for t, i, s, sy in rows:
                # 새 WAL: 처음 보인 WAL inode 이고 그 첫 Write 10ms 안에 Checkpoint 가 왔다 (SQLite 가 새 WAL 의 첫 sync 뒤 폴더를 fsync).
                # 원본은 70ms 안에 WAL 을 네 번 새로 만들기도 해서, 새 WAL 마다 transaction 을 나눈다
                new = kind[i] == "wal" and i not in seen and ck_after(t)
                if kind[i] == "wal":
                    seen.add(i)
                if not burst or t - burst[-1]["end"] > GAP or new:
                    burst.append({"t": t, "end": t, "wal": 0, "main": 0, "sync": 0, "n": 0, "new": new})
                c = burst[-1]
                c["end"] = t
                c["n"] += 1
                c["sync"] += bool(sy)
                c["wal" if kind[i] != "main" else "main"] += s
            for c in burst:
                fresh = SQL_FRESH_WAL if c["new"] else 0
                stat["freshWal"] += bool(fresh)
                # WAL frame 은 4120 byte 라 block 경계를 넘는다. frame 1개도 Write 2 block 이므로 그만큼 뺀다
                wal_p = max(1, round((c["wal"] - 4096) / 4120))
                if b in SPECS:  # 실제 테이블: 목표 WAL frame 수와 checkpoint page 수. 행 동작 수는 재생기가 재면서 정한다
                    tx.append((c["t"], wal_p if c["wal"] else 0, round(c["main"] / 4096), fresh | (SQL_WAL_CKPT if c["main"] else (SQL_WAL_SYNC if c["sync"] * 2 >= c["n"] else SQL_WAL_LAZY))))
                    continue
                if c["main"]:
                    m = max(1, round(c["main"] / 4096))
                    tx.append((c["t"], max(wal_p, m), m, fresh | SQL_WAL_CKPT))
                    stat["walCkpt"] += 1
                elif c["sync"] * 2 >= c["n"]:
                    tx.append((c["t"], wal_p, wal_p, fresh | SQL_WAL_SYNC))
                    stat["walSync"] += 1
                else:
                    tx.append((c["t"], wal_p, wal_p, fresh | SQL_WAL_LAZY))
                    stat["walLazy"] += 1
        drop |= {f for v in fs.values() for f in v}
        size = max([int(a["file_size"][f]) for f in fs.get("main", [])] + [0])
        uniq = max(x[2] for x in tx)
        nrows = max(walprefill, 2 * uniq) if b in SPECS and not rollback else max(256, size // 4096, 2 * uniq)
        home = (fs.get("main") or fs.get("wal") or fs.get("journal"))[0]   # 이 DB 가 있던 폴더를 줄 파일
        out.append((b, 2 | (4 if rollback else 0) | (8 if b in SPECS else 0), nrows, tx, home))
        stat["dbs"] += 1
        stat["writeBytes"] += sum(s for _, _, s, _ in rows)
    return drop, out, stat



def touch_extra(con, pq, a, sel, drop):
    """원본 Checkpoint 에 node 가 나왔는데 그 사이 TC 가 아무것도 쓰지 않는 파일 → Checkpoint 직전에 TOUCH (시각만 바꿔 inode 를 dirty 로).
    원본은 Read 만 보이는 파일의 node 도 Checkpoint 에 실렸다 (무거운 앱 cold start 의 영상 cache 파일들). 앱이 파일 시각을 바꾸거나
    (SimpleCache 의 touch) 이름을 바꾼 것으로 보지만 UFS trace 에는 그런 메타데이터 동작이 안 남는다. 이름이 없는 inode 는 TC 파일이 없어 넣지 못한다"""
    cpq = os.path.join(os.path.dirname(pq), "result_fsio_cpnode.parquet")
    if not os.path.exists(cpq):
        return [], {}
    t0 = con.execute(f"select min(time) from read_parquet('{pq}')").fetchone()[0]
    of = {int(i): f for f, i in enumerate(a["file_ino"]) if int(i) > 10}
    rows = con.execute(f"""select cp_ver, min(time) - {t0}, list(distinct ino) from read_parquet('{cpq}')
        where ino > 10 group by 1 order by 2""").fetchall()
    if not rows:
        return [], {}
    # 파일마다 TC 가 실제로 내는 Write 계열 동작 시각 (Read 는 inode 를 dirty 로 만들지 않는다)
    w = sel & (a["op"] != 0)
    by_f = collections.defaultdict(list)
    for t, f in zip(a["t"][w], a["f"][w]):
        by_f[int(f)].append(float(t))
    gone = {}
    for t, f in zip(a["t"][sel & np.isin(a["op"], [UL, RN])], a["f"][sel & np.isin(a["op"], [UL, RN])]):
        gone.setdefault(int(f), float(t))
    last_end = float(a["t"][-1]) if len(a["t"]) else 0.0
    out, st, prev = [], collections.Counter(), -1e9
    for _, tc, inos in rows:
        if tc < 0 or tc > last_end + 1:
            prev = tc
            continue
        for ino in inos:
            f = of.get(int(ino))
            if f is None:
                st["touchNoFile"] += 1
                continue
            if f in drop:
                continue
            ts = by_f.get(f, [])
            if any(prev < x <= tc for x in ts):
                continue
            if f in gone and gone[f] <= tc:     # 이미 지웠거나 이름을 바꾼 파일
                continue
            # 파일이 그 시각에 있어야 한다: 처음부터 있던 파일이거나 TC 가 그 전에 만든 파일
            if not (a["file_existing"][f] & 1) and not any(x <= tc for x in ts):
                st["touchNotYet"] += 1
                continue
            out.append((int(max(0.0, tc - 0.003) * 1e6), TOUCH, f, 0, 0))
            st["touch"] += 1
        prev = tc
    return out, st


def sync_scenarios():
    """측정 구간 안에서 "sync; echo 3 > drop_caches" 단계를 부르는 시나리오 (cold start 계열)"""
    out = set()
    for p in glob.glob(str(HERE.parent / "scenarios" / "*" / "*.scenario.json")):
        on = False
        for st in json.loads(Path(p).read_text()).get("steps", []):
            t, cmd = st.get("type"), st.get("params", {}).get("cmd", "")
            on = True if t == "trace_start" else False if t == "trace_stop" else on
            if on and t == "shell" and re.search(r"\bsync\b", cmd) and "drop_caches" in cmd:
                out.add(Path(p).name.split(".")[0])
    return out


def scenario_syncs(con, pq):
    """그 단계의 sync 시각. drop_caches 뒤라 sh 가 실행 파일을 다시 읽는 Read 묶음(20개 넘게)으로 보이고,
    Checkpoint 가 그 0.2초쯤 뒤에 온다 (Chrome cold start 4/4, 무거운 앱 cold start 2/2). 묶음 시작에 sync 를 부른다"""
    t0 = con.execute(f"select min(time) from read_parquet('{pq}')").fetchone()[0]
    rows = con.execute(f"""select time - {t0} from read_parquet('{pq}')
        where action = 'send_req' and comm = 'sh' and opcode in (40, 136) order by time""").fetchall()
    b = []
    for (t,) in rows:
        if not b or t - b[-1][1] > 0.3:
            b.append([t, t, 0])
        b[-1][1] = t
        b[-1][2] += 1
    return [x[0] for x in b if x[2] >= 20]


WD_OP, WD_GAP, WD_MAX = 3, 1000, 16 << 20   # direct Write, 조각 사이 1ms, uxwl maxIO


def merge_wd(r):
    """앱이 한 번 부른 큰 direct pwrite 는 커널에서 bio 여러 개로 나뉘어 trace 에 따로 찍힌다. 같은 파일에서 offset 이
    이어지고 앞 조각에서 1ms 안에 온 WD 를 하나로 합친다(16MB 까지). 따로 재생하면 동시에 쓰는 다른 파일과
    번갈아 pwrite 돼 f2fs 가 미리 할당하지 못하고(i_size 안쪽 쓰기) block 이 4KB 씩 섞여 놓인다(버스트샷 3초).
    uxwl 도 이어진 WD 를 합치지만 전체 순서에서 바로 붙은 것만 봐서, 파일 여러 개가 섞이면 못 합친다"""
    keep = np.ones(len(r), bool)
    open_ = {}                                   # 파일 → [합치는 중인 index, 마지막 조각 시각]
    n = 0
    wd = r["op"] == WD_OP
    for i in np.flatnonzero(wd | np.isin(r["op"], [FS, FA, WX, 0, 1, 2, 6, 7, RN])):
        f = int(r["f"][i])
        if not wd[i]:                            # 같은 파일의 다른 동작(fsync, Read, unlink...)이 끼면 끊는다
            open_.pop(f, None)
            continue
        h = open_.get(f)
        if h is not None:
            j, last = h
            if (int(r["t"][i]) - last <= WD_GAP and int(r["off"][i]) == int(r["off"][j]) + int(r["len"][j])
                    and int(r["len"][j]) + int(r["len"][i]) <= WD_MAX):
                r["len"][j] += r["len"][i]
                keep[i] = False
                h[1] = int(r["t"][i])
                n += 1
                continue
        open_[f] = [i, int(r["t"][i])]
    return r[keep], n


def file_dirs(con, pq, a):
    """파일마다 원본 상위 폴더 번호 (1부터, 회차 안에서 경로 순). 경로를 모르면 0. 경로 자체는 내보내지 않는다"""
    rows = con.execute(f"""select ino, max(case when name like '/%' then name end) from read_parquet('{pq}')
        where ino > 1 and name is not null group by 1""").fetchall()
    path = {int(i): n for i, n in rows if n}
    par = [os.path.dirname(path[int(i)]) if int(i) in path else "" for i in a["file_ino"]]
    num = {d: k + 1 for k, d in enumerate(sorted({d for d in par if d}))}
    return np.array([num.get(d, 0) for d in par], np.uint32)


def new_dir_files(a, drop):
    """원본 Checkpoint 바로 앞이 새 파일의 Write·unlink 인 파일 → (새 폴더에 둘 파일, 그 파일의 마지막 Write 직후 FS)"""
    t, op, f = a["t"], a["op"], a["f"]
    cp = t[op == CP]
    if not len(cp):
        return set(), []
    cp = cp[np.r_[True, np.diff(cp) > 0.001]]          # 한 Checkpoint 의 Write 묶음은 한 번
    nm = op != CP
    tt, oo, ff = t[nm], op[nm], f[nm]
    files, extra = set(), []
    for c in cp:
        j = int(np.searchsorted(tt, c)) - 1
        if j < 0 or c - tt[j] >= CAUSE_WIN or int(oo[j]) not in (1, 2, UL, RN):
            continue
        x = int(ff[j])
        if a["file_existing"][x] & 1 or x in drop or x in files:   # 같은 폴더는 처음 fsync 때만 Checkpoint 가 난다
            continue
        w = (f == x) & np.isin(op, (1, 2)) & (t <= c)
        if not w.any():
            continue
        files.add(x)
        extra.append((int((float(t[w].max()) + 0.0001) * 1e6), FS, x, 0, 0))
    return files, extra

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sqlite", action="store_true", help="DB Write 도 파일 동작으로 재생")
    ap.add_argument("--no-real", action="store_true", help="실제 테이블 구조(real.json)를 쓰지 않고 공용 테이블 UPDATE 로")
    ap.add_argument("--no-sync", action="store_true", help="시나리오 단계의 sync(cold start 전 drop_caches)를 넣지 않는다")
    ap.add_argument("--no-merge-wd", action="store_true", help="같은 파일의 이어진 direct Write 조각을 합치지 않는다 (11-05 까지의 방식)")
    ap.add_argument("--flat", action="store_true", help="원본 폴더 구조를 쓰지 않고 모든 파일을 f/ 하나에 둔다 (v5 후보 2 까지의 방식)")
    ap.add_argument("--no-touch", action="store_true", help="원본 Checkpoint node 의 주인인데 TC 가 쓰지 않는 파일에 TOUCH 를 넣지 않는다 (v5 후보 8 전)")
    ap.add_argument("--keep-cp", action="store_true", help="f2fs Checkpoint 를 원본 시각에 일으키는 CP op 를 남김. 기본은 뺀다: Checkpoint 는 FS 몫이라 앱 동작의 결과로만 나와야 한다")
    args = ap.parse_args()
    import duckdb
    dcon = duckdb.connect()
    con = None if args.no_sqlite else dcon
    total = collections.Counter()
    touch_by = collections.Counter()
    groups = json.loads((HERE / "groups.json").read_text())["groups"]
    idx = json.loads((SEG / "index.json").read_text())
    reps = {}
    for k, v in idx.items():
        reps.setdefault(v["sid"], []).append(k)
    member = [s for g in groups.values() for s in g]
    if len(member) != len(set(member)):
        raise SystemExit("한 시나리오가 두 유형에 들어 있어요: " + str(sorted({s for s in member if member.count(s) > 1})))
    if set(member) != set(reps):
        raise SystemExit(f"groups.json 과 측정 시나리오가 달라요: 없는 측정 {sorted(set(member) - set(reps))}, 유형 없음 {sorted(set(reps) - set(member))}")

    sys.path.insert(0, str(HERE.parent / "report"))
    sys.path.insert(0, str(HERE.parent))
    global extract
    import extract
    nm = names()
    global SYNC_SIDS
    SYNC_SIDS = sync_scenarios()
    global SPECS
    if not args.no_real:
        SPECS = load_specs()
    meta = {"groups": groups, "funcs": {}, "specs": {k: v["spec"] for k, v in SPECS.items()}}
    blobs = []
    pos = 0
    for sid in sorted(reps):
        fn = {"name": nm.get(sid, sid), "reps": []}
        for seg in sorted(reps[sid]):
            a = np.load(SEG / f"{seg}.npz")
            sel = a["op"] != DB_OP
            if not args.keep_cp:
                sel = sel & (a["op"] != CP)
                # 원본 Checkpoint 바로 앞에 fsync 가 있으면 그 fsync 가 원인이다 (새 파일·AtomicFile: 디렉터리까지 내려야 한다).
                # 시각을 맞춰 Checkpoint 를 부르지 않고, 원인 쪽에 디렉터리 fsync(DS)를 붙인다
                _cp, _fs = a["t"][a["op"] == CP], a["t"][np.isin(a["op"], [FS, FA])]
                ds_t = []
                if len(_cp) and len(_fs):
                    _i = np.searchsorted(_fs, _cp) - 1
                    ds_t = sorted({float(_fs[j]) + 0.0002 for j, c in zip(_i, _cp) if j >= 0 and c - _fs[j] <= CAUSE_WIN})
            dbs, drop = [], set()
            pq = extract.parquet_of(idx[seg]["traceJobId"]) or idx[seg]["pq"]
            dirs = file_dirs(dcon, pq, a) if not args.flat else np.zeros(len(a["file_size"]), np.uint32)
            if con is not None:
                drop, dbs, st = dbmodel(con, pq, a)
                total.update(st)
                if drop:
                    # Read 와 atomic write 를 뺀 DB 파일 동작 (Write, fsync, unlink, TRUNC) 은 SQLite 가 한다
                    infile = np.isin(a["f"], list(drop))
                    keep = (a["op"] == 0) | (a["op"] == WX) | (a["op"] == FA)
                    sel = sel & ~(infile & ~keep)
            ds_extra = [(int(t * 1e6), DS, 0, 0, 0) for t in (ds_t if not args.keep_cp else [])]
            nd_files, nd_extra = set(), []
            if not args.keep_cp:
                nd_files, nd_extra = new_dir_files(a, drop)
                total["newDirFiles"] += len(nd_files)
            sy_extra = [(int(t * 1e6), SYNC, 0, 0, 0) for t in scenario_syncs(dcon, pq)] if sid in SYNC_SIDS and not args.no_sync else []
            total["scenarioSync"] += len(sy_extra)
            tc_extra = []
            if not args.no_touch:
                tc_extra, st = touch_extra(dcon, pq, a, sel, drop)
                total.update(st)
                touch_by[sid] += st.get("touch", 0)
            extra = ds_extra + nd_extra + sy_extra + tc_extra + [(int(t * 1e6), SQL, len(a["file_size"]) + k, p | (u << 32), act) for k, d in enumerate(dbs) for t, p, u, act in d[3]]
            r = np.zeros(int(sel.sum()) + len(extra), REQ)
            n0 = int(sel.sum())
            r["t"][:n0] = (a["t"][sel] * 1e6).astype(np.uint64)
            for k, c in (("op", "op"), ("f", "f"), ("off", "off"), ("len", "len")):
                r[k][:n0] = a[c][sel]
            if extra:
                r[n0:] = np.array(extra, REQ)
                r = r[np.argsort(r["t"], kind="stable")]
            # 새 WAL 로 재생하는 Checkpoint 를 DS(fsync 뒤 폴더 fsync)로 한 번 더 내지 않는다
            fr = r["t"][(r["op"] == SQL) & ((r["len"] & SQL_FRESH_WAL) != 0)]
            if len(fr):
                ds = np.flatnonzero(r["op"] == DS)
                j = np.clip(np.searchsorted(fr, r["t"][ds]), 1, len(fr))
                near = np.minimum(np.abs(fr[j - 1].astype(np.int64) - r["t"][ds].astype(np.int64)),
                                  np.abs(fr[np.minimum(j, len(fr) - 1)].astype(np.int64) - r["t"][ds].astype(np.int64))) <= 20000
                r = np.delete(r, ds[near])
                total["dsDupFresh"] += int(near.sum())
            if not args.no_merge_wd:
                r, n_wd = merge_wd(r)
                total["wdMerged"] += n_wd
            f = np.zeros(len(a["file_size"]) + len(dbs), FILE)
            n1 = len(a["file_size"])
            f["size"][:n1], f["existing"][:n1] = a["file_size"], a["file_existing"]
            # DB 파일의 Read 는 파일 동작으로 남는데 Write 는 SQLite 로 넘어갔다. 아무도 쓰지 않는 파일이므로 미리 채워 둬야 Read 가 나온다
            if con is not None and drop:
                rd = (a["op"] == 0) & np.isin(a["f"], list(drop))
                for x in np.unique(a["f"][rd]):
                    f["existing"][x] = 1
                    f["size"][x] = max(int(f["size"][x]), int((a["off"][a["f"] == x] + a["len"][a["f"] == x]).max()))
            for x in nd_files:
                f["existing"][x] |= 16
            if "file_wdpar" in a:                         # 원본에서 다른 파일과 동시에 O_DIRECT 로 쓴 파일
                f["existing"][:n1][a["file_wdpar"]] |= 32
            for k, d in enumerate(dbs):
                f[n1 + k] = (d[2] * 4096, d[1] | 1)   # 1: 같은 회차를 다시 쓰면 같은 DB
            real = {str(n1 + k): d[0] for k, d in enumerate(dbs) if d[0] in SPECS}
            dirs = [int(x) for x in dirs] + [int(dirs[d[4]]) for d in dbs]
            total["dirs"] += len(set(dirs) - {0})
            blob = f.tobytes() + r.tobytes()
            last = float(a["t"][-1]) if len(a["t"]) else 0.0
            fn["reps"].append({"seg": seg, "durSec": round(max(last, idx[seg]["durSec"]), 6), "off": pos, "nfiles": len(f), "nreq": len(r), **({"dbs": real} if real else {}), **({"dirs": dirs} if any(dirs) else {})})
            blobs.append(blob)
            pos += len(blob)
        meta["funcs"][sid] = fn

    # off 를 파일 처음 기준으로. 길이 자릿수가 바뀌지 않도록 off 를 더한 json 길이가 안정될 때까지 되풀이
    base = 0
    for _ in range(5):
        shifted = json.loads(json.dumps(meta))
        for fn in shifted["funcs"].values():
            for r in fn["reps"]:
                r["off"] += base
        js = json.dumps(shifted, ensure_ascii=False, separators=(",", ":")).encode()
        new = 12 + len(js)
        if new == base:
            break
        base = new
    else:
        raise SystemExit("json 길이가 안정되지 않아요")

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "funcs.bin", "wb") as fo:
        fo.write(b"UXFN0001" + struct.pack("<I", len(js)) + js)
        for b in blobs:
            fo.write(b)
    if con is not None:
        print("TOUCH 회차 합:", dict(touch_by.most_common(15)))
        print("SQLite 로 바꾼 것:", dict(total), f"DB Write {total['writeBytes'] / 1e6:.0f}MB")
    print(f"wrote {OUT / 'funcs.bin'}: 함수 {len(meta['funcs'])}개, 회차 {len(blobs)}개, 유형 {len(groups)}개, {(base + pos) / 1e6:.1f}MB")


if __name__ == "__main__":
    main()
