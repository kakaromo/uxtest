#!/usr/bin/env python3
"""report/data.json → report/report.html (보고서 형식, Artifact 로 발행)

  python3 report/extract.py && python3 report/build_report.py

표·본문은 여기서 정적으로 만들고, 차트만 ECharts 로 그린다 (데이터는 페이지에 넣는다).
본문 숫자는 가능한 한 data.json 에서 꺼내 쓴다. 해석 문장은 P1·P2 측정(2026-10-25) 기준으로 썼다.
A4 의 앱별 구간 읽기는 report/perstep.py 로 뽑았다.
"""
import html
import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).parent
D = json.loads((HERE / "data.json").read_text())
S = {s["key"]: s for s in D["scenarios"]}
J = {(j["scenario"], j["repeat"]): j for j in D["jank"]}
ORDER = [s["key"] for s in D["scenarios"]]
E = html.escape


def med(k, f, d=None):
    v = S[k][f][d] if d else S[k][f]
    return v["med"] if isinstance(v, dict) else v


def mb(x):
    return f"{x / 1000:.2f} GB" if x >= 1000 else f"{x:.0f} MB" if x >= 10 else f"{x:.1f} MB"


def rng(k, f):
    v = S[k][f]
    if v["min"] == v["max"] or S[k]["repeats"] < 2:
        return mb(v["med"])
    return f'{mb(v["med"])} <span class="rg">{v["min"]:.0f}–{v["max"]:.0f}</span>'


def label(s):
    n = s["name"].replace("[UX-fsio] ", "").split(" ", 1)[1]
    return n + (f' · {s["cache"]}' if s["cache"] else "")


# ── 시나리오 표 ────────────────────────────────────────────────────────────
DOING = {
    "A1": "캐시 비우기 → Chrome 강제 종료 후 실행, 5번",
    "A2": "앱마다 캐시 비우기 → cold start: Chrome, YouTube, 설정, 갤러리, 카메라, 지도",
    "A3": "Chrome·YouTube·설정을 띄워 둔 채 오가며 짧게 스크롤 (warm)",
    "B1": "영문 위키 문서 2개를 열고 8번씩 스크롤 (회차마다 디스크 캐시 비움)",
    "B2": "YouTube 검색 → 결과 스크롤 (회차마다 이미지 캐시 비움)",
    "B3": "YouTube 홈피드 1.5초 간격 40번 스크롤",
    "B7": "Instagram 홈 피드 1.5초 간격 40번 스크롤 (탭 없음)",
    "B7r": "Instagram 릴스 20개를 5초씩 보며 넘기기 (탭 없음)",
    "B7t": "TikTok 추천 영상 20개를 5초씩 보며 넘기기 (탭 없음)",
    "B7y": "YouTube Shorts 20개를 5초씩 보며 넘기기 (탭 없음)",
    "C1": "YouTube 일반 영상 3분 재생 (화질 자동, Premium)",
    "C2": "Shorts 3초씩 보고 넘기기 30번",
    "C3": "캐시 비우기 → 2분 촬영 영상(230MB)을 시스템 동영상 앱으로 재생",
    "D1": "워밍업 1장 뒤 2초 간격 사진 10장",
    "D2": "셔터 3초 길게 눌러 버스트",
    "D3": "동영상 30초 녹화 (1920×1080)",
    "E2": "/sdcard 의 512MB 파일 복사 (원본 생성·캐시 비우기는 측정 밖)",
    "E3": "설치된 Instagram 을 같은 APK 로 재설치 (pm install -r)",
    "E4": "YouTube·Chrome 캐시를 채운 뒤 pm trim-caches",
    "G1": "캐시 비우기 → NASA 1000장 그리드를 처음부터 끝까지 스크롤",
    "G2": "캐시 비우기 → 뷰어에서 0.5초 간격으로 999번 다음 사진",
    # P2
    "A4": "앱마다 캐시 비우기 → cold start: 지도, Facebook(로그아웃 화면), Instagram(약관 화면)",
    "A5": "6개 앱을 띄워 둔 뒤 최근 앱 화면에서 이전 앱 카드 열기, 6번",
    "A6": "날씨 앱 pm clear 직후 첫 실행",
    "A7": "YouTube 를 띄워 둔 채 홈↔앱 10번",
    "A8": "YouTube 를 띄우고 다른 앱 3개를 거쳐 5분 뒤 복귀 (복귀 구간만 측정)",
    "B1i": "B1 과 같은 위키 2개를 시크릿 탭에서",
    "B4": "시크릿 탭 5개에 위키 문서를 열고 주소창 스와이프로 탭 8번 전환",
    "B5": "이미지 200여 개 위키 문서(국기 갤러리) 30번 스크롤 (디스크 캐시 비움)",
    "B6": "지도 캐시 비우기 → 좌표로 서울시청 열기 → 이동 5번·두 번 탭 확대 5번",
    "B8": "Gmail 받은편지함 30번 내리고 다시 올리기 (메일은 열지 않음)",
    "B9": "Play 스토어 캐시 비우기 → 홈 추천 25번·인기 차트 15번 스크롤",
    "C4a": "C1 과 같은 방식, 화질 360p 고정 3분",
    "C4b": "C1 과 같은 방식, 화질 1080p 고정 3분",
    "C5": "재생 중 플레이어 연속 탭으로 앞으로 40초·뒤로 20초, 번갈아 10번",
    "C6": "YouTube Music 곡 하나 3분 재생",
    "C7": "캐시 비우기 → C3 영상의 진행 막대 10곳으로 건너뛰기",
    "D4": "동영상 2분 녹화 (1080p)",
    "D5": "동영상 30초 녹화 (4K, 측정 뒤 1080p 로 되돌림)",
    "D6": "사진 5장 → 바로 최근 사진 버튼으로 뷰어에서 5장 넘기기",
    "D7": "전면 카메라로 2초 간격 5장",
    "D8": "촬영 없이 사진↔동영상 모드 5번 전환",
    "D9": "screenrecord 1분 (설정 화면 스크롤하며)",
    "E1": "갤러리 그리드 20번 스크롤 + 사진 5장 (warm)",
    "E5": "/sdcard 에 4KB 파일 1000개 만들고 지우기",
    "E6": "1GB 파일 지우기 (만들기는 측정 밖)",
    "E7": "파일 관리자에서 256MB 파일을 Documents 로 복사",
    "E8": "Chrome 으로 100MB 파일 다운로드 (OVH 공개 시험 파일)",
    "F1": "메모 앱에 약 500자 입력 → 저장 (측정 뒤 삭제)",
    "F2": "녹음기 1분 녹음 (측정 뒤 삭제)",
    "F4": "연락처 검색(010) → 목록 10번 스크롤",
    "F5": "캘린더 월 보기에서 12달 넘기기",
    "G3": "캐시 비우기 → 그리드를 빠른 fling 40번으로 끝까지",
    "G4": "캐시 비우기 → 뷰어에서 0.15초 간격으로 300장 넘기기",
    "G5": "캐시 비우기 → 사진마다 두 번 탭 확대·이동 후 다음 사진, 20장",
    "G6": "사진 탭 맨 앞 20장 선택 삭제 → 최근 삭제된 항목 비우기",
    # 대기 (2026-10-26, 무선 adb)
    "S1": "YouTube·Chrome·Gmail·지도를 띄워 둔 뒤 화면을 끄고 30분",
    "S2": "S1 과 같은 상태에서 deep doze 로 강제 진입시키고 30분",
    "S3": "앱 4개를 띄워 둔 채 측정을 켜고 화면을 끈 뒤 5분",
    "S4": "앱 4개를 띄워 둔 뒤 홈 화면을 켜 둔 채 입력 없이 10분",
    "S5": "앱을 따로 띄우지 않고 홈에서 화면을 끄고 3시간 (Deep Sleep 끄고 다시 잼)",
}


def check_text(s):
    ck = s["checks"]
    caps = [v["captured"] for v in ck.values() if v.get("captured")]
    if caps:
        files = [c.split()[0].split("=")[1] for c in caps]
        kb = [int(c.split("kb=")[1]) for c in caps]
        return f'저장 {"/".join(files)}개 · {sum(kb) / len(kb) / 1024:.0f}MB'
    foc = {v["focus"] for v in ck.values() if v.get("focus")}
    if foc:
        f = next(iter(foc))
        pkg, _, act = f.partition("/")
        return f'화면 {E(act.split(".")[-1])} <span class="muted">({E(pkg)})</span>'
    return '<span class="muted">셸 동작 (화면 없음)</span>'


def scen_table():
    out, cur, seen = [], None, set()
    for s in D["scenarios"]:
        if s["id"] in seen:
            continue
        seen.add(s["id"])
        if s["type"] != cur:
            cur = s["type"]
            out.append(f'<tr class="grp"><th colspan="6">{s["type"]} · {E(s["typeName"])}</th></tr>')
        out.append(f"""<tr><td class="id"><a href="s-{s['id']}.html">{s['id']}</a></td><td>{E(label(s).split(' · ')[0])}</td><td>{E(DOING[s['id']])}</td>
            <td class="num">{med(s['key'], 'durSec'):.0f}</td><td>{check_text(s)}</td>
            <td class="num">{f'<span class="ok">{s["repeats"]}/{s["repeats"]}</span>' if s['success'] else '<span class="bad">중간에 끊김</span>'}</td></tr>""")
    return "\n".join(out)


# ── UFS 관리 명령 (mgmt) ────────────────────────────────────────────────────
MG = [x for x in D["scenarios"] if x["cache"] != "cold"]
MG_ON = [x for x in MG if x["type"] != "S"]
MG_OFF = [x for x in MG if x["type"] == "S" and x["id"] != "S4"]


def mrng(rows, f, d=0):
    v = [x[f]["med"] for x in rows]
    return f"{min(v):.{d}f}~{max(v):.{d}f}"


# 시나리오 ID → 이름 (본문에 ID 대신 쓴다)
NAME = {x["id"]: x["name"].replace("[UX-fsio] ", "").split(" ", 1)[1] for x in D["scenarios"]}


def nm(key):
    """시나리오 key(ID 또는 ID-cold/warm) → 이름"""
    sid, _, cache = key.partition("-")
    return NAME.get(sid, sid) + (f" {cache}" if cache else "")


def mtop(rows, f, n=4, rev=True):
    return ", ".join(f'{nm(x["key"].replace("-warm", ""))} {x[f]["med"]:.0f}' for x in sorted(rows, key=lambda x: x[f]["med"], reverse=rev)[:n])


def mgsum(rows, name):
    return sum(x["mgmtN"].get(name, 0) for x in rows)


mg_exit = st.median(x["h8ExitMs"]["med"] for x in MG)
mg_enter = st.median(x["h8EnterMs"]["med"] for x in MG)
mg_q50 = st.median(x["queryMsP50"]["med"] for x in MG)
mg_q99 = st.median(x["queryMsP99"]["med"] for x in MG)
mg_bk = st.median(x["bkopsPerMin"]["med"] / x["h8PerMin"]["med"] for x in MG if x["h8PerMin"]["med"])
mg_names = {}
for x in D["scenarios"]:
    for k, v in x["mgmtN"].items():
        mg_names[k] = mg_names.get(k, 0) + v


def mgmt_type_table():
    out = []
    for t, n in D["types"].items():
        rows = [x for x in MG if x["type"] == t]
        if not rows:
            continue
        out.append(f"""<tr><td class="id">{t}</td><td>{E(n)}</td><td class="num">{mrng(rows, 'h8PerMin')}</td>
          <td class="num">{mrng(rows, 'h8Pct')}%</td><td class="num">{mrng(rows, 'queryPerMin')}</td>
          <td class="num">{mrng(rows, 'wbCheckPerMin')}</td><td class="num">{sum(mgsum([x], 'Clear Flag(fBackgroundOpsEn)') for x in rows)}</td></tr>""")
    return "\n".join(out)


