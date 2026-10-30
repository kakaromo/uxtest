#!/usr/bin/env python3
"""TC 검증 결과 → 분석 사이트용 공개 JSON (web/.private/data/tc.json, copy-data.mjs 가 static/data 로 복사)

  python3 wl/export_site.py            # report/export_web.py 가 끝에서 부른다

compare.json 에서 공개해도 되는 값만 뽑는다:
  - 지표별 전체 원본·TC 값과 판정 (total)
  - 지표별 구간 통과율 (items 의 ok 를 센 비율만. 구간 수·순서·길이는 내보내지 않음)
  - 카테고리별 통과 수/항목 수, 떨어진 항목 이름, FS Write·Flush/s 의 TC/원본 비율 (min 같은 시간 값은 내보내지 않음)
  - Run 요약: 구간 통과율, 전체 판정 수, 늦은 요청 비율, version
manifest.json(카테고리 비중), categories 의 min, items·settle·synth(구간 타임라인)는 사용 로그 데이터셋 모델에서 나오므로 쓰지 않는다.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import metrics as M  # noqa: E402

RES = HERE / ".private" / "results"
OUT = HERE.parent / "web" / ".private" / "data" / "tc.json"
# 사이트에 싣는 Run. version: compare.json 에 없으면 여기 값 (041017 은 v1 과 같은 코드, 011053 은 v1 이전 uxwl)
RUNS = [
    ("day6-20261030-011053", "pre-v1", "v1 이전 uxwl"),
    ("day6-20261030-041017", "v1", ""),
    ("day6-20261030-064621", "v1", ""),
]
# 카테고리 순서는 고정 (compare.json 의 순서는 하루 TC 안 순서라 쓰지 않음)
CATS = ["launch", "browser", "sns", "video", "music", "maps", "camera", "gallery", "mail_store", "productivity",
        "commerce", "home", "call", "daily", "standby"]
RATIO_KEYS = ("fsWriteMB", "flushPerSec")
SIZE_B = ["4K", "8–16K", "20–128K", "132–512K", ">512K"]
GAP_B = ["<1ms", "1–16ms", "16–200ms", "≥200ms"]


def rnd(v, n=3):
    if isinstance(v, list):
        return [rnd(x, 2) for x in v]
    return round(v, n) if isinstance(v, float) else v


def run_doc(name, version, note):
    d = json.loads((RES / name / "compare.json").read_text())
    res = json.loads((RES / name / "result.json").read_text())
    agg = {}
    for it in d["items"]:
        for k, c in it["checks"].items():
            a = agg.setdefault(k, [0, 0])
            if c["ok"] is not None:
                a[0] += bool(c["ok"])
                a[1] += 1
    cats = {}
    for c, v in d["categories"].items():
        cats[c] = {"pass": v["pass"], "of": v["of"], "fail": [k for k, x in v["checks"].items() if x["ok"] is False],
                   # 알려진 차이(GUIDE 9.2) 해설용: TC/원본 비율만 (원본·TC 값은 내보내지 않음)
                   "ratio": {k: v["checks"][k]["d"] for k in RATIO_KEYS}}
    return {
        "id": name, "version": d.get("version") or version, "note": note, "tcSha": d.get("tcSha"),
        "itemPassPct": round(100 * d["itemPass"] / d["itemOf"], 1),
        "totalPass": d["totalPass"], "totalOf": d["totalOf"],
        "latePct": round(100 * res["lateOver5ms"] / res["requests"], 2),
        "total": {k: {"orig": rnd(v["orig"]), "tc": rnd(v["tc"]), "d": v["d"], "ok": v["ok"]} for k, v in d["total"].items()},
        "itemPct": {k: (round(100 * a[0] / a[1], 1) if a[1] else None) for k, a in agg.items()},
        "cats": {c: cats[c] for c in CATS if c in cats},
    }


def export(out=OUT):
    runs = [run_doc(*r) for r in RUNS if (RES / r[0] / "compare.json").exists()]
    if not runs:
        print("TC 결과가 없어 tc.json 을 그대로 둬요")
        return
    shas = {r["tcSha"] for r in runs if r["tcSha"]}
    doc = {
        "version": M.VERSION, "tc": "day6", "tcSha": shas.pop() if len(shas) == 1 else None,
        "metrics": [{"key": k, "kind": kind, "th": th, "info": k in M.INFO,
                     **({"buckets": SIZE_B} if k in ("sizeR", "sizeW") else {"buckets": GAP_B} if k == "gap" else {})}
                    for k, kind, th in M.CHECKS],
        "cats": [c for c in CATS if any(c in r["cats"] for r in runs)],
        "runs": [{k: v for k, v in r.items() if k != "tcSha"} for r in runs],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    print(f"  tc.json: Run {len(runs)}개 {out.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    export()
