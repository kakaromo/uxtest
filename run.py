#!/usr/bin/env python3
"""시나리오 실행기 — agent(standalone) 에 시나리오를 돌리고 결과를 runs/ 에 남긴다.

  ./run.py A1 B2            # 시나리오에 적힌 repeatCount 대로 (본 측정)
  ./run.py --dry A1 B2      # 1회만 (dry-run: 스텝·요소·좌표 점검)
  ./run.py --dry --all-p1   # P1 전부 (--all-p2 는 P2)

결과: runs/<ID>/<시각>[-dry].json  (rawOutput, traceJobs, 스텝 오류 요약)
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

AGENT = os.environ.get("UX_AGENT", "http://127.0.0.1:50051")
DEVICE = os.environ.get("UX_DEVICE", "2-1.1.3")
HERE = os.path.dirname(os.path.abspath(__file__))
DEV_OUT = "/dev/ux"  # gen.py 의 DEV_OUT 과 같아야 한다


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(AGENT + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}") | {"_http": e.code}


def find(sid):
    hits = glob.glob(os.path.join(HERE, "scenarios", "*", f"{sid}.scenario.json"))
    if not hits:
        sys.exit(f"시나리오 없음: {sid}")
    return hits[0]


def summarize(raw):
    """rawOutput 에서 사람이 볼 줄만 뽑는다: 실패 스텝, 포커스, trace 시작/종료."""
    keep = []
    for line in raw.splitlines():
        if re.search(r"(?i)error|fail|not found|timeout|killed|mCurrentFocus|TRACE_ST|CAPTURED", line):
            keep.append(line.strip()[:220])
    return keep


def pull_dev_out(dst):
    """Perfetto·gfxinfo 결과(tmpfs /dev/ux)를 PC 로 가져오고 기기에서 지운다.

    tmpfs 는 RAM 이라 쌓아 두면 메모리를 먹고, 재부팅하면 사라진다."""
    serial = os.environ.get("UX_SERIAL", "3C1677001HN00000")
    adb = ["adb", "-s", serial]
    names = subprocess.run(adb + ["shell", f"ls {DEV_OUT} 2>/dev/null"], capture_output=True, text=True).stdout.split()
    if not names:
        return ""
    os.makedirs(dst, exist_ok=True)
    for n in names:
        subprocess.run(adb + ["pull", f"{DEV_OUT}/{n}", dst], capture_output=True, check=True)
    subprocess.run(adb + ["shell", f"rm -rf {DEV_OUT}/*"], check=True)
    return ", ".join(names)


def run(sid, dry):
    path = find(sid)
    sc = json.load(open(path))
    repeat = 1 if dry else sc.get("repeatCount", 1)
    body = {"deviceIds": [DEVICE], "scenarioName": sc["name"] + (" (dry)" if dry else ""),
            "steps": sc["steps"], "loops": sc.get("loops", []), "repeat": repeat,
            "busyPolicy": "wait"}
    r = call("POST", "/api/agent/scenario/run", body)
    if "jobId" not in r:
        print(f"[{sid}] 실행 요청 실패: {r}")
        return False
    job = r["jobId"]
    print(f"[{sid}] job {job} 시작 (repeat {repeat}, 스텝 {len(sc['steps'])})", flush=True)
    # keepAwake: 화면을 보며 기다리는 시나리오(녹음, 다운로드 대기). 배터리 상태에선 입력 없이 30초면 화면이 꺼져
    # 다음 tap 이 잠금 화면에 눌린다. 설정은 바꾸지 않고 10초마다 WAKEUP 키와 잠금 해제(보안 잠금 아님)로 켜 둔다
    awake = None
    if sc.get("keepAwake"):
        serial = os.environ.get("UX_SERIAL", "3C1677001HN00000")
        awake = subprocess.Popen(["adb", "-s", serial, "shell", "while true; do input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; sleep 10; done"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0, last = time.time(), None
    while True:
        st = call("GET", f"/api/agent/benchmark/status?jobId={job}")
        ds = (st.get("deviceStatuses") or [{}])[0]
        msg = f"{st.get('state')} {ds.get('progressPercent', 0):.0f}% {ds.get('message', '')}"
        if msg != last:
            print(f"  {time.time() - t0:6.0f}s  {msg[:160]}", flush=True)
            last = msg
        if st.get("state") in ("completed", "failed", "cancelled"):
            break
        time.sleep(5)
    if awake:
        awake.kill()
    res = call("GET", f"/api/agent/benchmark/result?jobId={job}&deviceId={DEVICE}")
    results = res.get("results") or [{}]
    out = {"scenario": sid, "file": os.path.relpath(path, HERE), "jobId": job, "dry": dry,
           "state": st.get("state"), "elapsedSec": round(time.time() - t0),
           "results": results}
    d = os.path.join(HERE, "runs", sid)
    os.makedirs(d, exist_ok=True)
    fn = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + ("-dry" if dry else "") + ".json")
    json.dump(out, open(fn, "w"), ensure_ascii=False, indent=1)
    pulled = pull_dev_out(fn[:-5])
    if pulled:
        print(f"  기기 /dev/ux → {os.path.relpath(fn[:-5], HERE)}/ ({pulled})")
    ok =st.get("state") == "completed" and all(x.get("success") for x in results)
    print(f"[{sid}] {'성공' if ok else '실패'} {out['elapsedSec']}s → {os.path.relpath(fn, HERE)}")
    for x in results:
        if x.get("error"):
            print(f"  error: {x['error'][:300]}")
        for tj in x.get("traceJobs") or []:
            print(f"  trace {tj['traceJobId']} repeat={tj.get('repeatIndex')} loop={tj.get('loopIndex')} {tj.get('traceType')}")
        for line in summarize(x.get("rawOutput", ""))[-25:]:
            print("  |", line)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--dry", action="store_true", help="1회만 실행")
    ap.add_argument("--all-p1", action="store_true")
    ap.add_argument("--all-p2", action="store_true")
    ap.add_argument("--rest", type=int, default=30, help="시나리오 사이 휴지(초)")
    a = ap.parse_args()
    ids = list(a.ids)
    for prio in [n for n, on in ((1, a.all_p1), (2, a.all_p2)) if on]:
        for p in sorted(glob.glob(os.path.join(HERE, "scenarios", "*", "*.scenario.json"))):
            if f"· P{prio}]" in json.load(open(p)).get("description", ""):
                ids.append(os.path.basename(p).split(".")[0])
    fails = []
    for i, sid in enumerate(ids):
        if i:
            time.sleep(a.rest)
        if not run(sid, a.dry):
            fails.append(sid)
    if fails:
        print("실패:", " ".join(fails))
        sys.exit(1)


if __name__ == "__main__":
    main()
