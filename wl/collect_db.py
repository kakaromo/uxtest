#!/usr/bin/env python3
"""시나리오마다 앱 DB 의 구조와 쓰임을 모은다 (측정과 따로). 결과는 .private/dbinfo 에만 둔다

  python3 wl/collect_db.py            # 화면 꺼짐 대기를 뺀 시나리오 전부. 끝난 시나리오는 건너뛴다
  python3 wl/collect_db.py B7t C1

각 시나리오의 측정 trace 에서 Write 가 많은 DB 를 고르고, 시나리오를 한 번 돌리는 동안 uxwl dbwatch 로 잰다.
끝나면 real.json (DB 이름 → 구조·쓰임 파일) 을 다시 만든다. 행 내용은 폰 밖으로 나오지 않는다.
"""
import collections
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
OUT = HERE / ".private" / "dbinfo"
SEG = HERE / ".private" / "seg"
SERIAL = os.environ.get("UX_SERIAL", "192.168.1.20:5555")
DEV = "/data/local/tmp/uxwl"
SKIP = ("S1", "S2", "S3", "S4", "S5")
MIN_MB, TOP = 0.05, 8
sys.path.insert(0, str(HERE.parent / "report"))
sys.path.insert(0, str(HERE.parent))
import extract  # noqa: E402


def adb(cmd, check=False, timeout=600):
    for k in range(3):
        p = subprocess.run(["adb", "-s", SERIAL, "shell", cmd], capture_output=True, text=True, errors="replace", timeout=timeout)
        if p.returncode == 0 or not check:
            return p.stdout
        subprocess.run(["adb", "connect", SERIAL], capture_output=True)
        time.sleep(20)
    raise RuntimeError(p.stderr[:200])


def paths():
    out = adb(r'''find /data/data /data/user_de/0 /data/system /data/misc -type f -size +0 2>/dev/null | grep -Ev '/(cache|code_cache|app_webview/.*/Cache|shared_prefs)/' ''', timeout=600)
    by = collections.defaultdict(list)
    for p in out.split("\n"):
        by[os.path.basename(p.strip())].append(p.strip())
    return by


def pkg(p):
    m = re.match(r"/data/(?:data|user_de/0)/([^/]+)/", p)
    return m.group(1) if m else p.split("/")[3] if len(p.split("/")) > 3 else "sys"


def top_dbs(seg):
    pq = extract.parquet_of(seg["traceJobId"]) or seg["pq"]
    rows = duckdb.sql(f"""select name, sum(size)/1e6 from read_parquet('{pq}') where action = 'send_req' and opcode in (42,138) and name is not null group by 1""").fetchall()
    agg = collections.Counter()
    has = set()
    for n, mb in rows:
        b = os.path.basename(n)
        base = re.sub(r"-(wal|journal)$", "", b)
        if base != b:
            has.add(base)
        agg[base] += mb
    return [b for b, mb in agg.most_common(200) if b in has and mb >= MIN_MB][:TOP]


def scenario_text(sid):
    for p in (HERE.parent / "scenarios").glob(f"*/{sid}.scenario.json"):
        return p.read_text()
    return ""


def is_sqlite(path):
    return "SQLite format 3" in adb(f"dd if='{path}' bs=16 count=1 2>/dev/null | cat")


