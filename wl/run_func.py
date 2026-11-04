#!/usr/bin/env python3
"""시나리오 함수를 기기에서 하나씩 또는 가중치로 묶어 실행하고 원본과 비교한다

  UX_SERIAL=... UX_DEVICE=... python3 wl/run_func.py matrix                 # 61개 함수 각 1회분, 대기 시나리오는 뒤로
  python3 wl/run_func.py matrix --only A1,B7t,C1                            # 고른 함수만
  python3 wl/run_func.py mix --name m1 --weight sns=0.4,video=0.6 --sec 7200 --seed 1

순서: funcs.bin push → 기기의 uxwl plan 으로 tc.bin·manifest 생성 → 회수 → run_tc.py (prep, Discard 대기, trace, compare).
matrix 는 .private/results/func-matrix.json 에 함수별 결과를 쌓고, 다시 돌리면 끝난 함수를 건너뛴다 (--redo 면 다시).
USB 전원이 들어와 있으면 멈춘다 (배터리 측정 규칙). 배터리가 --min-battery 아래로 내려가도 멈춘다.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIV = HERE / ".private"
RES = PRIV / "results"
PACK = PRIV / "funcs" / "funcs.bin"
MATRIX = RES / "func-matrix.json"
SERIAL = os.environ.get("UX_SERIAL", "192.168.1.20:5555")
DEV = "/data/local/tmp/uxwl"
LATE = ("S1", "S2", "S5")     # 긴 대기 시나리오는 뒤로


def adb(*a):
    for k in range(5):
        p = subprocess.run(["adb", "-s", SERIAL, *a], capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout
        print(f"adb 실패 ({k + 1}/5): {p.stderr.strip()[:200]}", flush=True)
        subprocess.run(["adb", "connect", SERIAL], capture_output=True)
        time.sleep(30)
    raise RuntimeError("adb 연결 실패")


def battery():
    d = {}
    for ln in adb("shell", "dumpsys battery").splitlines():
        k, _, v = ln.strip().partition(":")
        d[k] = v.strip()
    return int(d.get("level", -1)), d.get("AC powered") == "true" or d.get("USB powered") == "true"


def guard(a):
    lv, plugged = battery()
    if plugged:
        sys.exit("USB·AC 전원이 들어와 있어서 멈춰요. 빼고 다시 실행해 주세요")
    if lv < a.min_battery:
        sys.exit(f"배터리 {lv}% 라 멈춰요 (기준 {a.min_battery}%)")
    return lv


def prepare():
    subprocess.run(["make", "-s", "-C", str(HERE)], check=True)
    if not PACK.exists():
        subprocess.run([sys.executable, str(HERE / "gen_funcs.py")], check=True)
    adb("shell", f"mkdir -p {DEV}")
    adb("push", "-q", str(PRIV / "uxwl"), str(PACK), f"{DEV}/")
    adb("shell", f"chmod 755 {DEV}/uxwl")


def plan(name, *opts):
    src = PRIV / "tc" / name
    src.mkdir(parents=True, exist_ok=True)
    print(adb("shell", f"{DEV}/uxwl plan --root {DEV} --pack {DEV}/funcs.bin {' '.join(opts)}").strip(), flush=True)
    adb("pull", f"{DEV}/tc.bin", str(src / "tc.bin"))
    adb("pull", f"{DEV}/plan.json", str(src / "manifest.json"))
    return src


def run(name):
    before = set(RES.glob(f"{name}-*"))
    p = subprocess.run([sys.executable, str(HERE / "run_tc.py"), name], env=os.environ | {"UX_SERIAL": SERIAL})
    new = sorted(set(RES.glob(f"{name}-*")) - before)
    return p.returncode, new[-1] if new else None


def summary(out):
    cj = out / "compare.json"
    if not cj.exists():
        return None
    c = json.loads(cj.read_text())
    it = c["items"][0] if c["items"] else {}
    rj = out / "result.json"
    rs = json.loads(rj.read_text()) if rj.exists() else {}
    return {"errors": rs.get("errorKinds"), "sqlFrames": rs.get("sqlFrames"), "run": out.name, "pass": it.get("pass"), "of": it.get("of"), "fail": [k for k, v in it.get("checks", {}).items() if v["ok"] is False],
            "late": c["lateOver5ms"], "elapsedSec": c["elapsedSec"], "checks": it.get("checks")}


def cmd_matrix(a):
    idx = json.loads((PRIV / "seg" / "index.json").read_text())
    sids = sorted({v["sid"] for v in idx.values()}, key=lambda s: (s in LATE, s))
    if a.only:
        sids = a.only.split(",")
    m = json.loads(MATRIX.read_text()) if MATRIX.exists() else {}
    prepare()
    for sid in sids:
        if sid in m and m[sid].get("pass") is not None and not a.redo:
            continue
        lv = guard(a)
        name = f"f-{sid}"
        print(f"\n=== {time.strftime('%H:%M:%S')} {sid} (배터리 {lv}%) ===", flush=True)
        plan(name, f"--func {sid}", f"--rep {a.rep}")
        rc, out = run(name)
        s = summary(out) if out else None
        m[sid] = (s or {"pass": None, "error": f"run_tc 종료 코드 {rc}"}) | {"battery": lv, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "rep": a.rep}
        MATRIX.write_text(json.dumps(m, ensure_ascii=False, indent=1))
        print(f"--- {sid}: " + (f"통과 {s['pass']}/{s['of']}, 실패 {s['fail']}" if s else m[sid]["error"]), flush=True)
    done = [v for v in m.values() if v.get("pass") is not None]
    print(f"\n끝: 함수 {len(done)}/{len(m)}개, 통과 {sum(v['pass'] for v in done)}/{sum(v['of'] for v in done)}", flush=True)


def cmd_mix(a):
    prepare()
    guard(a)
    plan(a.name, f"--weight {a.weight}", f"--sec {a.sec}", f"--seed {a.seed}")
    rc, out = run(a.name)
    sys.exit(rc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-battery", type=int, default=15)
    sub = ap.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("matrix")
    x.add_argument("--only")
    x.add_argument("--rep", type=int, default=0)
    x.add_argument("--redo", action="store_true")
    x.set_defaults(fn=cmd_matrix)
    y = sub.add_parser("mix")
    y.add_argument("--name", required=True)
    y.add_argument("--weight", required=True)
    y.add_argument("--sec", type=float, default=7200)
    y.add_argument("--seed", type=int, default=1)
    y.set_defaults(fn=cmd_mix)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
