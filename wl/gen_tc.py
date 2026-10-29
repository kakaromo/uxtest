#!/usr/bin/env python3
"""조각 → TC (wl/.private/tc/<name>/{tc.bin, manifest.json})

  python3 wl/gen_tc.py seq --name cal-b7t B7t-2              # 보정용: 조각을 순서대로 (S5-1@0:1200 = 0~1200초만)
  python3 wl/gen_tc.py seq --name cal --rest 20 A1-1 B7t-2 C1-1
  python3 wl/gen_tc.py day --name day1 --seed 1                # 하루: 카테고리 가중치 × 사용 패턴
  python3 wl/gen_tc.py day --name sns --seed 1 --set sns=0.5 --hours 2

TC 형식은 wl/replay/main.go 머리 주석과 같다. manifest.timeline 의 각 구간은
  {i, seg, tcStart, srcFrom, srcTo} : TC 의 tcStart 초부터 조각 seg 의 [srcFrom, srcTo) 초를 재생
이라는 뜻이고, compare.py 가 이 구간으로 원본과 TC trace 를 잘라 비교한다.
"""
import argparse
import bisect
import json
import math
import random
import struct
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SEG = HERE / ".private" / "seg"
TCD = HERE / ".private" / "tc"
R, W, WB, WD, FS, DB, UNLINK, TRUNC, MARK, FA, WX, CP, TRIM, DS, SCREEN = 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14
SCREEN_OFF = ("S1", "S2", "S3", "S5")   # 화면을 끄고 잰 시나리오


_segs = {}


def load_seg(name):
    if name not in _segs:
        _segs[name] = dict(np.load(SEG / f"{name}.npz"))
    return _segs[name]