def mgmt_table():
    out, cur = [], None
    for x in D["scenarios"]:
        k = x["key"]
        if x["type"] != cur:
            cur = x["type"]
            out.append(f'<tr class="grp"><th colspan="9">{x["type"]} · {E(x["typeName"])}</th></tr>')
        out.append(f"""<tr><td class="id"><a href="s-{x['id']}.html">{x['id']}</a>{'<span class="tag">' + x['cache'] + '</span>' if x['cache'] else ''}</td>
          <td class="num">{med(k, 'h8PerMin'):.0f}</td><td class="num">{med(k, 'h8Pct'):.0f}%</td>
          <td class="num">{med(k, 'h8ExitMs'):.2f}</td><td class="num">{med(k, 'queryPerMin'):.0f}</td>
          <td class="num">{med(k, 'bkopsPerMin'):.0f}</td><td class="num">{med(k, 'wbCheckPerMin'):.0f}</td>
          <td class="num">{mgsum([x], 'Clear Flag(fBackgroundOpsEn)')}</td><td class="num">{mgsum([x], 'Write Attribute(qTimestamp)')}</td></tr>""")
    return "\n".join(out)


def sig_table(only=None):
    out, cur = [], None
    for s in D["scenarios"]:
        if only and s["type"] != only:
            continue
        k = s["key"]
        if s["type"] != cur:
            cur = s["type"]
            out.append(f'<tr class="grp"><th colspan="12">{s["type"]} · {E(s["typeName"])}</th></tr>')
        r, w = med(k, "readMB"), med(k, "writeMB")
        st = s["rep"]["streams"][:2]
        sts = " ".join(f'<span class="stream {x["dir"]}">{x["seq"]} {x["size"]} {x["dir"]} {x["pct"]:.0f}%</span>' for x in st)
        out.append(f"""<tr><td class="id"><a href="s-{s['id']}.html">{s['id']}</a>{'<span class="tag">' + s['cache'] + '</span>' if s['cache'] else ''}</td>
          <td class="num">{rng(k, 'readMB')}</td><td class="num">{rng(k, 'writeMB')}</td>
          <td class="num">{100 * w / (r + w) if r + w else 0:.0f}%</td>
          <td class="num">{med(k, 'peakMBs'):.0f}</td>
          <td class="num">{med(k, 'seq', 'R'):.0f}% / {med(k, 'seq', 'W'):.0f}%</td>
          <td class="num">{med(k, 'dtocP99', 'R'):.2f} / {med(k, 'dtocP99', 'W'):.2f}</td>
          <td class="num">{med(k, 'qdP99'):.0f}</td><td class="num">{med(k, 'metaPct'):.0f}%</td>
          <td class="num">{med(k, 'idlePct'):.0f}%</td>
          <td class="num {'warn' if s['cv'] > 0.5 else ''}">{s['cv']:.2f}</td><td class="streams">{sts}</td></tr>""")
    return "\n".join(out)


def proc_table():
    out = []
    for s in D["scenarios"]:
        ps = s["rep"]["procs"][:4]
        cells = "".join(f'<li><span class="pn">{E(p["name"])}</span> <span class="num">R {p["readMB"]:.0f} · W {p["writeMB"]:.0f}</span></li>' for p in ps)
        out.append(f'<tr><td class="id">{s["id"]}{"<span class=tag>" + s["cache"] + "</span>" if s["cache"] else ""}</td><td class="num">{s["rep"]["repeat"]}회차</td><td><ul class="plist">{cells}</ul></td></tr>')
    return "\n".join(out)


def jank_table():
    out = []
    for (sid, rep), j in sorted(J.items()):
        if "jank" not in j:
            continue
        g = j["gfx"] or {}
        out.append(f"""<tr><td class="id">{sid}<span class="tag">{j['cache']}</span></td><td class="num">{rep}</td>
          <td class="num">{j['total']:,}</td><td class="num">{j['jank']['frames']} <span class="rg">({100 * j['jank']['frames'] / j['total']:.2f}%)</span></td>
          <td class="num">{j['frameDurP50']:.1f} / {j['frameDurP99']:.1f}</td><td class="num">{g.get('p90', '–')} / {g.get('p99', '–')}</td>
          <td class="num">{j['jank']['readsPerFrame']:.2f} / {j['normal']['readsPerFrame']:.2f}</td>
          <td class="num">{j['jank']['withReadPct']:.0f}% / {j['normal']['withReadPct']:.0f}%</td></tr>""")
    return "\n".join(out)


# ── 본문에 쓰는 값 ───────────────────────────────────────────────────────
def capkb(k):
    caps = [v["captured"] for v in S[k]["checks"].values() if v.get("captured")]
    return sum(int(c.split("kb=")[1]) for c in caps) / len(caps) / 1024


d1_ratio = med("D1", "writeMB") / capkb("D1")
d2_ratio = med("D2", "writeMB") / capkb("D2")
d3_ratio = med("D3", "writeMB") / capkb("D3")
d1_per = med("D1", "writeMB") / 10   # 측정 구간 촬영 10장 (워밍업 1장은 구간 밖)
d1_jpg = capkb("D1") / 11            # 저장 파일 11장 = 워밍업 1 + 10
a1_chrome = next(p for p in S["A1"]["rep"]["procs"] if "chrome" in p["name"])["readMB"]
g2w = J[("G2", 2)]
g2c = J[("G2", 1)]
cv_hi = [s["key"] for s in D["scenarios"] if s["cv"] > 0.5]
n_ids = len({s["id"] for s in D["scenarios"]})
n_p1 = len({s["id"] for s in D["scenarios"] if s["prio"] == 1})
d7_per = med("D7", "writeMB") / 5


# 수집 도구 귀속 수정(2026-10-28) 뒤 다시 잰 시나리오. 이름·flag 에 기대는 문장은 아래 REVIEWED 에 넣기 전까지 '확인 중' 표시
FIXED = sorted({x["id"] for x in D["scenarios"] if x.get("toolFixed")})
OLD = sorted({x["id"] for x in D["scenarios"] if not x.get("toolFixed")})
REVIEWED = {"D1", "D8", "A1", "B1", "B3", "B7t", "C3"}   # 새 도구 측정으로 다시 확인한 문장의 시나리오 ID (10-28 trace-analyst 검증)


def chk(*sids):
    """파일·프로세스 이름이나 NODE/META/fsync 표시에 기대는 문장 뒤에 붙인다. 다시 확인 전이면 표시"""
    return "" if all(x in REVIEWED for x in sids) else ' <span class="tag">확인 중</span>'


def jank_rng(sid):
    """끊긴 프레임 비율(%) 회차 최소~최대. 프레임 기록이 없는 회차는 뺀다"""
    v = [100 * j["jank"]["frames"] / j["total"] for j in D["jank"] if j["scenario"] == sid and j.get("total")]
    return f"{min(v):.2f}~{max(v):.2f}%" if v else "기록 없음"
d5_x = capkb("D5") / capkb("D3")
e8_x = med("E8", "writeMB") / 100
s_ids = [s["id"] for s in D["scenarios"] if s["type"] == "S"]
n_main = n_ids - len(s_ids)
s_wph = {k: med(k, "writeMB") / med(k, "durSec") * 3600 for k in s_ids}   # 시간당 쓰기 MB
s_wake = [med(k, "wakesPerMin") for k in s_ids]
s_flush = [med(k, "flushPerSec") for k in s_ids]
s1_upd = S["S1"]["perRun"][1]
VOL_H = 22 * len(ORDER) + 60

CHART_DATA = {
    "order": ORDER,
    "labels": {s["key"]: f'{s["id"]}{" " + s["cache"] if s["cache"] else ""}' for s in D["scenarios"]},
    "names": {s["key"]: label(s) for s in D["scenarios"]},
    "type": {s["key"]: s["type"] for s in D["scenarios"]},
    "types": D["types"],
    "buckets": D["meta"]["buckets"],
    "vol": {k: {d: S[k][f] for d, f in (("R", "readMB"), ("W", "writeMB"))} for k in ORDER},
    "size": {k: S[k]["size"] for k in ORDER},
    "dtoc": {k: S[k]["dtoc"] for k in ORDER},
    "gap": {k: S[k]["gap"] for k in ORDER},
    "seq": {k: {d: S[k]["seq"][d]["med"] for d in "RW"} for k in ORDER},
    "timeline": {k: S[k]["rep"]["timeline"] for k in ORDER},
    "rep": {k: S[k]["rep"]["repeat"] for k in ORDER},
    "lba": {k: S[k]["rep"]["lba"] for k in ORDER},
    "dur": {k: S[k]["durSec"]["med"] for k in ORDER},
    "ids": {k: S[k]["id"] for k in ORDER},
    "lbaMaxGB": D["meta"]["lbaMaxGB"],
    "jank": {f"{sid}-{rep}": {"sec": j["sec"], "cache": j["cache"]} for (sid, rep), j in J.items() if "sec" in j},
}

def legend(names, shift=0):
    cols = ["var(--r1)", "var(--r2)", "var(--r3)", "var(--r4)", "var(--r5)"][shift:]
    return '<div class="legend">' + "".join(f'<span><i style="background:{c}"></i>{E(n)}</span>' for n, c in zip(names, cols)) + '<span class="muted">건수 비율 %</span></div>'


SRC = "<code>uxtest/report/data.json</code> ← <code>extract.py</code> ← 회차별 저장장치 기록 <code>~/.agent-standalone/archive/jobs/&lt;시각&gt;_scenario_ux-&lt;ID&gt;/trace/&lt;trace job&gt;/result_fsio_ufs.parquet</code>"
PROV = {
    "vol": f"<p><b>값</b> 측정 구간 동안 저장장치에 들어간 읽기·쓰기 요청 크기의 합. 3번 측정의 중앙값(점)과 최소~최대(선).</p><p><b>계산</b> parquet 의 <code>action='send_req'</code> 행 중 SCSI 명령 40·136 = 읽기, 42·138 = 쓰기로 보고 <code>size</code> 합계 (<code>extract.py trace_metrics</code>).</p><p><b>출처</b> {SRC}</p>",
    "timeline": f"<p><b>값</b> 1초마다 저장장치에 보낸 읽기·쓰기 요청 크기 합 (MB/s). 3번 중 총량이 가운데인 회차 하나로 그렸어요.</p><p><b>계산</b> <code>floor(time - t0)</code> 초 단위로 묶은 send_req 크기 합 (<code>extract.py</code> timeline).</p><p><b>출처</b> {SRC}</p>",
    "size": f"<p><b>값</b> 요청 크기 구간별 건수 비율. 3번 평균 (그 방향 요청이 없던 회차는 뺌).</p><p><b>계산</b> send_req 의 <code>size</code> 를 4K / 8–16K / 20–128K / 132–512K / &gt;512K 로 나눔.</p><p><b>출처</b> {SRC}</p>",
    "dtoc": f"<p><b>값</b> 응답 시간(드라이버가 요청을 보낸 뒤 완료까지, dtoc) 구간별 건수 비율.</p><p><b>계산</b> <code>action='complete_rsp'</code> 행의 <code>dtoc</code>(ms) 를 &lt;0.1 / 0.1–0.5 / 0.5–1 / 1–5 / ≥5 로 나눔.</p><p><b>출처</b> {SRC}</p>",
    "gap": f"<p><b>값</b> DtoD(dispatch-to-dispatch): 앞 요청을 보낸 시각부터 다음 요청을 보낸 시각까지, 구간별 건수 비율. 처리 시간(DtoC, Latency)과는 다른 값이에요.</p><p><b>계산</b> send_req 의 <code>time</code> 차이를 &lt;1ms / 1–16ms / 16–200ms / ≥200ms 로 나눔.</p><p><b>출처</b> {SRC}</p>",
    "map": f"<p><b>값</b> 가로 = 바로 앞 요청이 끝난 위치에서 이어 시작한 요청의 바이트 비율(읽기·쓰기 가중 평균), 세로 = 쓰기 바이트 비중, 점 크기 = 총량.</p><p><b>출처</b> {SRC}</p>",
    "lba": f"<p><b>값</b> 측정 시간을 60칸, LUN 0 주소 공간을 48칸으로 나눈 칸마다 읽기·쓰기 MB. 3번 중 총량이 가운데인 회차.</p><p><b>계산</b> <code>lba</code> 는 4KB 단위. 모든 시나리오가 같은 세로 범위(0~{D['meta']['lbaMaxGB']:.0f}GB)를 써요.</p><p><b>출처</b> {SRC}</p>",
    "jank": f"<p><b>값</b> 위 = 1초마다 갤러리 프로세스(pid)가 보낸 읽기 MB, 아래 = 그 1초에 App Deadline Missed 로 표시된 프레임 수.</p><p><b>계산</b> Perfetto <code>actual_frame_timeline_slice</code> 와 fsio <code>time</code> 은 둘 다 boot clock 초라 그대로 맞췄어요 (<code>extract.py jank_io</code>).</p><p><b>출처</b> 프레임: <code>uxtest/runs/&lt;ID&gt;/&lt;시각&gt;/ux_&lt;ID&gt;_*.pftrace</code> · 읽기: {SRC}</p>",
    "runs": f"<p><b>값</b> 회차별 측정 구간의 읽기·쓰기 합계. trace job 은 원자료 parquet 폴더 이름이에요.</p><p><b>출처</b> {SRC}</p>",
}