def collect(sid, seg, by):
    bases = top_dbs(seg)
    text = scenario_text(sid)
    tg = {}
    for b in bases:
        ps = by.get(b, [])
        if len(ps) > 1:                        # 같은 이름이 여러 앱에 있으면 시나리오가 쓰는 앱 것만
            named = [p for p in ps if pkg(p) in text]
            ps = named or ps[:1]
        for p in ps[:2]:
            if is_sqlite(p):
                tg[f"{b}@{pkg(p)}"] = p
    if not tg:
        print(f"[{sid}] 볼 DB 없음", flush=True)
        (OUT / f"watch-{sid}.json").write_text("{}")
        return
    # dbwatch 의 결과 키에 / 가 없도록 번호로 넘기고 나중에 푼다
    keys = list(tg)
    args = " ".join(f"d{i}='{tg[k]}'" for i, k in enumerate(keys))
    adb(f"rm -rf /dev/uxdb; mkdir -p /dev/uxdb; {DEV}/uxwl dbwatch --sec 3600 --tc /dev/uxdb/out.json {args} > /dev/uxdb/log 2>&1 &")
    time.sleep(1)
    for _ in range(120):
        if "시작" in adb("cat /dev/uxdb/log 2>/dev/null"):
            break
        time.sleep(1)
    print(f"[{sid}] {time.strftime('%H:%M:%S')} DB {len(keys)}개 감시, 시나리오 실행", flush=True)
    r = subprocess.run([sys.executable, str(HERE.parent / "run.py"), "--dry", sid], capture_output=True, text=True, errors="replace",
                       env=os.environ | {"UX_SERIAL": SERIAL, "UX_DEVICE": SERIAL})
    ok = r.returncode == 0
    adb("touch /dev/uxdb/out.json.stop")
    for _ in range(300):
        if "끝" in adb("cat /dev/uxdb/log 2>/dev/null"):
            break
        time.sleep(1)
    raw = adb("cat /dev/uxdb/out.json", timeout=120)
    res = json.loads(raw) if raw.strip() else {}
    out = {keys[int(k[1:])]: v | {"path": tg[keys[int(k[1:])]]} for k, v in res.items()}
    (OUT / f"watch-{sid}.json").write_text(json.dumps(out, ensure_ascii=False))
    # 구조: 복사본으로 읽는다
    for k in keys:
        f = OUT / f"info-{safe(k)}.json"
        if not f.exists():
            p = tg[k]
            js = adb(f"mkdir -p /dev/uxdi; cp '{p}' /dev/uxdi/x.db; [ -f '{p}-wal' ] && cp '{p}-wal' /dev/uxdi/x.db-wal; {DEV}/uxwl dbinfo /dev/uxdi/x.db; rm -rf /dev/uxdi", timeout=300)
            if js.strip().startswith("{"):
                f.write_text(js)
    adb("rm -rf /dev/uxdb /dev/uxdi")
    ch = sum(1 for v in out.values() if v.get("tablesChanged"))
    print(f"[{sid}] 끝 {'성공' if ok else '시나리오 실패'}, 바뀐 DB {ch}/{len(out)}", flush=True)


def safe(k):
    return re.sub(r"[^A-Za-z0-9._-]", "_", k)


def build_real():
    """DB 이름마다 행 동작이 가장 많았던 측정을 고른다. WITHOUT ROWID·가상 테이블뿐이거나 행 동작이 없으면 공용 테이블로 남는다"""
    best = {}
    for f in OUT.glob("watch-*.json"):
        sid = f.stem[6:]
        try:
            j = json.loads(f.read_text())
        except ValueError:
            continue
        for k, v in j.items():
            ch = v.get("tablesChanged") or {}
            ops = sum(t["insert"] + t["update"] + t["delete"] for t in ch.values())
            base = k.split("@")[0]
            info = OUT / f"info-{safe(k)}.json"
            if ops and info.exists() and ops > best.get(base, (0,))[0]:
                best[base] = (ops, info.stem, sid, k)
    real = {b: {"info": i, "scenario": s, "watch": k} for b, (o, i, s, k) in best.items()}
    if "ttm_strategy.db" in real:
        real["ttm_strategy.db"]["opsScale"] = 0.5
    (OUT / "real.json").write_text(json.dumps(real, ensure_ascii=False, indent=1))
    print(f"real.json: DB {len(real)}개", flush=True)


def main():
    idx = json.loads((SEG / "index.json").read_text())
    subprocess.run(["make", "-s", "-C", str(HERE)], check=True)
    subprocess.run(["adb", "-s", SERIAL, "push", "-q", str(HERE / ".private" / "uxwl"), f"{DEV}/"], check=True)
    adb(f"chmod 755 {DEV}/uxwl")
    sids = sys.argv[1:] or sorted({v["sid"] for v in idx.values() if not v["sid"].startswith(SKIP)})
    by = paths()
    print(f"파일 {sum(map(len, by.values()))}개, 시나리오 {len(sids)}개", flush=True)
    for sid in sids:
        if not sys.argv[1:] and (OUT / f"watch-{sid}.json").exists():
            continue
        lv = adb("dumpsys battery")
        if "AC powered: true" in lv or "USB powered: true" in lv:
            sys.exit("USB·AC 전원이 들어와 있어서 멈춰요")
        m = re.search(r"level: (\d+)", lv)
        if m and int(m.group(1)) < 20:
            sys.exit(f"배터리 {m.group(1)}% 라 멈춰요")
        seg = idx[f"{sid}-1"]
        try:
            collect(sid, seg, by)
        except Exception as e:
            print(f"[{sid}] 오류: {e}", flush=True)
            adb("rm -rf /dev/uxdb /dev/uxdi")
    build_real()


if __name__ == "__main__":
    main()