class Builder:
    def __init__(self):
        self.files = []        # (size, prefill)
        self.reqs = []         # (t_us, op, file, off, len)
        self.timeline = []
        self.created = []      # 재생 중 새로 만든 파일 (Discard 를 만들 때 지울 후보) [(file, size)]
        self.garbage = []      # 지울 후보가 모자랄 때 쓰는 미리 채운 파일
        self.last_trim = -10**12
        self.shared = {}       # (조각, 파일) → TC 파일: 원래 있던 파일은 같은 조각을 다시 써도 같은 파일 (미리 채우는 양을 줄임)

    def add_file(self, size, prefill):
        self.files.append([int(size), bool(prefill)])
        return len(self.files) - 1

    def add_segment(self, name, tc_start, src_from=0.0, src_to=None, **tag):
        a = load_seg(name)
        t = a["t"]
        src_to = float(t[-1]) + 1e-6 if src_to is None else src_to
        sel = (t >= src_from) & (t < src_to)
        i = len(self.timeline)
        self.timeline.append({"i": i, "seg": name, "tcStart": round(tc_start, 6), "srcFrom": round(src_from, 6),
                              "srcTo": round(src_to, 6)} | tag)
        self.reqs.append((int(tc_start * 1e6), MARK, i, 0, 0))
        # 조각 파일 → TC 파일 (구간마다 새로: 같은 조각을 다시 써도 서로 겹치지 않게). 구간에서 쓰는 파일만
        used = np.unique(a["f"][sel & ~np.isin(a["op"], [DB, CP, DS])])
        gid = {}
        for k in used:
            k = int(k)
            if a["file_existing"][k]:
                key = (name, k)
                if key not in self.shared:
                    self.shared[key] = self.add_file(a["file_size"][k], True)
                gid[k] = self.shared[key]
            else:
                gid[k] = self.add_file(a["file_size"][k], False)
        gone = set()
        for t_, op, f, off, ln in zip(t[sel], a["op"][sel], a["f"][sel], a["off"][sel], a["len"][sel]):
            ts = int((tc_start + t_ - src_from) * 1e6)
            if op == DB:
                self.discard(ts, int(ln))
            else:
                self.reqs.append((ts, int(op), gid.get(int(f), 0), int(off), int(ln)))
                if op == UNLINK:
                    gone.add(int(f))
        # 이 구간에서 새로 만들고 지우지 않은 파일은 뒤 구간의 Discard 때 지울 후보
        for k in gid:
            if not a["file_existing"][k] and k not in gone:   # 원래 있던(공유) 파일은 지우지 않는다
                self.created.append((gid[k], int(a["file_size"][k])))
        return float(src_to - src_from)

    def screen(self, tc_start, on):
        self.reqs.append((max(0, int(tc_start * 1e6) - 1), SCREEN, 1 if on else 0, 0, 0))

    def discard(self, ts, nbytes):
        """Discard 는 블록으로 재생하지 않는다. 그 양만큼 앞서 만든 파일을 1초 전에 지우고, 그 시각에 FITRIM 을 불러
        f2fs 가 직접 반납하게 한다. (원본 Discard 는 대기 중에만 나온다: 파일 삭제만으로는 바로 반납하지 않고,
        화면 꺼짐 idle maintenance 의 fstrim 같은 OS 동작이 내보낸다. 1초 안 Discard 는 FITRIM 한 번으로 묶음)"""
        if ts - self.last_trim > 1_000_000:
            self.reqs.append((ts, TRIM, 0, 0, 0))
            self.last_trim = ts
        ts = max(0, ts - 1_000_000)
        # f2fs discard_granularity(16블록=64KB) 보다 작게 풀린 조각은 FITRIM 으로도 반납되지 않는다 → 큰 파일부터 지운다.
        # (원본은 대기 중 f2fs_discard 가 4~32KB 로 냈다. 양은 맞추지만 Discard 크기 분포는 다르다)
        while nbytes > 0:
            big = [i for i, (_, sz) in enumerate(self.created) if sz >= 256 << 10]
            if big:
                f, s = self.created.pop(big[0])
            else:
                s = min(nbytes, 4 << 20)
                f = self.add_file(s, True)
                self.garbage.append(f)
            self.reqs.append((ts, UNLINK, f, 0, 0))
            nbytes -= s

    def write(self, name, meta):
        out = TCD / name
        out.mkdir(parents=True, exist_ok=True)
        self.reqs.sort(key=lambda r: r[0])
        with open(out / "tc.bin", "wb") as fo:
            fo.write(b"UXWL0001" + struct.pack("<IIQ", len(self.files), 0, len(self.reqs)))
            fo.write(b"".join(struct.pack("<QB", s, 1 if p else 0) for s, p in self.files))
            fo.write(b"".join(struct.pack("<QBIQI", *r) for r in self.reqs))
        ops = np.array([r[1] for r in self.reqs])
        ln = np.array([r[4] for r in self.reqs], np.float64)
        man = meta | {
            "timeline": self.timeline, "files": len(self.files),
            "prefillMB": round(sum(s for s, p in self.files if p) / 1e6, 1),
            "durSec": round(self.reqs[-1][0] / 1e6, 3), "requests": len(self.reqs),
            "MB": {k: round(float(ln[ops == v].sum()) / 1e6, 1) for k, v in (("R", R), ("W", W), ("WB", WB), ("WX", WX), ("WD", WD))},
            "fsync": int((ops == FS).sum()), "atomic": int((ops == FA).sum()), "ckpt": int((ops == CP).sum()), "dirsync": int((ops == DS).sum()), "trim": int((ops == TRIM).sum()), "unlink": int((ops == UNLINK).sum()), "garbageFiles": len(self.garbage),
        }
        (out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1))
        print(f"wrote {out}: {man['durSec']}s, 요청 {man['requests']}, 파일 {man['files']} (미리 채움 {man['prefillMB']}MB), "
              f"MB {man['MB']}, fsync {man['fsync']}, atomic {man['atomic']}, dirsync {man['dirsync']}, ckpt {man['ckpt']}, unlink {man['unlink']}")
        return out


def cmd_seq(a):
    b = Builder()
    t = a.lead
    for spec in a.segments:
        name, _, rng = spec.partition("@")    # S5-1@0:1200 = 조각의 0~1200초만
        lo, hi = (float(x) for x in rng.split(":")) if rng else (0.0, None)
        b.screen(t - a.rest / 2 if t > a.lead else 0, not name.startswith(SCREEN_OFF))
        t += b.add_segment(name, t, lo, hi) + a.rest
    b.write(a.name, {"mode": "seq", "segments": a.segments, "rest": a.rest, "lead": a.lead})


# ---------------- 하루 TC ----------------
QS = [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0]