HEAD = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&display=swap">
<link rel="stylesheet" href="assets/report.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.0/echarts.min.js"></script>
<script src="assets/report.js"></script>"""

PAGE = f"""<title>UX 워크로드 I/O 패턴 보고서</title>
<meta name="claude:viewport-fit-sides" content="cover">
{HEAD}

<div class="doc">
<header class="title">
  <div class="eyebrow">P1·P2·대기 측정 보고서 · 2026-10-25~26</div>
  <h1>UX 워크로드 유형별 UFS I/O 패턴</h1>
  <p class="lede">사람들이 폰으로 자주 하는 동작 {n_main}가지를 3번씩 재현하고, 그동안 저장장치(UFS)가 실제로 읽고 쓴 양과 모양을 기록했어요. 폰을 그냥 놓아 둔 대기 상태 {len(s_ids)}가지도 같이 쟀어요.</p>
  <p class="byline">OnePlus CPH2749 · SM8850 · RAM 16GB · Samsung UFS 512GB · Android 16 · 수집 도구 fsiotrace(eBPF)</p>
  <nav class="toc" aria-label="목차">
    <a href="#summary">핵심 결론</a><a href="#glance">유형별 한눈에</a><a href="#types">유형별 분석</a>
    <a href="#mgmt">UFS 관리 명령</a><a href="#method">측정 방법</a><a href="#limits">한계</a><a href="#appendix">부록</a>
  </nav>
  <nav class="chips" aria-label="유형별 페이지"><span class="muted" style="font-size:13px;align-self:center">유형별 페이지</span>{"".join(f'<a href="type-{t}.html">{t} {E(n)}</a>' for t, n in D["types"].items())}</nav>
</header>

<section id="summary" aria-labelledby="h-sum">
  <h2 id="h-sum">핵심 결론</h2>
  <ol class="takes">
    <li><a href="#t-D"><b>사진 한 장을 찍을 때마다 저장장치에 약 {d1_per:.0f}MB를 써요.</b><span>남는 JPEG는 장당 {d1_jpg:.1f}MB예요. 나머지는 카메라 앱이 촬영마다 만드는 중간 파일이에요.{chk('D1')}</span></a></li>
    <li><a href="#t-A"><b>앱을 처음 열면 앱 하나에 170~195MB를 읽어요.</b><span>캐시를 비우고 같은 앱을 다시 열면 약 25MB로 줄어요. Facebook은 같은 조건에서 다른 앱의 약 2배를 읽었어요.</span></a></li>
    <li><a href="#t-B"><b>웹 서핑과 영상 시청은 저장장치를 거의 쓰지 않아요.</b><span>YouTube 3분 재생 동안 쓴 양은 {mb(med('C1', 'writeMB'))}이고, 시간의 {med('C1', 'idlePct'):.0f}%는 아무 요청도 없었어요.</span></a></li>
    <li><a href="#t-G"><b>갤러리에서 사진 1000장을 넘겨 보면 11분 동안 약 5GB를 읽고 써요.</b><span>화면 끊김(jank)은 프레임의 0.75%였고, 저장장치 읽기와 겹치지 않았어요.</span></a></li>
    <li><a href="#t-E"><b>배터리로 쓸 때는 지운 파일의 블록을 바로 반납해요.</b><span>1GB 파일 삭제 10초 안에 블록 반납(discard) {med('E6', 'discardMB'):.0f}MB가 나갔어요. USB 전원을 꽂고 잰 첫 측정에서는 0이었어요.</span></a></li>
    <li><a href="#t-E"><b>Chrome으로 100MB를 받으면 약 {med('E8', 'writeMB'):.0f}MB를 써요.</b><span>3번 모두 파일 크기의 {e8_x:.1f}배였어요. 같은 크기를 복사하면 1.05배라, 나머지가 어디서 오는지 확인하고 있어요.</span></a></li>
    <li><a href="#t-S"><b>화면을 꺼 두어도 저장장치는 약 2초마다 깨어나요.</b><span>화면 켜짐, 꺼짐, 강제 deep doze 모두 분당 {min(s_wake):.0f}~{max(s_wake):.0f}번 깨어났고, 시간당 약 {min(s_wph.values()):.0f}~{max(s_wph.values()):.0f}MB를 썼어요. 지운 블록 반납(discard)은 이때 몰아서 나가요.</span></a></li>
    {"" if not OLD else f'<li class="caution"><a href="#limits"><b>어떤 앱·파일이 썼는지는 다시 재는 중이에요.</b><span>총량·속도·크기는 믿을 수 있어요. 수집 도구가 이름과 메타데이터 표시를 다른 파일 것으로 붙이던 문제를 10월 28일에 고쳤고, 시나리오 {len(FIXED)}개를 다시 쟀어요(남은 {len(OLD)}개).</span></a></li>'}
  </ol>
</section>

<section id="glance" aria-labelledby="h-glance">
  <h2 id="h-glance">유형별 한눈에</h2>
  <div class="tw" data-name="유형별 한눈에"><table class="glance">
    <thead><tr><th>유형</th><th>얼마나</th><th>어떤 모양</th><th>성능에서 중요한 것</th></tr></thead>
    <tbody>
      <tr><th scope="row"><a href="#t-A">앱 실행</a></th><td class="num">처음 열 때 앱당 <b>약 190MB 읽기</b></td><td>중간 크기 읽기를 한꺼번에 여러 개 보내요</td><td>여러 읽기를 동시에 빨리 처리하는 능력</td></tr>
      <tr><th scope="row"><a href="#t-B">웹·피드</a></th><td class="num">40~60초에 <b>쓰기 4~29MB</b></td><td>작은 쓰기가 띄엄띄엄, 대부분 쉬어요</td><td>작은 쓰기의 지연, 쉬었다가 깨어나는 속도</td></tr>
      <tr><th scope="row"><a href="#t-C">미디어 재생</a></th><td class="num">스트리밍 3분 <b>쓰기 {mb(med('C1', 'writeMB'))}</b><br>로컬 영상 <b>약 45초마다 몰아 읽기</b></td><td>스트리밍은 거의 쉬고, 로컬 재생은 구간을 미리 읽어 두고 쉬어요</td><td>재생 시작 순간의 읽기 속도</td></tr>
      <tr><th scope="row"><a href="#t-D">카메라</a></th><td class="num">사진 10장 <b>쓰기 {mb(med('D1', 'writeMB'))}</b><br>버스트 10초 <b>쓰기 {mb(med('D2', 'writeMB'))}</b></td><td>큰 쓰기를 이어서, 초당 최대 {med('D2', 'peakMBs'):.0f}MB. 4K 동영상은 1080p의 약 {d5_x:.0f}배</td><td>쓰기 버퍼 크기와 저장장치 수명</td></tr>
      <tr><th scope="row"><a href="#t-E">파일 작업</a></th><td class="num">512MB 복사 <b>초당 최대 {med('E2', 'peakMBs') / 1000:.1f}GB</b></td><td>큰 읽기·쓰기를 끊김 없이 이어서</td><td>최대 대역폭</td></tr>
      <tr><th scope="row"><a href="#t-F">생산성</a></th><td class="num">메모·녹음·연락처·캘린더 <b>쓰기 1~11MB</b></td><td>작은 쓰기 몇 번, 대부분 쉬어요</td><td>거의 영향 없음. 앱이 처음 뜨는 순간만 읽기가 많아요</td></tr>
      <tr><th scope="row"><a href="#t-G">갤러리 1000장</a></th><td class="num">뷰어 11분 <b>읽기 {mb(med('G2-warm', 'readMB'))} · 쓰기 {mb(med('G2-warm', 'writeMB'))}</b></td><td>원본 사진을 매번 다시 읽고, 화면용 캐시를 계속 써요</td><td>앱의 캐시 정책 (저장장치보다 앱 쪽)</td></tr>
      <tr><th scope="row"><a href="#t-S">대기</a></th><td class="num">30분 <b>쓰기 {mb(med('S1', 'writeMB'))}</b><br>앱 업데이트가 끼면 <b>읽기 {s1_upd['readMB']:.0f}MB</b></td><td>작은 쓰기와 flush가 약 2초마다, 가끔 앱이 깨어나 몰아 읽기</td><td>짧은 유휴 사이의 절전 진입·복귀, 배경 discard 처리</td></tr>
    </tbody></table></div>

  <figure>
    <div class="legend"><span><i style="background:var(--read)"></i>읽기</span><span><i style="background:var(--write)"></i>쓰기</span><span class="muted">점 = 3번 측정의 중앙값, 가로선 = 가장 적었던 회차부터 많았던 회차까지, 가로축은 로그 눈금</span></div>
    <div id="f-vol" class="chart" style="height:{VOL_H}px"></div>
    <figcaption><b>그림 1. 시나리오별 읽기·쓰기 총량 (P1·P2 전체).</b> 카메라(사진 10장, 버스트샷)와 갤러리 뷰어 1000장은 GB 단위, 웹·피드(B)는 MB 단위라 가로축을 로그 눈금으로 그렸어요.</figcaption>
  </figure>
</section>

