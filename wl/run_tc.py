#!/usr/bin/env python3
"""TC 를 기기에서 재생하고 fsio_ufs trace 를 같이 잡은 뒤 원본과 비교한다

  python3 wl/run_tc.py cal-b7t            # wl/.private/tc/cal-b7t
  python3 wl/run_tc.py cal-b7t --no-trace # trace 없이 재생만

순서: adb push → uxwl prep (trace 밖) → agent 임시 시나리오 [sync, trace_start, uxwl run 백그라운드,
TC 길이만큼 sleep, 끝날 때까지 확인, trace_stop] → result.json 회수 → compare.py.
uxwl 은 백그라운드로 띄우고 sleep Step 으로 기다려서 agent shell Step 시간 제한과 상관없이 긴 TC 도 돈다.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "report"))
import run as agent  # noqa: E402  (run.py: call, DEVICE)
import extract  # noqa: E402

SERIAL = os.environ.get("UX_SERIAL", "3C1677001HN00000")
DEV = "/data/local/tmp/uxwl"
TCD = HERE / ".private" / "tc"
RES = HERE / ".private" / "results"


def adb(*a, check=True):
    return subprocess.run(["adb", "-s", SERIAL, *a], capture_output=True, text=True, check=check).stdout


def step(type_, label, **p):
    return {"type": type_, "params": {k: str(v) for k, v in p.items()} | {"label": label}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tc")
    ap.add_argument("--no-trace", action="store_true")
    ap.add_argument("--speed", type=float, default=1)
    ap.add_argument("--max-qd", type=int, default=256)
    ap.add_argument("--cleanup", action="store_true", help="끝나고 재생 파일 삭제")
    a = ap.parse_args()
    src = TCD / a.tc
    man = json.loads((src / "manifest.json").read_text())
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = RES / f"{a.tc}-{stamp}"
    out.mkdir(parents=True)
    for f in ("manifest.json", "tc.bin"):
        shutil.copy(src / f, out / f)

    subprocess.run(["make", "-s", "-C", str(HERE)], check=True)   # uxwl 최신으로
    adb("shell", f"mkdir -p {DEV}")
    adb("push", "-q", str(HERE / ".private" / "uxwl"), str(src / "tc.bin"), f"{DEV}/")
    adb("shell", f"chmod 755 {DEV}/uxwl; rm -f {DEV}/result.json {DEV}/done")
    # 앞 TC 가 남긴 재생 파일을 지우고 새로 채운다. 지운 공간의 Discard 는 f2fs 가 idle 때 알아서 내는데, 바로 측정하면
    # 그게 측정 앞부분에 섞이므로 (cal3: 첫 구간에 원본에 없던 Discard 2.9GB) pending_discard 가 0 이 될 때까지 기다린다.
    # FITRIM·f2fs 설정 변경으로 억지로 비우지 않는다
    adb("shell", f"{DEV}/uxwl clean --root {DEV}")
    print(adb("shell", f"{DEV}/uxwl prep --root {DEV} {DEV}/tc.bin").strip())
    t_wait = time.time()
    while True:
        pend = adb("shell", "sync; cat /sys/fs/f2fs/*/pending_discard 2>/dev/null").split()
        pend = sum(int(x) for x in pend if x.isdigit())
        if pend == 0 or time.time() - t_wait > 900:
            break
        time.sleep(10)
    print(f"Discard 대기 {time.time() - t_wait:.0f}s, 남은 pending_discard {pend}", flush=True)
    run_cmd = (f"cd {DEV} && (./uxwl run --root {DEV} --speed {a.speed} --max-qd {a.max_qd} tc.bin > run.log 2>&1; "
               "touch done) &")
    dur = man["durSec"] / a.speed

    if a.no_trace:
        adb("shell", "sync")
        adb("shell", run_cmd.replace(" &", ""))
        info = {"pq": None}
    else:
        steps = [
            step("shell", "sync", cmd="sync"),
            step("trace_start", "측정 시작", trace_type="fsio_ufs", window_seconds=1, include_vfs="false", include_dram="false"),
            step("shell", "uxwl 재생 시작", cmd=f"nohup sh -c '{run_cmd[:-2]}' >/dev/null 2>&1 &"),
            step("sleep", "TC 재생 대기", seconds=int(dur) + 2),
            step("shell", "재생 끝 확인", cmd=f"for i in $(seq 120); do [ -e {DEV}/done ] && break; sleep 1; done; cat {DEV}/run.log"),
            step("sleep", "writeback 배수 대기", seconds=3),
            step("trace_stop", "측정 종료", trace_type="fsio_ufs"),
        ]
        body = {"deviceIds": [agent.DEVICE], "scenarioName": f"uxwl-{a.tc}", "steps": steps, "loops": [], "repeat": 1,
                "busyPolicy": "wait"}
        r = agent.call("POST", "/api/agent/scenario/run", body)
        if "jobId" not in r:
            sys.exit(f"agent 실행 요청 실패: {r}")
        job = r["jobId"]
        print(f"[{a.tc}] job {job} 시작, TC {dur:.0f}초", flush=True)
        while True:
            st = agent.call("GET", f"/api/agent/benchmark/status?jobId={job}")
            if st.get("state") in ("completed", "failed", "cancelled"):
                break
            time.sleep(5)
        res = agent.call("GET", f"/api/agent/benchmark/result?jobId={job}&deviceId={agent.DEVICE}")
        x = (res.get("results") or [{}])[0]
        tjs = x.get("traceJobs") or []
        if st.get("state") != "completed" or not tjs:
            sys.exit(f"agent 실패: {st.get('state')} {x.get('error', '')[:300]}")
        tid = tjs[0]["traceJobId"]
        pq = None
        for _ in range(60):                     # parquet 변환 대기
            pq = extract.parquet_of(tid)
            if pq:
                break
            time.sleep(5)
        info = {"jobId": job, "traceJobId": tid, "pq": pq, "rawOutput": x.get("rawOutput", "")}
        print(x.get("rawOutput", "").strip()[-600:])
    (out / "run.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
    adb("pull", f"{DEV}/result.json", str(out / "result.json"))
    r = json.loads((out / "result.json").read_text())
    print(f"재생 {r['elapsedSec']:.1f}s / 예정 {r['scheduledSec']:.1f}s, 늦음(>5ms) {r['lateOver5ms']}, qdMax {r['qdMax']}")
    if a.cleanup:
        adb("shell", f"{DEV}/uxwl clean --root {DEV}")
    if info["pq"]:
        subprocess.run([sys.executable, str(HERE / "compare.py"), str(out)], check=True)


if __name__ == "__main__":
    main()