def sampler(qv, lo=2.0, hi_mult=3.0):
    """분위수 [10,25,50,75,90,99%] 값 → 역누적분포 샘플러 (로그 공간 선형 보간)"""
    xs = [lo] + list(qv) + [qv[-1] * hi_mult]
    lx = [math.log(max(x, 1e-3)) for x in xs]
    return lambda u: math.exp(np.interp(u, QS, lx))


def pick(rng, d):
    keys = [k for k, v in d.items() if v > 0]
    return rng.choices(keys, [d[k] for k in keys])[0] if keys else None


def cmd_day(a):
    rng = random.Random(a.seed)
    usage = json.loads((HERE / ".private" / "usage.json").read_text())
    mix = json.loads((HERE / a.mix).read_text())
    idx = json.loads((SEG / "index.json").read_text())
    reps = {}
    for k, v in idx.items():
        reps.setdefault(v["sid"], []).append(k)

    # 1. 카테고리 가중치: null = 데이터셋, 숫자 = 사용자 값, --set 이 우선. 측정 조각이 없는 카테고리는 0
    cats = mix["categories"]
    target = {}
    for c, v in cats.items():
        w = v.get("weight")
        w = usage["categoryShareUserAvg"].get(c, 0) if w is None else w
        target[c] = w
    for kv in a.set or []:
        c, w = kv.split("=")
        target[c] = float(w)
    for c in target:
        if not cats.get(c, {}).get("db") and not any(s in reps for s in cats.get(c, {}).get("scenarios", {})):
            target[c] = 0
    tot = sum(target.values())
    target = {c: w / tot for c, w in target.items() if w > 0}

    vis = {c: sampler(usage["visitSecQ"][c]["p"]) for c in target if c in usage["visitSecQ"]}
    sess_s = sampler(usage["sessionSecQ"], lo=5)
    hourly = usage["hourly"]
    on_min = a.on_min or usage["perDay"]["onMinQ"][1]

    def plan_sessions():
        # 화면 켜짐 세션: 시각은 시간대별 세션 수, 길이는 세션 분위수 → 하루 화면 켜짐 합이 on_min 이 되게 늘이고 줄임
        hw = [hourly.get(str(h), {}).get("sessions", 0) for h in range(24)]
        n = max(1, round(usage["perDay"]["sessionsQ"][1]))
        st = sorted(h * 3600 + rng.random() * 3600 for h in rng.choices(range(24), hw, k=n))
        du = [sess_s(rng.random()) for _ in st]
        k = on_min * 60 / sum(du)
        sess, t = [], 0.0
        for s0, d in zip(st, du):
            s0 = max(s0, t + 30)
            sess.append((s0, d * k))
            t = s0 + d * k
        return sess

    def plan_visits(sess):
        """카테고리마다 목표 비중 × 화면 켜짐 시간만큼 방문을 먼저 만들고(길이는 데이터셋 방문 분위수),
        세션을 채울 때 다음 카테고리는 데이터셋 전이 확률 × 남은 할당량으로 고른다 → 비중은 목표대로, 순서는 실제 사용처럼"""
        T = sum(d for _, d in sess)
        left = {c: target[c] * T for c in target}
        out = []
        for s0, d in sess:
            prev, t = None, 0.0
            while t < d - 1 and any(v > 1 for v in left.values()):
                base = usage["transition"].get(prev, {}) if prev else usage["firstCategory"]
                c = pick(rng, {c: (base.get(c, 0) + 0.01) * left[c] for c in left if left[c] > 1})
                v = min(vis[c](rng.random()) if c in vis else 30, left[c], d - t)
                if v >= 3:
                    out.append((s0 + t, c, v))
                left[c] -= v
                t += v
                prev = c
        return out

    sess = plan_sessions()

    # 2. 하루 이벤트: 화면 켜진 방문 사이 무작위 시각
    events = []
    for sid, n in mix["daily"].items():
        k = int(n) + (1 if rng.random() < n - int(n) else 0)
        for _ in range(k):
            if sid in reps:
                events.append((rng.uniform(0, 86400), "daily", sid))

    # 3. TC 를 쓴다. 앱 사용 구간은 실제 길이, 화면 꺼짐은 압축.
    #    --hours 를 넘으면 하루 전체에 고르게 퍼진 순서로 세션을 골라 화면 켜짐 시간 예산까지만 쓴다 (시간대 모양 유지)
    launch = mix["launch"]
    n = len(sess)
    spread = sorted(range(n), key=lambda i: int(f"{i:016b}"[::-1], 2) if n else 0)   # 비트 반전 순서 = 고르게 퍼짐
    state = rng.getstate()

    def build(on_budget):
        rng.setstate(state)
        kept, acc = [], 0.0
        for i in spread:
            if acc >= on_budget:
                break
            if kept and acc + sess[i][1] > on_budget * 1.05:
                continue                        # 긴 세션 하나가 예산을 크게 넘기지 않게
            kept.append(sess[i])
            acc += sess[i][1]
        kept.sort()
        visits = plan_visits(kept)
        b = Builder()
        st = {"tc": 5.0}

        def seg(name, f0=0.0, f1=None, **tag):
            st["tc"] += b.add_segment(name, st["tc"], f0, f1, **tag)

        def add_standby(gap):
            b.screen(st["tc"], False)
            L = max(5.0, gap * a.standby_scale)
            band = next(x for x in mix["standby"] if gap <= x["maxSec"])
            sid = pick(rng, {k: v for k, v in band["scenarios"].items() if k in reps})
            name = rng.choice(reps[sid])
            dur = idx[name]["durSec"]
            while L > 0.5:
                w = min(L, dur)
                f0 = rng.uniform(0, max(0.0, dur - w))
                seg(name, f0, f0 + w, cat="standby", gapSec=round(gap, 1))
                L -= w

        dbs = {}

        def add_visit(c, v):
            if cats[c].get("db"):                  # DB 동작 모델 (측정 안 한 카테고리)
                p = cats[c]["db"]
                if c not in dbs:
                    dbs[c] = DB(b, p.get("mode", "wal"), p.get("kb", 12), p.get("dbKb", 8), rng=random.Random(a.seed * 7 + len(dbs)))
                st["tc"] += dbs[c].run(st["tc"], v, p.get("perMin", 30), cat=c)[0]
                return
            sid = pick(rng, {k: w for k, w in cats[c]["scenarios"].items() if k in reps})
            name = rng.choice(reps[sid])
            dur = idx[name]["durSec"]
            while v > 0.5:                     # 길면 이어 붙임 (새 파일로), 짧으면 앞에서부터 자름
                w = min(v, dur)
                seg(name, 0.0, w, cat=c)
                v -= w

        def add_launch():
            pool = launch["cold"] if rng.random() < launch["coldRatio"] else launch["warm"]
            sid = pick(rng, {k: v["w"] for k, v in pool.items() if k in reps})
            if sid:
                name = rng.choice(reps[sid])
                k, m = rng.randrange(pool[sid]["n"]), pool[sid]["n"]
                L = idx[name]["durSec"] / m
                seg(name, k * L, (k + 1) * L, cat="launch")

        ev_i = sorted(events)
        day_t = 0.0
        for s0, d in kept:
            if s0 > day_t:
                add_standby(s0 - day_t)
            prev_c = None
            b.screen(st["tc"], True)
            for vt, c, v in visits:
                if not (s0 <= vt < s0 + d):
                    continue
                while ev_i and ev_i[0][0] <= vt:
                    seg(rng.choice(reps[ev_i.pop(0)[2]]), cat="daily")
                if c != prev_c and c not in launch["skip"]:
                    add_launch()
                add_visit(c, v)
                prev_c = c
            day_t = s0 + d
        while ev_i:
            seg(rng.choice(reps[ev_i.pop(0)[2]]), cat="daily")
        if day_t < 86400:
            add_standby(86400 - day_t)
        return b, kept

    on_total = sum(d for _, d in sess)
    budget = on_total
    T = (a.hours or 0) * 3600
    best = None
    for _ in range(8):
        b, kept = build(budget)
        L = b.reqs[-1][0] / 1e6 if b.reqs else 0
        used = sum(d for _, d in kept)
        if a.verbose:
            print(f"  맞추기: 세션 예산 {budget:.0f}s → 세션 {len(kept)}개 {used:.0f}s, TC {L:.0f}s")
        if not T or L <= 1.03 * T and (best is None or L > best[0]):
            best = (L, b, kept)
        if not T or 0.95 * T <= L <= 1.03 * T or (L < T and budget >= on_total) or budget < 120:
            break
        fixed = L - used                       # 화면 꺼짐·앱 실행·하루 이벤트 (세션 수와 거의 무관)
        budget = min(on_total, max(120.0, used * max(0.05, (T - fixed) / max(used, 1)) * 0.99))
    if T and best:
        _, b, kept = best
    keep = sum(d for _, d in kept) / on_total

    got = {}
    for it in b.timeline:
        got[it["cat"]] = got.get(it["cat"], 0) + it["srcTo"] - it["srcFrom"]
    app_t = sum(v for c, v in got.items() if c in target)
    share = {c: round(got.get(c, 0) / app_t, 4) for c in target}
    meta = {"mode": "day", "seed": a.seed, "mix": a.mix, "set": a.set or [], "hours": a.hours, "standbyScale": a.standby_scale,
            "onMinPerDay": round(on_min, 1), "sessionKeep": round(keep, 3), "sessions": len(kept),
            "target": {c: round(w, 4) for c, w in target.items()}, "actual": share,
            "secByCategory": {c: round(v, 1) for c, v in sorted(got.items(), key=lambda x: -x[1])},
            "proxy": [c for c in target if cats.get(c, {}).get("proxy")],
            "dbModel": {c: cats[c]["db"] for c in target if cats.get(c, {}).get("db")}}
    b.write(a.name, meta)
    print("카테고리   목표   실제  (앱 사용 시간 기준)")
    for c in sorted(target, key=lambda c: -target[c]):
        print(f"  {c:13} {100 * target[c]:5.1f}% {100 * share[c]:5.1f}%{'  (대리)' if c in meta['proxy'] else ''}")
    print(f"세션 {len(kept)}/{len(sess)} 개 사용, 화면 켜짐 {sum(d for _, d in kept) / 60:.0f}분, 압축된 화면 꺼짐 {got.get('standby', 0) / 60:.0f}분")