<section id="types" aria-labelledby="h-types">
  <h2 id="h-types">유형별 분석</h2>
  <p class="prose muted">유형마다 결론 한 줄, 핵심 숫자 셋, 근거, 그리고 무엇을 뜻하는지 순서로 적었어요. 그래프는 대표 시나리오의 1초 단위 읽기(위)·쓰기(아래) 속도예요. 각 유형 아래 "변형 시나리오"는 P2에서 조건을 바꿔 잰 결과예요.</p>

  <article class="type" id="t-D">
    <header><span class="tid">D 카메라</span><h3>사진은 남는 파일의 수십 배를 써요</h3></header>
    <div class="stats">
      <div><b>{d1_per:.0f}MB</b><span>사진 한 장당 쓰기</span></div>
      <div><b>{d1_jpg:.1f}MB</b><span>남는 JPEG 한 장</span></div>
      <div><b>{med('D2', 'peakMBs'):.0f}MB/s</b><span>버스트 중 최고 쓰기 속도</span></div>
    </div>
    <ul class="points">
      <li>사진 10장을 찍는 27초 동안 {mb(med('D1', 'writeMB'))}를 썼어요. 버스트샷 3초(약 23장)는 10초 동안 {mb(med('D2', 'writeMB'))}를 썼어요.</li>
      <li>셔터를 누를 때마다 카메라 앱이 <code>/data/vendor/camera_process/</code>에 촬영 한 번당 약 80MB(16MB 안팎 파일 여러 개)의 중간 파일을 써요. 쓰기 양의 약 90%가 이 파일이고, 측정 구간 안에서 저장장치로 다시 읽지는 않았어요.{chk('D1')}</li>
      <li>동영상은 달라요. 30초 1080p 녹화 파일 {capkb('D3'):.0f}MB에 쓰기 {mb(med('D3', 'writeMB'))}로, 파일 크기만큼만 써요.</li>
    </ul>
    <div class="tl-row"><div class="chart" data-tl="D1" style="height:140px"></div><div class="chart" data-tl="D2" style="height:140px"></div></div>
    <div class="more"><h4>변형 시나리오 (P2)</h4><ul class="points">
      <li><b>동영상은 길이·화질에 비례해요.</b> 2분 녹화는 파일 {capkb('D4'):.0f}MB에 쓰기 {mb(med('D4', 'writeMB'))}, 4K 30초는 파일 {capkb('D5'):.0f}MB에 쓰기 {mb(med('D5', 'writeMB'))}예요. 같은 길이 1080p의 약 {d5_x:.1f}배예요.</li>
      <li><b>전면 카메라도 중간 파일을 써요.</b> 5장에 {mb(med('D7', 'writeMB'))}, 장당 약 {d7_per:.0f}MB로 후면(장당 {d1_per:.0f}MB)과 비슷한 수준이고, 남는 JPEG의 20배가 넘어요.</li>
      <li><b>찍자마자 갤러리를 열면 읽기가 크게 늘어요.</b> 5장 찍고 바로 뷰어를 열면 읽기 {mb(med('D6', 'readMB'))}·쓰기 {mb(med('D6', 'writeMB'))}였어요. 읽기 대부분이 카메라 후처리 스레드(ApsCaptureDefer)예요. 사진만 찍었을 때는 10장에 읽기 {mb(med('D1', 'readMB'))}였어요.</li>
      <li>촬영 없이 사진·동영상 모드만 오가도 35초에 읽기 {mb(med('D8', 'readMB'))}·쓰기 {mb(med('D8', 'writeMB'))}예요. 쓰기는 대부분 카메라 앱의 화면 스냅샷 파일이고, 읽기는 거의 다 다른 앱의 배경 동작이에요.{chk('D8')}</li>
      <li>화면 녹화 1분은 쓰기 {mb(med('D9', 'writeMB'))}로 녹화 파일(약 25MB) 크기만큼만 써요.</li>
    </ul></div>
    <p class="sowhat"><b>무엇을 뜻하나</b> 사진 쓰기 양은 이미지가 아니라 카메라 앱의 중간 파일이 정해요. 버스트 10초에 1.5GB면 쓰기 버퍼(SLC 캐시) 크기와 수명 계산에 바로 들어가요. 중간 파일을 메모리(tmpfs)로 옮기면 가장 크게 줄일 수 있어요.</p>
    <a class="more-link" href="type-D.html">이 유형의 시나리오 전체 보기 →</a>
  </article>

  <article class="type" id="t-A">
    <header><span class="tid">A 앱 실행</span><h3>처음 열 때만 많이 읽어요</h3></header>
    <div class="stats">
      <div><b>170~195MB</b><span>앱을 처음 열 때 읽기 (6개 앱)</span></div>
      <div><b>약 25MB</b><span>같은 앱을 다시 cold로 열 때</span></div>
      <div><b>{med('A3', 'readMB') + med('A3', 'writeMB'):.0f}MB</b><span>띄워 둔 앱끼리 오갈 때 (1분)</span></div>
    </div>
    <ul class="points">
      <li>Chrome, YouTube, 설정, 갤러리, 지도는 처음 열 때 각각 170~195MB를 읽었어요(cold start 순회 6앱). 카메라는 약 100MB였어요.</li>
      <li>캐시를 비우고 Chrome을 다섯 번 다시 열면 Chrome 파일 읽기가 첫 번째만 약 225MB이고, 2~5번째는 30MB 안팎이었어요. 캐시를 비워도 base.apk 대부분이 메모리에 남는데, 어떤 프로세스가 붙잡고 있는지는 아직 확인하지 못했어요.{chk('A1')}</li>
      <li>읽기는 128~512KB 크기가 대부분이고, 한 번에 최대 {med('A2', 'qdP99'):.0f}개까지 동시에 쌓여요. 99%의 요청이 {med('A2', 'dtocP99', 'R'):.1f}ms 안에 끝났어요.</li>
      <li>이미 떠 있는 앱 사이를 오가면 1분 동안 {mb(med('A3', 'readMB') + med('A3', 'writeMB'))} 정도라 거의 없어요.</li>
    </ul>
    <div class="tl-row"><div class="chart" data-tl="A1" style="height:140px"></div><div class="chart" data-tl="A2" style="height:140px"></div></div>
    <div class="more"><h4>변형 시나리오 (P2)</h4><ul class="points">
      <li><b>Facebook은 다른 앱의 약 2배를 읽어요.</b> 무거운 앱 3개를 같은 방식으로 열고 실행 후 8초 동안 읽은 양이 지도 약 320MB, Instagram 약 335MB, Facebook 약 620MB예요. 이 구간 값에는 캐시를 비운 뒤 시스템 전체가 다시 읽는 양이 들어 있어서 위의 앱 기준 숫자보다 커요. 같은 기준으로 6앱 순회의 Chrome·설정·갤러리는 320~365MB였어요.</li>
      <li><b>데이터를 지우고 처음 열면 쓰기가 많아요.</b> 날씨 앱을 초기화하고 처음 열면 읽기 {mb(med('A6', 'readMB'))}·쓰기 {mb(med('A6', 'writeMB'))}예요. 앱 하나의 쓰기가 앱 6개를 연 cold start 순회 전체({mb(med('A2', 'writeMB'))})보다 많아요. 처음 쓰는 DB·설정 파일이에요.</li>
      <li><b>띄워 둔 앱으로 돌아가는 건 가벼워요.</b> 최근 앱 화면에서 6번 전환 쓰기 {mb(med('A5', 'writeMB'))}, 홈과 YouTube를 10번 오가기 쓰기 {mb(med('A7', 'writeMB'))}(한 번에 약 2.5MB)예요.</li>
      <li>백그라운드 5분 뒤 복귀는 3번 모두 YouTube가 메모리에 남아 있어서 쓰기 {mb(med('A8', 'writeMB'))}뿐이었어요. 메모리 16GB에서는 5분으로 밀려나지 않아요.</li>
    </ul></div>
    <p class="sowhat"><b>무엇을 뜻하나</b> 앱 실행 속도는 중간 크기 읽기를 여러 개 동시에 처리하는 능력에 달려 있어요. "캐시 비우기"로 만든 cold start는 실제 첫 실행과 양이 크게 달라서, 비교할 때는 첫 실행(cold start 순회 6앱)을 기준으로 삼는 게 맞아요.</p>
    <a class="more-link" href="type-A.html">이 유형의 시나리오 전체 보기 →</a>
  </article>

  <article class="type" id="t-B">
    <header><span class="tid">B 웹·피드</span><h3>작은 쓰기가 띄엄띄엄 나오고, 대부분 쉬어요</h3></header>
    <div class="stats">
      <div><b>{mb(med('B1', 'writeMB'))}</b><span>위키 2개 읽기 (44초)</span></div>
      <div><b>{mb(med('B3', 'writeMB'))}</b><span>YouTube 피드 40번 스크롤</span></div>
      <div><b>{med('B1', 'idlePct'):.0f}~{med('B2', 'idlePct'):.0f}%</b><span>요청이 없는 시간</span></div>
    </div>
    <ul class="points">
      <li>읽기는 거의 없어요. 화면에 필요한 건 이미 메모리에 있어요.</li>
      <li>쓰기는 브라우저 캐시와 썸네일, 그리고 앱의 기록 파일이에요. Chrome은 사용 통계 파일(BrowserMetrics)이 약 3분의 1, YouTube는 설정 파일(youtube.xml)을 반복해서 다시 쓰는 몫이 커요. 쓰기의 15~20%는 파일 내용이 아니라 파일시스템 관리 정보(f2fs 메타데이터)예요.{chk('B1', 'B3')}</li>
      <li>같은 동작을 해도 회차마다 2배 가까이 달라요(YouTube 홈피드 {S['B3']['writeMB']['min']:.0f}~{S['B3']['writeMB']['max']:.0f}MB). 백그라운드 동기화가 섞이기 때문이에요.</li>
    </ul>
    <div class="tl-row"><div class="chart" data-tl="B1" style="height:140px"></div><div class="chart" data-tl="B3" style="height:140px"></div></div>
    <div class="more"><h4>변형 시나리오 (P2)</h4><ul class="points">
      <li><b>시크릿 모드는 쓰기가 줄지만 0은 아니에요.</b> Chrome 위키와 같은 문서를 시크릿 탭에서 읽으면 쓰기 {mb(med('B1i', 'writeMB'))}로 일반 모드({mb(med('B1', 'writeMB'))})의 약 {100 * med('B1i', 'writeMB') / med('B1', 'writeMB'):.0f}%예요.</li>
      <li><b>무엇을 해도 1분에 10~20MB예요.</b> 탭 5개 전환 {mb(med('B4', 'writeMB'))}, 이미지 많은 문서 {mb(med('B5', 'writeMB'))}, 지도 이동·확대 {mb(med('B6', 'writeMB'))}, Gmail {mb(med('B8', 'writeMB'))}, Play 스토어 {mb(med('B9', 'writeMB'))}이고, 요청 없는 시간이 87~94%예요.</li>
      <li>이미지가 200개 넘는 문서도 글 위주 문서와 쓰기 양이 비슷했어요.</li>
      <li><b>Instagram 피드는 YouTube 피드의 약 {med('B7', 'writeMB') / med('B3', 'writeMB'):.0f}배를 써요.</b> 같은 1분 40번 스크롤에 Instagram은 쓰기 {mb(med('B7', 'writeMB'))}, YouTube는 {mb(med('B3', 'writeMB'))}예요. 피드의 사진·영상을 캐시에 받아 두는 쓰기로, 128KB가 넘는 큰 쓰기가 대부분이에요. 회차 차이도 작아요({S['B7']['writeMB']['min']:.0f}~{S['B7']['writeMB']['max']:.0f}MB).</li>
      <li><b>Instagram 릴스는 100초에 {mb(med('B7r', 'writeMB'))}를 써요.</b> 릴스 20개를 5초씩 보면 Read가 거의 0이고 Write만 나와요(회차별 {S['B7r']['writeMB']['min']:.0f}~{S['B7r']['writeMB']['max']:.0f}MB). 1분으로 따지면 약 {60 * med('B7r', 'writeMB') / med('B7r', 'durSec'):.0f}MB로 피드(1분 {mb(med('B7', 'writeMB'))})보다 적고, YouTube 3분 재생({mb(med('C1', 'writeMB'))})의 약 {med('B7r', 'writeMB') / med('C1', 'writeMB'):.0f}배예요. 다음 영상을 미리 받아 캐시에 쓰는 큰 Sequential Write가 대부분이고, Peak throughput은 {med('B7r', 'peakMBs'):.0f} MB/s예요.</li>
      <li><b>TikTok은 같은 동작에 릴스의 약 {med('B7t', 'writeMB') / med('B7r', 'writeMB'):.1f}배를 쓰고, 모양도 달라요.</b> 영상 20개를 5초씩 보면 Write {mb(med('B7t', 'writeMB'))}(회차별 {S['B7t']['writeMB']['min']:.0f}~{S['B7t']['writeMB']['max']:.0f}MB)예요. 릴스는 큰 Sequential Write가 대부분인데, TikTok은 4~128KB Random Write가 대부분이고 Write 요청 수가 약 {med('B7t', 'writeN') / med('B7r', 'writeN'):.0f}배예요. Metadata가 {med('B7t', 'metaPct'):.0f}%(릴스 {med('B7r', 'metaPct'):.0f}%), Flush가 초당 {med('B7t', 'flushPerSec'):.0f}번(릴스 {med('B7r', 'flushPerSec'):.0f}번)이에요. 영상 파일보다 앱 안의 SQLite DB(전략·추적·추천 기록으로 보이는 이름)를 자주 고쳐 쓰는 쪽이 커요. 전략 DB(ttm_strategy) 하나가 Write의 약 5분의 1이에요.{chk('B7t')}</li>
      <li><b>YouTube Shorts는 같은 동작에 Write가 {mb(med('B7y', 'writeMB'))}로, 셋 중 가장 적어요.</b> Shorts 20개를 5초씩 보면 회차별 {S['B7y']['writeMB']['min']:.0f}~{S['B7y']['writeMB']['max']:.0f}MB를 써서 릴스({mb(med('B7r', 'writeMB'))})의 약 {100 * med('B7y', 'writeMB') / med('B7r', 'writeMB'):.0f}%, TikTok({mb(med('B7t', 'writeMB'))})의 약 {100 * med('B7y', 'writeMB') / med('B7t', 'writeMB'):.0f}%예요. 그래서 Write 양은 Shorts &lt; 릴스 &lt; TikTok 순이에요. YouTube 앱에는 영상을 받아 두는 큰 캐시 폴더가 없고, 영상은 메모리에서 재생하는 것으로 보여요. 남는 Write는 썸네일·기록 쪽 작은 쓰기라 Metadata가 {med('B7y', 'metaPct'):.0f}%예요. Flush는 초당 {med('B7y', 'flushPerSec'):.1f}번이에요.</li>
    </ul></div>
    <p class="sowhat"><b>무엇을 뜻하나</b> 이 유형은 속도보다 작은 쓰기의 지연과, 쉬다가 다시 깨어나는 시간이 체감을 좌우해요.</p>
    <a class="more-link" href="type-B.html">이 유형의 시나리오 전체 보기 →</a>
  </article>

  <article class="type" id="t-C">
    <header><span class="tid">C 미디어 재생</span><h3>스트리밍은 거의 쉬고, 로컬 영상은 처음에 몰아 읽어요</h3></header>
    <div class="stats">
      <div><b>{mb(med('C1', 'writeMB'))}</b><span>YouTube 3분 재생 중 쓰기</span></div>
      <div><b>{med('C3', 'peakMBs'):.0f}MB/s</b><span>로컬 영상 재생 시작 직후 읽기</span></div>
      <div><b>{S['C2']['writeMB']['min']:.0f}~{S['C2']['writeMB']['max']:.0f}MB</b><span>Shorts 30개, 회차별 쓰기</span></div>
    </div>
    <ul class="points">
      <li>YouTube 3분 재생은 쓰기 {mb(med('C1', 'writeMB'))}, 요청 없는 시간이 {med('C1', 'idlePct'):.0f}%예요.</li>
      <li>Shorts 30회 넘기기는 회차마다 {S['C2']['writeMB']['min']:.0f}MB에서 {S['C2']['writeMB']['max']:.0f}MB까지 달라서 대표값을 정하기 어려워요.</li>
      <li>로컬 영상은 재생을 시작하자마자 한 번 몰아 읽고(첫 burst에 약 70MB), 그 뒤에는 약 45초마다 다음 구간을 몰아 읽고 쉬어요. 파일 읽기는 앱이 아니라 저장소 관리 프로세스(MediaProvider)에 잡혀요.{chk('C3')}</li>
    </ul>
    <div class="tl-row"><div class="chart" data-tl="C1" style="height:140px"></div><div class="chart" data-tl="C3" style="height:140px"></div></div>
    <div class="more"><h4>변형 시나리오 (P2)</h4><ul class="points">
      <li><b>화질을 바꿔도 쓰기는 크게 다르지 않아요.</b> 360p {mb(med('C4a', 'writeMB'))}, 1080p {mb(med('C4b', 'writeMB'))}, 자동 {mb(med('C1', 'writeMB'))}이에요. 화질 차이보다 회차 차이(1080p {S['C4b']['writeMB']['min']:.0f}~{S['C4b']['writeMB']['max']:.0f}MB)가 커요. 영상 데이터는 저장장치를 거치지 않는 것으로 보여요.</li>
      <li>재생 중 앞뒤로 건너뛰어도 쓰기 {mb(med('C5', 'writeMB'))}예요.</li>
      <li><b>YouTube Music은 영상보다 많이 써요.</b> 3분 재생 쓰기 {mb(med('C6', 'writeMB'))}, 회차별 {S['C6']['writeMB']['min']:.0f}~{S['C6']['writeMB']['max']:.0f}MB예요. 앱이 메모리에 없던 첫 회차에는 앱 파일 읽기 약 {S['C6']['perRun'][0]['readMB']:.0f}MB가 함께 잡혔어요.</li>
      <li>로컬 영상을 10곳 건너뛰며 보면 읽기 {mb(med('C7', 'readMB'))}로, 처음부터 2분 재생한 경우({mb(med('C3', 'readMB'))})보다 적어요. 건너뛴 구간은 읽지 않아요.</li>
    </ul></div>
    <p class="sowhat"><b>무엇을 뜻하나</b> 스트리밍의 I/O는 저장장치보다 앱의 캐시 방식에 달려 있어요. 로컬 재생은 시작 순간의 읽기 속도만 중요해요.</p>
    <a class="more-link" href="type-C.html">이 유형의 시나리오 전체 보기 →</a>
  </article>

  <article class="type" id="t-E">
    <header><span class="tid">E 파일 작업</span><h3>파일 복사는 이 기기의 최대 속도를 보여 줘요</h3></header>
    <div class="stats">
      <div><b>{med('E2', 'peakMBs') / 1000:.1f}GB/s</b><span>512MB 복사 중 최고 속도</span></div>
      <div><b>{med('E3', 'qdP99'):.0f}개</b><span>앱 재설치 때 동시 요청 (가장 많음)</span></div>
      <div><b>{med('E6', 'discardMB'):.0f}MB</b><span>1GB 삭제 10초 안 블록 반납(discard)</span></div>
    </div>
    <ul class="points">
      <li>512MB 복사는 읽기·쓰기가 모두 끊김 없이 이어지고, 쓰기는 대부분 512KB보다 커요.</li>
      <li>앱 재설치는 읽기 {mb(med('E3', 'readMB'))}, 쓰기 {mb(med('E3', 'writeMB'))}이고, 동시에 쌓인 요청이 전체 시나리오 중 가장 많아요.</li>
      <li>캐시 정리는 측정 구간이 3~7초로 짧아, 3번 중 1번만 블록 반납({S['E4']['discardMB']['max']:.0f}MB)이 구간 안에 들어왔어요.</li>
    </ul>
    <div class="tl-row"><div class="chart" data-tl="E2" style="height:140px"></div><div class="chart" data-tl="E3" style="height:140px"></div></div>
    <div class="more"><h4>변형 시나리오 (P2)</h4><ul class="points">
      <li><b>1GB를 지우면 곧바로 블록을 반납해요.</b> 파일 삭제 10초 동안 블록 반납 {med('E6', 'discardMB'):.0f}MB(회차별 {S['E6']['discardMB']['min']:.0f}~{S['E6']['discardMB']['max']:.0f}MB), 쓰기는 {mb(med('E6', 'writeMB'))}예요. USB 전원을 꽂고 잰 첫 측정에서는 같은 10초 동안 반납이 0이었어요. 충전 중인지에 따라 f2fs가 반납을 보내는 때가 달라져요.</li>
      <li><b>Chrome 다운로드는 파일 크기의 {e8_x:.1f}배를 써요.</b> 100MB를 받는 동안 쓰기가 {S['E8']['writeMB']['min']:.0f}~{S['E8']['writeMB']['max']:.0f}MB로 3번 모두 같았어요. 쓰기 대부분이 커널 writeback이라 어떤 파일이 두 번째 100MB를 썼는지는 아직 확인하지 못했어요.</li>
      <li><b>앱으로 복사해도 양은 같아요.</b> 파일 관리자로 256MB 복사는 읽기 {mb(med('E7', 'readMB'))}·쓰기 {mb(med('E7', 'writeMB'))}로 셸 복사처럼 1.05배예요. 최고 속도는 {med('E7', 'peakMBs'):.0f}MB/s로 셸 복사의 {med('E2', 'peakMBs'):.0f}MB/s보다 낮아요.</li>
      <li>4KB 파일 1000개를 만들고 지우면 데이터 4MB에 쓰기 {mb(med('E5', 'writeMB'))}예요.</li>
      <li>갤러리 가벼운 사용(스크롤 20번, 사진 5장)은 읽기 {mb(med('E1', 'readMB'))}·쓰기 {mb(med('E1', 'writeMB'))}예요.</li>
    </ul></div>
    <p class="sowhat"><b>무엇을 뜻하나</b> 512MB 복사는 다른 시나리오를 비교할 기준선으로 쓸 수 있어요. 삭제한 공간을 저장장치가 언제 알게 되는지는 1GB를 지운 경우에도 10초 안에 보이지 않아서, 측정 구간을 분 단위로 늘려 따로 봐야 해요.</p>
    <a class="more-link" href="type-E.html">이 유형의 시나리오 전체 보기 →</a>
  </article>

  <article class="type" id="t-F">
    <header><span class="tid">F 생산성 (P2)</span><h3>메모·녹음·연락처·캘린더는 저장장치를 거의 쓰지 않아요</h3></header>
    <div class="stats">
      <div><b>{mb(med('F1', 'writeMB'))}</b><span>메모 하나 저장</span></div>
      <div><b>{mb(med('F2', 'writeMB'))}</b><span>1분 녹음</span></div>
      <div><b>{mb(med('F5', 'writeMB'))}</b><span>캘린더 12달 넘기기</span></div>
    </div>
    <ul class="points">
      <li>약 500자 메모 저장 쓰기 {mb(med('F1', 'writeMB'))}, 1분 녹음 {mb(med('F2', 'writeMB'))}, 연락처 검색·스크롤 {mb(med('F4', 'writeMB'))}, 캘린더 {mb(med('F5', 'writeMB'))}예요. 요청 없는 시간이 86~95%예요.</li>
      <li>읽기는 첫 회차만 커요(메모 {S['F1']['perRun'][0]['readMB']:.0f}MB, 녹음기 {S['F2']['perRun'][0]['readMB']:.0f}MB). 앱이 메모리에 없어 앱 파일을 읽은 양이고, 두 번째부터는 수 MB예요.</li>
      <li>메시지 앱은 계정 연결 화면이 떠서 측정하지 않았어요.</li>
    </ul>
    <div class="tl-row"><div class="chart" data-tl="F1" style="height:140px"></div><div class="chart" data-tl="F2" style="height:140px"></div></div>
    <p class="sowhat"><b>무엇을 뜻하나</b> 이 유형에서 체감 차이는 저장장치보다 앱이 메모리에 남아 있는지에 달려 있어요.</p>
    <a class="more-link" href="type-F.html">이 유형의 시나리오 전체 보기 →</a>
  </article>

  <article class="type" id="t-G">
    <header><span class="tid">G 갤러리 1000장</span><h3>뷰어는 원본을 매번 다시 읽지만, 끊김의 원인은 아니에요</h3></header>
    <div class="stats">
      <div><b>{mb(med('G2-warm', 'readMB'))}</b><span>뷰어 11분 읽기 (두 번째 이후)</span></div>
      <div><b>{mb(med('G2-warm', 'writeMB'))}</b><span>같은 시간 쓰기</span></div>
      <div><b>{100 * g2w['jank']['frames'] / g2w['total']:.2f}%</b><span>앱이 늦어 끊긴 프레임</span></div>
    </div>
    <ul class="points">
      <li>그리드를 끝까지 스크롤하면 처음에만 썸네일을 만들어요(쓰기 {mb(med('G1-cold', 'writeMB'))}). 두 번째부터는 쓰기 {mb(med('G1-warm', 'writeMB'))} 정도예요.</li>
      <li>뷰어로 1000장을 넘기면 두 번째, 세 번째에도 원본 981장(1.75GB)을 모두 다시 읽어요. 1.7GB 사진 세트는 메모리 16GB 기기에서도 캐시에 남지 않아요.</li>
      <li>끊긴 프레임 주변의 읽기는 정상 프레임과 비슷하거나 적었어요(프레임당 {g2w['jank']['readsPerFrame']:.1f}건 대 {g2w['normal']['readsPerFrame']:.1f}건). 사진을 처음 보는 회차에서만 끊긴 프레임 쪽 읽기가 더 많았어요.</li>
      <li>그리드 스크롤은 회당 약 8,900프레임 중 끊긴 프레임이 1개라 매끄러워요.</li>
    </ul>
    <figure class="inner">
      <div class="controls"><span id="seg-label">회차</span><div class="seg" id="sel-jank" role="group" aria-labelledby="seg-label"><button type="button" data-v="G2-1" aria-pressed="false">뷰어 첫 회차</button><button type="button" data-v="G2-2" aria-pressed="true">뷰어 두 번째</button><button type="button" data-v="G2-3" aria-pressed="false">뷰어 세 번째</button><button type="button" data-v="G1-1" aria-pressed="false">그리드 첫 회차</button><button type="button" data-v="G1-2" aria-pressed="false">그리드 두 번째</button><button type="button" data-v="G4-2" aria-pressed="false">뷰어 빠른 넘기기</button><button type="button" data-v="G5-2" aria-pressed="false">사진 확대</button></div></div>
      <div id="f-jank" class="chart" style="height:340px"></div>
      <figcaption><b>그림 2. 갤러리 읽기와 끊긴 프레임.</b> 위는 1초마다 갤러리가 읽은 양, 아래는 1초마다 앱이 늦어 끊긴 프레임 수예요. 두 그래프의 가로축은 같은 시간이에요.</figcaption>
    </figure>
    <div class="more"><h4>변형 시나리오 (P2)</h4><ul class="points">
      <li><b>빠르게 훑으면 썸네일을 덜 만들어요.</b> 빠른 fling 첫 회차는 쓰기 {mb(med('G3-cold', 'writeMB'))}로, 천천히 끝까지 스크롤한 그리드 첫 회차(쓰기 {mb(med('G1-cold', 'writeMB'))})의 절반쯤이에요.</li>
      <li><b>뷰어는 넘긴 사진마다 약 {med('G4', 'writeMB') / 300:.1f}MB를 써요.</b> 0.15초 간격으로 300장에 읽기 {mb(med('G4', 'readMB'))}·쓰기 {mb(med('G4', 'writeMB'))}이에요. 장당 쓰기가 1000장 뷰어(약 2.4MB)와 비슷해요. 끊긴 프레임은 {jank_rng('G4')}로 1000장 뷰어({jank_rng('G2')})보다 적었어요.</li>
      <li><b>확대 타일은 한 번 만들면 다음부터 읽어요.</b> 20장 확대는 갤러리가 만들어 둔 확대용 타일 캐시(tilecache)를 읽는 게 대부분이에요. {(lambda r: f"3회 중 {r['repeat']}회차만 타일을 새로 만들어 쓰기 {r['writeMB']:.0f}MB, 읽기 {r['readMB']:.0f}MB였고")(max(S['G5']['perRun'], key=lambda r: r['writeMB']))}, 나머지는 읽기 약 {min(r['readMB'] for r in S['G5']['perRun']):.0f}MB, 쓰기 {min(r['writeMB'] for r in S['G5']['perRun']):.0f}MB예요. 끊긴 프레임은 {jank_rng('G5')}예요.</li>
      <li>20장 삭제 후 휴지통 비우기는 읽기 {mb(med('G6', 'readMB'))}·쓰기 {mb(med('G6', 'writeMB'))}예요.</li>
    </ul></div>
    <p class="sowhat"><b>무엇을 뜻하나</b> 뷰어의 끊김은 사진 디코딩이나 그리기 쪽에서 원인을 찾아야 해요. 갤러리 I/O를 줄이려면 저장장치보다 앱의 캐시 정책을 봐야 해요.</p>
    <a class="more-link" href="type-G.html">이 유형의 시나리오 전체 보기 →</a>
  </article>

  <article class="type" id="t-S">
    <header><span class="tid">S 대기 (2026-10-26)</span><h3>화면을 꺼도, deep doze여도 저장장치는 약 2초마다 깨어나요</h3></header>
    <div class="stats">
      <div><b>{med('S2', 'wakesPerMin'):.0f}번</b><span>강제 deep doze 중 분당 깨어남</span></div>
      <div><b>{s_wph['S2']:.0f}MB</b><span>deep doze 중 시간당 쓰기</span></div>
      <div><b>{mb(med('S1', 'discardMB'))}</b><span>화면 꺼짐 30분 블록 반납</span></div>
    </div>
    <ul class="points">
      <li>화면 켜진 홈, 화면 끈 직후, 화면 꺼짐 30분, 강제 deep doze 30분 모두 분당 {min(s_wake):.0f}~{max(s_wake):.0f}번, 요청이 1초 넘게 끊겼다가 다시 와요. 가장 길게 쉰 시간도 {min(med(k, 'maxGapSec') for k in s_ids):.1f}~{max(med(k, 'maxGapSec') for k in s_ids):.1f}초예요. 캐시 비우기(flush) 요청은 초당 약 {sorted(s_flush)[len(s_flush) // 2]:.0f}번이에요.</li>
      <li>시간당 쓰기는 화면 켜진 홈 {s_wph['S4']:.0f}MB, 화면 꺼짐 {s_wph['S1']:.0f}MB, 강제 deep doze {s_wph['S2']:.0f}MB예요. deep doze로 앱 작업을 막아도 줄지 않았어요. 쓰기는 대부분 4~16KB 랜덤이고, 파일시스템 메타데이터가 약 {med('S2', 'metaPct'):.0f}%예요.{chk('S2')}</li>
      <li><b>지운 블록은 대기 중에 반납해요.</b> 화면 꺼짐 30분 동안 {mb(med('S1', 'discardMB'))}를 반납했어요(회차별 {S['S1']['discardMB']['min']:.0f}~{S['S1']['discardMB']['max']:.0f}MB). 화면이 켜져 있을 때도 배터리 상태라면 파일을 지운 직후 반납이 나가요(1GB 파일 삭제).</li>
      <li><b>배경 앱 업데이트가 가장 커요.</b> 화면 꺼짐 30분의 두 번째 회차는 읽기 {s1_upd['readMB']:.0f}MB·쓰기 {s1_upd['writeMB']:.0f}MB로 다른 회차의 수 배예요. 앱 설치용 임시 파일(131MB)과 Instagram APK(163MB)를 검사 프로세스가 읽었어요. Play 스토어 자동 업데이트로 보여요.{chk('S1')}</li>
      <li><b>3시간 대기에도 배경 작업이 몰리는 순간이 있어요.</b> 앱을 따로 띄우지 않고 3시간 동안 읽기 {mb(med('S5', 'readMB'))}·쓰기 {mb(med('S5', 'writeMB'))}·블록 반납 {mb(med('S5', 'discardMB'))}이 나갔어요. 평소에는 10분에 쓰기 25~50MB 정도인데, 두 번 크게 튀었어요. 82분째(자정 무렵)에는 OxygenOS 사용 패턴 DB(<code>obrain.db</code>)의 하루 백업으로 1분에 쓰기 약 120MB, 138~147분째에는 앱 자동 업데이트(설치 임시 파일, 앱 검사 프로세스가 Instagram·Facebook APK를 읽음)로 읽기 약 370MB·쓰기 약 450MB가 몰렸어요. 이 두 구간(11분)이 3시간 총량의 절반이 넘어요.</li>
    </ul>
    <div class="tl-row"><div class="chart" data-tl="S2" style="height:140px"></div><div class="chart" data-tl="S5" style="height:140px"></div></div>
    <p class="sowhat"><b>무엇을 뜻하나</b> 대기 중 저장장치는 쉬는 시간이 몇 초를 넘지 않아요. 짧은 유휴에서 빨리 절전에 들어가고 빨리 깨어나는 능력, 그리고 배경 블록 반납 처리가 대기 전력과 수명에 중요해요. 다만 무선 adb로 기록을 계속 보내는 동안이라 측정 자체가 깨어남을 늘렸을 수 있어요(한계 참고).</p>
    <a class="more-link" href="type-S.html">이 유형의 시나리오 전체 보기 →</a>
  </article>
</section>

<section id="mgmt" aria-labelledby="h-mgmt">
  <h2 id="h-mgmt">UFS 관리 명령 (mgmt)</h2>
  <div class="prose">
  <p>fsiotrace는 Read·Write·Flush·Discard 말고도 UFS 관리 명령을 같이 기록해요. Hibern8 진입·해제(UIC DME 명령), Query Request(attribute·flag·descriptor 읽기·쓰기), exception event예요. 다른 절의 Volume·Idle·QD 같은 지표는 이 명령을 빼고 셌고, 여기서 따로 봐요. 일반 명령의 응답 UPIU(upiu_response)는 관리 명령이 아니라서 뺐어요.</p>
  <ul class="points">
    <li><b>링크는 쉬자마자 Hibern8에 들어가요.</b> 화면이 켜진 시나리오는 분당 {mrng(MG_ON, 'h8PerMin')}번 Hibern8에 들어갔다 나와요(가장 적은 것은 작은 파일 1000개 생성·삭제). 가장 잦은 것은 {mtop(MG_ON, 'h8PerMin')}번이에요. 짧은 I/O가 수십~수백 ms 간격으로 끊겨 오는 시나리오예요. Hibern8 exit는 중앙값 {mg_exit:.2f}ms, enter는 {mg_enter:.2f}ms 걸려요. 쉬다가 오는 첫 요청은 이 exit 시간만큼 더 기다려요.</li>
    <li><b>측정 시간의 대부분은 Hibern8 안이에요.</b> 웹·미디어·생산성은 측정 시간의 약 {mrng([x for x in MG if x["type"] in "BCF"], 'h8Pct')}%를 Hibern8에서 보내요. 앱 실행(A)은 {mrng([x for x in MG if x["type"] == "A"], 'h8Pct')}%로 낮고, 파일을 계속 쓰는 512MB 복사와 작은 파일 1000개 생성·삭제는 Hibern8 시간이 {max(med('E2', 'h8Pct'), med('E5', 'h8Pct')):.1f}% 이하로, 링크가 거의 쉬지 않아요.</li>
    <li><b>Query는 대부분 bBackgroundOpStatus 읽기예요.</b> 전체 Query 요청 {sum(v for k, v in mg_names.items() if k[0] in "RWSC"):,}건 중 {mg_names.get('Read Attribute(bBackgroundOpStatus)', 0):,}건이에요. Hibern8을 한 번 드나들 때 약 {mg_bk:.0f}번(해제 직후·진입 직전) 읽어요. Query 응답은 중앙값 {mg_q50:.2f}ms, 99%가 {mg_q99:.2f}ms 안이에요.</li>
    <li><b>화면이 꺼진 대기에서만 Write Booster 상태를 읽어요.</b> 화면 꺼짐 30분, 강제 deep doze, 화면 끈 직후, 3시간 대기는 bAvailableWBBufSize, dCurrentWBBufSize, bWBBufLifeTimeEst 세 속성을 한 묶음으로 분당 {mrng(MG_OFF, 'wbCheckPerMin')}번 읽어요. Hibern8 횟수(분당 {mrng(MG_OFF, 'h8PerMin')}번)와 거의 같아서, 절전에 들어갈 때마다 WB flush가 필요한지 확인하는 것으로 보여요. 화면이 켜진 시나리오와 화면 켜진 홈 대기에는 이 조회가 없어요.</li>
    <li><b>화면 켜진 홈 대기에서는 UFS가 주기적으로 suspend·resume해요(추정).</b> wExceptionEventControl 쓰기와 fBackgroundOpsEn clear로 시작해서, qTimestamp 쓰기, fBackgroundOpsEn set, wExceptionEventControl 쓰기로 끝나는 묶음이 3회 합쳐 {mgsum([S['S4']], 'Clear Flag(fBackgroundOpsEn)')}번 나와요. 다른 시나리오에서는 앱 재설치 {mgsum([S['E3']], 'Clear Flag(fBackgroundOpsEn)')}번, 3시간 대기 {mgsum([S['S5']], 'Clear Flag(fBackgroundOpsEn)')}번뿐이에요.</li>
    <li><b>드물게 나오는 것:</b> qTimestamp 쓰기는 대기(S)에서 주로 나와요(화면 꺼짐 30분 3회 합 {mgsum([S['S1']], 'Write Attribute(qTimestamp)')}번, 3시간 대기 {mgsum([S['S5']], 'Write Attribute(qTimestamp)')}번). health descriptor 읽기는 모두 {mg_names.get('Read Descriptor(health)', 0)}번, exception event는 3시간 대기에서 {mg_names.get('exception', 0)}번이에요. Write Booster를 켜고 끄는 flag 명령은 측정 중에 없었어요.</li>
  </ul>
  <div class="tw" data-name="유형별 UFS 관리 명령"><table>
    <thead><tr><th>유형</th><th></th><th class="num">Hibern8 /분</th><th class="num">Hibern8 시간</th><th class="num">Query /분</th><th class="num">WB 조회 /분</th><th class="num">suspend (회차 합)</th></tr></thead>
    <tbody>{mgmt_type_table()}</tbody></table></div>
  <p class="cap">값은 시나리오별 3회 중앙값의 최소~최대예요. Hibern8 시간은 enter 완료부터 다음 exit 요청까지를 더한 비율이에요. WB 조회는 세 속성 묶음 횟수, suspend는 fBackgroundOpsEn clear 횟수예요. 시나리오별 값은 따로 표로 정리했어요(시나리오별 UFS 관리 명령).</p>
  </div>
</section>

<section id="method" aria-labelledby="h-method">
  <h2 id="h-method">측정 방법</h2>
  <div class="prose">
    <ul>
      <li>자동화 도구(agent)로 앱 실행, 탭, 스크롤을 재생하고, 측정할 동작 동안에만 기록을 켰어요.</li>
      <li>기록은 저장장치 드라이버에 들어간 요청 하나하나예요. 요청 크기, 위치, 걸린 시간, 그때 동시에 쌓여 있던 요청 수가 남아요.</li>
      <li>시나리오마다 3번 반복하고, 그 사이 60초를 쉬었어요. 값은 3번의 중앙값이에요.</li>
      <li>"cold"는 측정 전에 메모리 캐시를 비운 상태예요. 갤러리 그리드 처음→끝, 뷰어 1000장, 빠른 fling은 첫 회차 직전에 사진 1000장을 새 이름으로 다시 넣어 썸네일이 없는 상태로 시작했어요. 나머지 갤러리 시나리오(빠른 넘기기, 확대, 삭제, 가벼운 사용)는 썸네일이 있는 상태(warm)예요.</li>
      <li>P1 {n_p1}개를 먼저 재고, 조건을 바꾼 P2 {n_main - n_p1}개를 같은 날 이어서 쟀어요. 시나리오는 저장소의 <code>scenarios/gen.py</code>에 있어요.</li>
      <li>대기를 뺀 57개(A~G와 화면 켜진 홈 대기)는 수집 도구를 고친 뒤 10월 28일 07:50~13:29에 USB를 뽑고 무선 adb로 다시 쟀어요(배터리 93%→62%). 실제 사용처럼 충전하지 않는 상태에 맞추려는 거예요. USB 전원에서는 deviceidle이 깨어 있는 상태로 남아 블록 반납 같은 배경 동작이 달라져요. 녹음 1분과 Chrome 100MB 다운로드는 기다리는 동안 화면이 꺼지지 않게 10초마다 화면을 켰어요(설정은 바꾸지 않음).</li>
      <li>대기(S) {len(s_ids)}개는 다음 날 밤에 USB를 뽑고 무선 adb로 쟀어요. 충전 중이면 대기 상태에 들어가지 않기 때문이에요. 회차 사이 휴식은 120초, 배터리는 100%에서 95%까지 내려갔어요. 3시간 대기는 길어서 1번만 쟀고, 첫 시도가 Deep Sleep 때문에 66분에 끊겨 10월 26일 밤 22:36~01:36에 다시 쟀어요(배터리 100% 그대로).</li>
      <li>갤러리는 화면 프레임 기록(Perfetto)도 같이 남겼어요. 기록 파일을 저장장치에 쓰면 측정이 오염되기 때문에 메모리에 썼어요.</li>
    </ul>
  </div>
  <div class="tw" data-name="시나리오 목록"><table>
    <thead><tr><th>ID</th><th>시나리오</th><th>측정한 동작</th><th class="num">측정 시간(초)</th><th>끝난 뒤 확인</th><th class="num">성공</th></tr></thead>
    <tbody>{scen_table()}</tbody></table></div>
  <p class="cap">대기를 뺀 {n_main}개 × 3번 = {3 * n_main}번 모두 성공한 결과예요. 대기는 3시간 대기를 뺀 4개가 3번씩 모두 성공했고, 3시간 대기는 다시 잰 1번이 3시간을 다 채웠어요. P2의 지도 이동·확대, YouTube 1080p, Chrome 100MB 다운로드는 첫 시도에서 한 회차가 실패해 3번을 다시 쟀어요(아래 한계 참고). Chrome cold start, cold start 순회, 무거운 앱 cold start는 마지막에 홈으로 돌아가서 확인 화면이 런처예요. 갤러리 사진은 NASA의 퍼블릭 도메인 사진 1000장(1.67GiB)이에요.</p>
</section>

<section id="limits" aria-labelledby="h-lim">
  <h2 id="h-lim">한계</h2>
  <div class="note"><b>{"앱·파일 이름과 메타데이터 표시는 새 도구로 다시 재는 중이에요" if OLD else "앱·파일 이름과 메타데이터 표시는 고친 도구로 잰 값이에요"}</b><span>총량, 속도, 크기, 응답 시간은 저장장치 요청 그대로라 믿을 수 있어요.{f" 고친 도구로 다시 잰 시나리오는 {len(FIXED)}개, 남은 것은 {len(OLD)}개({', '.join(nm(x) for x in OLD)})예요. 남은 시나리오의 앱·파일·메타데이터 값은 참고만 해 주세요." if OLD else ""}</span></div>
  <div class="prose"><ul>
    <li><b>수집 도구의 이름 귀속 오류 (10월 28일 고침):</b> 이전 측정에서는 갤러리 뷰어 동안 실행하지 않은 카메라 앱에 쓰기 428MB가, 6.6MB짜리 배터리 로그 파일에 866MB가 붙었어요. 커널 writeback 스레드가 처음 내려쓴 파일 이름을 뒤 파일에도 계속 붙였고, f2fs가 여러 스레드가 함께 쓰는 bio를 다른 스레드가 제출하면 그 스레드 이름이 붙었고, 블록 계층 worker(kblockd)가 발급한 요청은 앱 대신 kworker로 찍혔어요. ftrace로 블록마다 주인을 대조하니 쓰기의 38%가 다른 파일 이름이었고, 고친 뒤에는 0%예요. 실제 시나리오로 빈틈을 점검해 카메라 Direct IO, 시스템 파티션(erofs 압축) 읽기, /apex(loop 장치) 읽기, mmap으로 쓴 파일, f2fs node 쓰기의 주인 파일, Checkpoint·GC 표시도 고쳤어요. Chrome 첫 실행 ×5의 Read 중 앱과 파일이 맞게 붙은 비율은 44%에서 98%, 카메라 사진 10장의 Write는 10%에서 97%가 됐어요(<code>kakaromo/bpftrace</code> 920fafa~d4aac83). 같은 문제로 메타데이터(node·checkpoint) 표시도 틀린 경우가 있어서, 메타데이터 비율과 쓰기 경로 분류는 다시 잰 값만 믿을 수 있어요.</li>
    <li><b>남은 수집 한계:</b> 여러 파일의 node가 한 요청으로 합쳐지면 첫 파일 하나만 이름으로 남아요. 측정 중에 연 적 없는 파일의 node 쓰기는 경로 없이 inode 번호로만 나와요. f2fs GC가 옮기는 데이터는 원래 파일을 알 수 없어 이름 없이 GC로 표시해요.</li>
    <li><b>쓸 수 없는 표시:</b> 쓰기 요청의 sync·fsync 표시가 104,971건 모두 0이라 쓰지 않았어요. 읽기/쓰기 표시와 메타데이터 표시도 맞지 않는 경우가 있어서, 요청 명령어로 다시 판정했어요.</li>
    <li><b>앱 실행 도구의 몫:</b> 앱을 열 때 쓰는 <code>monkey</code> 명령이 캐시를 비운 뒤마다 약 50MB를 읽어요. 앱 실행 시나리오의 총량에 이 양이 포함돼 있어요.</li>
    <li><b>표본:</b> 기기 1대, 시나리오당 3번이에요. 회차 간 차이가 큰 시나리오({', '.join(nm(x) for x in cv_hi)})는 횟수를 늘려야 해요. 갤러리 첫 회차는 시나리오당 1번뿐이에요.</li>
    <li><b>배경 I/O:</b> 개인 계정이 로그인된 상태라 동기화·로그 같은 배경 활동이 섞여 있어요.</li>
    <li><b>검색어 입력:</b> 자동화 도구의 글자 입력은 키보드가 한국어 모드면 영문이 자모로 바뀌어요. P2부터는 매번 영문 키보드로 바꿨지만, P1의 YouTube 검색(검색+결과 스크롤 "nasa 우주", 영상 3분 "nasa 4k")은 의도와 다른 검색어로 들어갔을 수 있어요. 결과 목록이나 영상은 열렸기 때문에 측정 자체는 유효해요.</li>
    <li><b>다시 잰 시나리오:</b> 지도 이동·확대는 자동화 도구가 콤마가 든 명령을 회차별 값 목록으로 잘라 쓰는 문제로 실패했어요(<code>benchmark/scenario.go</code>의 <code>resolveLoopVariable</code>). 콤마를 기기에서 만들어 넣도록 바꿨어요. YouTube 1080p는 한 회차에서 재생 확인이 시간 안에 안 됐고, Chrome 100MB 다운로드는 "다시 다운로드" 확인 창이 늦게 떠서 한 회차가 실패했어요. 셋 다 3번을 새로 쟀어요.</li>
    <li><b>권한 창:</b> 지도는 위치 권한이 정해지지 않아 실행할 때 권한 창이 뜰 수 있어요. 최근 앱 전환과 지도 이동·확대는 권한 창이 있으면 뒤로 키로 닫기만 했어요(본 측정에서는 뜨지 않았어요).</li>
    <li><b>대기 측정의 영향:</b> 대기 중에는 무선 adb로 기록을 계속 내보냈어요. 기록 자체는 저장장치에 쓰지 않지만, Wi-Fi와 adb가 켜져 있어 기기가 완전히 잠들지 못했을 수 있어요. 약 2초마다 깨어나는 주기가 측정 경로 때문인지는 USB 없이 기기 안에 기록을 쌓는 방식으로 다시 확인해야 해요. OxygenOS는 화면을 끄고 5분 안에 deep doze에 들어갔어요.</li>
    <li><b>3시간 대기 다시 잼:</b> 첫 3시간 대기는 66분째(04:35)에 무선 adb 연결이 끊겼어요. OxygenOS 배터리 앱의 Deep Sleep 모드가 학습한 수면 시간대(23:30~07:00)에 Wi-Fi를 끈 거예요. 설정에서 수면 대기 최적화를 끄고 다시 재니 3시간(10,764초)을 끊김 없이 채웠어요. 이 설정을 끈 만큼 실제 사용자의 밤보다 Wi-Fi가 더 오래 켜져 있었을 수 있어요. 대기 시나리오의 앱 이름은 측정 뒤 프로세스 목록 없이 스레드 이름으로 붙였어요.</li>
    <li><b>측정하지 않은 것:</b> Facebook 피드는 로그아웃 상태라, 메시지는 계정 연결 화면이 떠서 뺐어요. Netflix는 쓰지 않았어요. Instagram 피드·릴스는 사용자가 로그인한 뒤, TikTok은 첫 실행 동의 창을 사용자가 처리한 뒤 10월 27일에 따로 쟀어요. YouTube Shorts는 10월 27일 밤 USB를 뽑고 무선으로 쟀어요. 알림 같은 권한 요청 창이 뜨면 '허용 안함'을 눌러 닫도록 했어요. 좋아요·팔로우가 남지 않도록 영상과 게시물은 탭하지 않고 스크롤만 했어요. 릴스에는 광고도 섞여 나와요.</li>
    <li><b>다음 단계:</b> 다시 잰 값으로 파일 종류별(DB, 캐시, 앱 파일, 미디어) 분석과 Chrome 다운로드 2배 쓰기의 원인을 추가해요. 화면이 꺼진 대기 시나리오 4개도 고친 도구로 다시 재요. 삭제 후 블록 반납 시점은 측정 구간을 늘려 따로 봐요.</li>
  </ul></div>
</section>

<section id="appendix" aria-labelledby="h-app">
  <h2 id="h-app">부록</h2>
  <p class="prose muted">본문을 뒷받침하는 상세 지표예요. 처음 읽을 때는 건너뛰어도 돼요.</p>

  <details class="ap" open>
    <summary>A. 시나리오별 상세 지표</summary>
    <div class="tw" data-name="시나리오별 상세 지표"><table>
      <thead><tr><th>ID</th><th class="num">읽기</th><th class="num">쓰기</th><th class="num">쓰기 비중</th><th class="num">최고 MB/s</th><th class="num">이어진 요청 R/W</th><th class="num">응답 99% R/W (ms)</th><th class="num">동시 요청 최대</th><th class="num">메타데이터</th><th class="num">쉬는 시간</th><th class="num">회차 차이</th><th>많은 요청 형태</th></tr></thead>
      <tbody>{sig_table()}</tbody></table></div>
    <dl class="gloss">
      <div><dt>회색 숫자</dt><dd>3번 중 가장 적었던 값과 많았던 값</dd></div>
      <div><dt>이어진 요청</dt><dd>바로 앞 요청이 끝난 위치에서 이어서 시작한 요청의 비율(순차). 높을수록 큰 파일을 통째로 읽거나 쓴 것</dd></div>
      <div><dt>응답 99%</dt><dd>요청의 99%가 이 시간 안에 끝났다는 뜻(dtoc p99)</dd></div>
      <div><dt>동시 요청 최대</dt><dd>요청을 보낼 때 이미 쌓여 있던 요청 수의 99번째 값(QD p99)</dd></div>
      <div><dt>메타데이터</dt><dd>쓰기 중 파일 내용이 아닌 f2fs 관리 정보(node·checkpoint)의 비율</dd></div>
      <div><dt>쉬는 시간</dt><dd>0.1초 단위로 잘랐을 때 요청이 하나도 없는 칸의 비율</dd></div>
      <div><dt>회차 차이</dt><dd>3번 총량의 변동계수. 0.5를 넘으면 붉게 표시</dd></div>
      <div><dt>많은 요청 형태</dt><dd>바이트 기준 상위 2개. 예: SEQ 132–512K W 75% = 132~512KB 크기의 이어진 쓰기가 75%</dd></div>
    </dl>
  </details>

  <details class="ap">
    <summary>B. 요청 크기 · 응답 시간 · 요청 간격 분포</summary>
    <figure>
      {legend(D["meta"]["buckets"]["size"])}
      <div class="pair"><div id="f-size-R" class="chart" style="height:{VOL_H}px"></div><div id="f-size-W" class="chart" style="height:{VOL_H}px"></div></div>
      <figcaption><b>요청 크기(건수 비율).</b> 카메라 사진은 132–512KB 쓰기, 파일 복사·동영상·앱 설치는 512KB보다 큰 쓰기가 많아요.</figcaption>
    </figure>
    <figure>
      {legend(D["meta"]["buckets"]["dtoc"])}
      <div class="pair"><div id="f-dtoc-R" class="chart" style="height:{VOL_H}px"></div><div id="f-dtoc-W" class="chart" style="height:{VOL_H}px"></div></div>
      <figcaption><b>응답 시간(건수 비율).</b> 앱 실행·웹·미디어의 쓰기는 77~93%가 0.1ms 안에 끝나요. 큰 연속 쓰기(E2)는 1ms를 넘는 요청이 약 25%예요.</figcaption>
    </figure>
    <figure>
      {legend(D["meta"]["buckets"]["gap"], 1)}
      <div id="f-gap" class="chart" style="height:{VOL_H}px"></div>
      <figcaption><b>요청 사이 간격(DtoD, dispatch-to-dispatch).</b> 앞 요청을 보낸 시각부터 다음 요청을 보낸 시각까지예요. 처리 시간(DtoC)과는 달라요. 모든 시나리오에서 63~94%의 요청이 앞 요청과 1ms 안에 붙어 와요. 몰렸다가 쉬는 모양이에요.</figcaption>
    </figure>
  </details>

  <details class="ap">
    <summary>C. 유형 지도와 전체 시간축</summary>
    <figure>
      <div class="legend">{"".join(f'<span><b>{t}</b> {E(n)}</span>' for t, n in D["types"].items())}<span class="muted">라벨의 첫 글자가 유형 · 점 크기 = 총량</span></div>
      <div id="f-map" class="chart" style="height:460px"></div>
      <figcaption><b>유형 지도.</b> 가로는 이어진 요청 비율, 세로는 쓰기 비중, 점 크기는 총량이에요. 카메라는 오른쪽 위, 앱 실행은 아래쪽, 웹·피드는 왼쪽 위에 모여요.</figcaption>
    </figure>
    <figure>
      <div class="legend"><span><i style="background:var(--read)"></i>읽기 (위)</span><span><i style="background:var(--write)"></i>쓰기 (아래)</span><span class="muted">칸마다 세로 범위가 달라요</span></div>
      <div class="multi" id="f-tl"></div>
      <figcaption><b>전체 시나리오의 1초 단위 속도.</b> 중앙값 회차로 그렸어요.</figcaption>
    </figure>
  </details>

  <details class="ap">
    <summary>D. 저장장치 위치(LBA) 접근 지도</summary>
    <figure>
      <div class="controls"><label for="sel-lba">시나리오</label><select id="sel-lba"></select><span class="muted" id="lba-note"></span></div>
      <div class="pair"><div id="f-lba-R" class="chart" style="height:340px"></div><div id="f-lba-W" class="chart" style="height:340px"></div></div>
      <figcaption><b>어느 위치를 언제 읽고 썼는지.</b> 세로는 저장장치 주소(0~{D['meta']['lbaMaxGB']:.0f}GB), 가로는 측정 시간이에요. 진할수록 많이 접근했어요.</figcaption>
    </figure>
  </details>

  <details class="ap">
    <summary>E. 갤러리 프레임 통계</summary>
    <div class="tw" data-name="갤러리 프레임 통계"><table>
      <thead><tr><th>회차</th><th class="num">#</th><th class="num">프레임</th><th class="num">끊긴 프레임</th><th class="num">프레임 시간 중앙/99% ms</th><th class="num">gfxinfo 90/99% ms</th><th class="num">프레임당 읽기 끊김/정상</th><th class="num">읽기 있던 프레임 끊김/정상</th></tr></thead>
      <tbody>{jank_table()}</tbody></table></div>
    <p class="cap">끊긴 프레임은 FrameTimeline에서 App Deadline Missed로 표시된 프레임이에요. 읽기는 프레임 시작 0.1초 전부터 끝까지 갤러리 프로세스의 저장장치 읽기예요.</p>
  </details>

  <details class="ap">
    <summary>F. 프로세스별 상위 4개{' (일부 이전 도구 값)' if OLD else ''}</summary>
    <div class="tw" data-name="프로세스별 상위 4개"><table><thead><tr><th>ID</th><th class="num">회차</th><th>프로세스 (읽기 · 쓰기 MB)</th></tr></thead><tbody>{proc_table()}</tbody></table></div>
  </details>

  <details class="ap">
    <summary>G. 원자료 위치</summary>
    <div class="prose"><ul>
      <li>회차별 실행 결과: <code>uxtest/runs/&lt;ID&gt;/&lt;시각&gt;.json</code></li>
      <li>저장장치 기록: <code>~/.agent-standalone/archive/jobs/&lt;시각&gt;_scenario_ux-&lt;ID&gt;/trace/&lt;id&gt;/result_fsio_ufs.parquet</code></li>
      <li>프레임 기록: <code>uxtest/runs/G1~G5/&lt;시각&gt;/</code> (실행 결과 JSON 과 같은 이름의 폴더)</li>
      <li>집계 코드: <code>uxtest/report/extract.py</code> → <code>data.json</code> → <code>build_report.py</code></li>
    </ul></div>
  </details>
  <details class="ap">
    <summary>H. 시나리오별 UFS 관리 명령</summary>
    <div class="tw" data-name="시나리오별 UFS 관리 명령"><table>
      <thead><tr><th>ID</th><th class="num">Hibern8 /분</th><th class="num">Hibern8 시간</th><th class="num">H8 exit ms</th><th class="num">Query /분</th><th class="num">bBackgroundOpStatus /분</th><th class="num">WB 조회 /분</th><th class="num">suspend</th><th class="num">qTimestamp</th></tr></thead>
      <tbody>{mgmt_table()}</tbody></table></div>
    <p class="cap">/분 값과 H8 exit는 3회 중앙값, suspend(fBackgroundOpsEn clear)와 qTimestamp 쓰기는 회차 합이에요.</p>
  </details>
</section>

<footer>P1·P2 측정 2026-10-25, 대기 측정 2026-10-26 · 참고: AndroStep, IISWC 2015 모바일 I/O 특성화, SNIA 워크로드 시그니처, Perfetto FrameTimeline 문서</footer>
</div>

<script>
window.DATA = {json.dumps(CHART_DATA, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")};
const PROV = {json.dumps(PROV, ensure_ascii=False)};
</script>
<script>
(function () {{
  const K = DATA.order;
  UX.vol('f-vol', K, PROV.vol);
  document.querySelectorAll('[data-tl]').forEach(el => UX.timeline(el, el.dataset.tl, el.dataset.tl + ' ' + DATA.names[el.dataset.tl] + ' · 1초 단위 MB/s (위 읽기, 아래 쓰기)', PROV.timeline));
  UX.stack('f-size-R', K, 'size', 'R', DATA.buckets.size, '요청 크기 분포 · 읽기 (건수 %)', PROV.size);
  UX.stack('f-size-W', K, 'size', 'W', DATA.buckets.size, '요청 크기 분포 · 쓰기 (건수 %)', PROV.size);
  UX.stack('f-dtoc-R', K, 'dtoc', 'R', DATA.buckets.dtoc, '응답 시간 분포 · 읽기 (건수 %)', PROV.dtoc);
  UX.stack('f-dtoc-W', K, 'dtoc', 'W', DATA.buckets.dtoc, '응답 시간 분포 · 쓰기 (건수 %)', PROV.dtoc);
  UX.stack('f-gap', K, 'gap', null, DATA.buckets.gap, '요청 사이 간격 분포 (건수 %)', PROV.gap, 1);
  UX.map('f-map', K, PROV.map);
  UX.minis('f-tl', K, k => 's-' + DATA.ids[k] + '.html', PROV.timeline);
  const selL = document.getElementById('sel-lba');
  K.forEach(k => {{ const o = document.createElement('option'); o.value = k; o.textContent = DATA.labels[k] + ' ' + DATA.names[k]; selL.appendChild(o); }});
  selL.value = 'D2';
  const note = () => {{ const k = selL.value; document.getElementById('lba-note').textContent = `${{DATA.rep[k]}}회차 · 구간 ${{DATA.dur[k].toFixed(0)}}초 · 칸 = ${{(DATA.dur[k] / 60).toFixed(1)}}초 × ${{(DATA.lbaMaxGB / 48).toFixed(1)}}GB`; }};
  note();
  const lr = UX.lba('f-lba-R', () => selL.value, 'R', PROV.lba), lw = UX.lba('f-lba-W', () => selL.value, 'W', PROV.lba);
  selL.addEventListener('change', () => {{ note(); UX.render(lr); UX.render(lw); }});
  const selJ = document.getElementById('sel-jank'); let jk = 'G2-2';
  const jc = UX.jank('f-jank', () => jk, PROV.jank);
  selJ.addEventListener('click', e => {{
    const bt = e.target.closest('button'); if (!bt) return;
    jk = bt.dataset.v; selJ.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === bt)));
    UX.render(jc);
  }});
}})();
</script>
"""

import pages  # noqa: E402  유형·시나리오 하위 페이지

SITE = HERE / "site"
(SITE / "assets").mkdir(parents=True, exist_ok=True)
for f in ("report.css", "report.js"):
    (SITE / "assets" / f).write_text((HERE / "web" / f).read_text())
(SITE / "index.html").write_text(PAGE)
n = pages.build(SITE, dict(D=D, S=S, J=J, C=CHART_DATA, PROV=PROV, HEAD=HEAD, PAGE=PAGE, DOING=DOING, label=label, mb=mb,
                            rng=rng, med=med, legend=legend, E=E, sig_table=sig_table))
print(f"wrote {SITE}/index.html ({len(PAGE) / 1024:.0f} KB) + 하위 페이지 {n}개")