# ---------------- DB 동작 (SQLite transaction 합성) ----------------
class DB:
    """SQLite 가 transaction 마다 내는 파일 동작을 그대로 만든다. 측정 안 한 앱(메시지 등)을 흉내 낼 때와
    "Checkpoint 표시 없이 원인만으로 FS I/O 가 나오는지" 검증할 때 쓴다.
      journal (rollback, DELETE): journal 생성·쓰기 → fsync → 디렉터리 fsync(DS) → header 4KB → DB 쓰기 → fsync → journal 삭제
      wal: WAL 덧붙이기 → fsync. WAL 이 ckptKB 를 넘으면 DB 로 옮겨 쓰고 fsync, WAL 은 처음부터 다시 씀
    시간 간격은 TikTok ttm_strategy.db(B7t) 에서 본 값: transaction 하나 약 2ms"""

    def __init__(self, b, mode="wal", kb=12, db_kb=8, db_size_kb=4096, ckpt_kb=4000, rng=None):
        self.b, self.mode, self.kb, self.db_kb, self.ckpt_kb = b, mode, kb, db_kb, ckpt_kb
        self.rng = rng or random.Random(0)
        self.dbf = b.add_file(db_size_kb * 1024, True)
        self.db_pages = db_size_kb // 4
        self.walf = b.add_file(max(ckpt_kb, kb) * 1024 + (1 << 20), False) if mode == "wal" else None
        self.wal_off = 0
        self.dirty = set()

    def _db_writes(self, ts, kb):
        for _ in range(max(1, kb // 4)):
            p = self.rng.randrange(self.db_pages)
            self.dirty.add(p)
            self.b.reqs.append((ts, WB, self.dbf, p * 4096, 4096))

    def tx(self, ts):
        us = lambda x: int(ts + x * 1000)  # noqa: E731  (ms → µs)
        b = self.b
        if self.mode == "journal":
            jf = b.add_file(self.kb * 1024 + 4096, False)
            b.reqs.append((us(0), WB, jf, 0, self.kb * 1024))
            b.reqs.append((us(0.1), FS, jf, 0, 0))
            b.reqs.append((us(0.15), DS, 0, 0, 0))
            b.reqs.append((us(1.0), WB, jf, 0, 4096))
            b.reqs.append((us(1.05), FS, jf, 0, 0))
            self._db_writes(us(1.3), self.db_kb)
            b.reqs.append((us(1.5), FS, self.dbf, 0, 0))
            b.reqs.append((us(1.8), UNLINK, jf, 0, 0))
        else:
            n = self.kb * 1024
            b.reqs.append((us(0), WB, self.walf, self.wal_off, n))
            b.reqs.append((us(0.1), FS, self.walf, 0, 0))
            self.wal_off += n
            for _ in range(max(1, self.kb // 4)):
                self.dirty.add(self.rng.randrange(self.db_pages))
            if self.wal_off >= self.ckpt_kb * 1024:          # WAL checkpoint
                for i, p in enumerate(sorted(self.dirty)):
                    b.reqs.append((us(1 + i * 0.01), WB, self.dbf, p * 4096, 4096))
                b.reqs.append((us(2 + len(self.dirty) * 0.01), FS, self.dbf, 0, 0))
                self.dirty.clear()
                self.wal_off = 0

    def run(self, tc_start, sec, per_min, cat="db"):
        """[tc_start, tc_start+sec) 동안 분당 per_min 번 transaction (지수 분포 간격)"""
        b = self.b
        i = len(b.timeline)
        b.timeline.append({"i": i, "seg": f"synth-db-{self.mode}", "tcStart": round(tc_start, 6), "srcFrom": 0.0,
                           "srcTo": round(sec, 6), "cat": cat, "synth": {"mode": self.mode, "kb": self.kb, "perMin": per_min}})
        b.reqs.append((int(tc_start * 1e6), MARK, i, 0, 0))
        t = tc_start
        n = 0
        while True:
            t += self.rng.expovariate(per_min / 60)
            if t >= tc_start + sec:
                break
            self.tx(t * 1e6)
            n += 1
        return sec, n


def cmd_dbtx(a):
    b = Builder()
    db = DB(b, a.mode, a.kb, a.db_kb, rng=random.Random(a.seed))
    _, n = db.run(5.0, a.sec, a.per_min)
    b.reqs.append((int((5 + a.sec + 5) * 1e6), MARK, len(b.timeline), 0, 0))
    b.write(a.name, {"mode": "dbtx", "db": vars(a) | {"fn": None}, "transactions": n})
    print(f"transaction {n}개 ({a.mode}, {a.kb}KB, 분당 {a.per_min})")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seq", help="조각을 순서대로 (보정용)")
    s.add_argument("--name", required=True)
    s.add_argument("--rest", type=float, default=20, help="조각 사이 쉬는 초")
    s.add_argument("--lead", type=float, default=5, help="처음 쉬는 초")
    s.add_argument("segments", nargs="+")
    s.set_defaults(fn=cmd_seq)
    d = sub.add_parser("day", help="하루 사용 흐름")
    d.add_argument("--name", required=True)
    d.add_argument("--seed", type=int, default=1)
    d.add_argument("--mix", default="mix.json")
    d.add_argument("--set", action="append", help="카테고리 가중치 덮어쓰기, 예: sns=0.4")
    d.add_argument("--hours", type=float, default=2.0, help="TC 길이 상한(시간). 넘으면 세션을 고르게 덜어 냄. 0 = 하루 전부")
    d.add_argument("--standby-scale", type=float, default=0.02, help="화면 꺼짐 압축 비율")
    d.add_argument("--on-min", type=float, help="하루 화면 켜짐 분 (기본: 데이터셋 중앙값)")
    d.add_argument("--verbose", action="store_true")
    x = sub.add_parser("dbtx", help="SQLite transaction 만 (DB 동작 검증용)")
    x.add_argument("--name", required=True)
    x.add_argument("--mode", choices=["journal", "wal"], default="journal")
    x.add_argument("--kb", type=int, default=24, help="transaction 하나의 journal/WAL 크기(KB)")
    x.add_argument("--db-kb", type=int, default=8, help="journal 방식에서 transaction 하나가 DB 에 쓰는 KB")
    x.add_argument("--per-min", type=float, default=600)
    x.add_argument("--sec", type=float, default=100)
    x.add_argument("--seed", type=int, default=1)
    x.set_defaults(fn=cmd_dbtx)
    d.set_defaults(fn=cmd_day)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
