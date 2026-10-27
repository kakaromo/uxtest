"""유형별·시나리오별 하위 페이지 (build_report.py 에서 부른다).

  type-<유형>.html  유형 요약(본문의 유형 글) + 시나리오 표 + 총량·시간축·분포 차트 + 상세 지표
  s-<ID>.html       시나리오 하나: 무엇을 했나, 회차별 값, 1초 시간축, 분포, 위치 지도, 프로세스·파일, 스텝, 원자료
"""
import json
import re

TYPES_ORDER = ["A", "B", "C", "D", "E", "F", "G", "S"]


def doc(title, head, body, data, prov, init):
    data_js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{head}
</head>
<body>
<div class="doc">
{body}
</div>
<script>
window.DATA = {data_js};
const PROV = {json.dumps(prov, ensure_ascii=False)};
</script>
<script>
(function () {{
{init}
}})();
</script>
</body>
</html>
"""


def subset(C, keys, jank_keys=()):
    """CHART_DATA 에서 이 페이지에 필요한 시나리오만."""
    per = ["labels", "names", "type", "vol", "size", "dtoc", "gap", "seq", "timeline", "rep", "lba", "dur", "ids"]
    out = {k: {x: C[k][x] for x in keys} for k in per}
    out |= {"order": keys, "types": C["types"], "buckets": C["buckets"], "lbaMaxGB": C["lbaMaxGB"],
            "jank": {j: C["jank"][j] for j in jank_keys if j in C["jank"]}}
    return out


def build(site, ctx):
    D, S, J, C, PROV = ctx["D"], ctx["S"], ctx["J"], ctx["C"], ctx["PROV"]
    E, mb, med, rng, label, legend, DOING = ctx["E"], ctx["mb"], ctx["med"], ctx["rng"], ctx["label"], ctx["legend"], ctx["DOING"]
    HEAD, PAGE = ctx["HEAD"], ctx["PAGE"]
    types = [t for t in TYPES_ORDER if t in D["types"]]
    by_type = {t: [s for s in D["scenarios"] if s["type"] == t] for t in types}
    ids_in = {t: list(dict.fromkeys(s["id"] for s in by_type[t])) for t in types}
    all_ids = [i for t in types for i in ids_in[t]]
    n = 0

    def crumb(*parts):
        out = ['<a href="index.html">보고서</a>']
        for href, txt in parts:
            out.append('<span aria-hidden="true">›</span>')
            out.append(f'<a href="{href}">{E(txt)}</a>' if href else f'<span>{E(txt)}</span>')
        return f'<nav class="crumb" aria-label="위치">{"".join(out)}</nav>'

    def type_chips(cur):
        return '<nav class="chips" aria-label="유형">' + "".join(
            f'<a href="type-{t}.html"{" aria-current=page" if t == cur else ""}>{t} {E(D["types"][t])}</a>' for t in types) + "</nav>"

    def scen_chips(t, cur):
        return '<nav class="chips" aria-label="같은 유형의 시나리오">' + "".join(
            f'<a href="s-{i}.html"{" aria-current=page" if i == cur else ""}>{i}</a>' for i in ids_in[t]) + "</nav>"

    def nm(s):
        return label(s).split(" · ")[0]

    # ── 유형 페이지 ─────────────────────────────────────
    for ti, t in enumerate(types):
        rows = by_type[t]
        keys = [s["key"] for s in rows]
        m = re.search(rf'<article class="type" id="t-{t}">.*?</article>', PAGE, re.S)
        art = m.group(0) if m else ""
        art = re.sub(r'\s*<a class="more-link"[^>]*>.*?</a>', "", art)
        art = art.replace(f'id="t-{t}"', f'id="sum-{t}"')
        trs = []
        for s in rows:
            k = s["key"]
            tag = f'<span class="tag">{s["cache"]}</span>' if s["cache"] else ""
            trs.append(f"""<tr><td class="id"><a href="s-{s['id']}.html">{s['id']}</a>{tag}</td><td>{E(nm(s))}</td>
              <td class="num">P{s['prio']}</td><td>{E(DOING.get(s['id'], ''))}</td><td class="num">{med(k, 'durSec'):.0f}</td>
              <td class="num">{rng(k, 'readMB')}</td><td class="num">{rng(k, 'writeMB')}</td><td class="num">{med(k, 'peakMBs'):.0f}</td>
              <td class="num {'warn' if s['cv'] > 0.5 else ''}">{s['cv']:.2f}</td></tr>""")
        jank_keys = [f"{sid}-{rep}" for (sid, rep) in sorted(J) if sid in ids_in[t] and "sec" in J[(sid, rep)]]
        jank_html = ""
        if jank_keys:
            btns = "".join(f'<button type="button" data-v="{j}" aria-pressed="{str(i == 0).lower()}">{j.split("-")[0]} {j.split("-")[1]}회차</button>'
                           for i, j in enumerate(jank_keys))
            jrows = "".join(jank_row(sid, rep, J[(sid, rep)]) for (sid, rep) in sorted(J) if sid in ids_in[t] and "jank" in J[(sid, rep)])
            jank_html = f"""
<section aria-labelledby="h-jank">
  <h2 id="h-jank">화면 끊김과 저장장치 읽기</h2>
  <figure>
    <div class="controls"><span id="seg-j">회차</span><div class="seg" id="sel-jank" role="group" aria-labelledby="seg-j">{btns}</div></div>
    <div id="f-jank" class="chart" style="height:340px"></div>
    <figcaption>위는 1초마다 갤러리가 읽은 양, 아래는 1초마다 앱이 늦어 끊긴 프레임 수예요.</figcaption>
  </figure>
  <div class="tw" data-name="{t} 프레임 통계"><table>
    <thead><tr><th>회차</th><th class="num">#</th><th class="num">프레임</th><th class="num">끊긴 프레임</th><th class="num">프레임 시간 중앙/99% ms</th><th class="num">gfxinfo 90/99% ms</th><th class="num">프레임당 읽기 끊김/정상</th><th class="num">읽기 있던 프레임 끊김/정상</th></tr></thead>
    <tbody>{jrows}</tbody></table></div>
</section>"""
        h = 22 * len(keys) + 60
        prev_t, next_t = types[ti - 1] if ti else None, types[ti + 1] if ti + 1 < len(types) else None
        body = f"""
<header class="title">
  {crumb((None, f"{t} {D['types'][t]}"))}
  <div class="eyebrow">{t} 유형 · 시나리오 {len(ids_in[t])}개</div>
  <h1>{E(D['types'][t])}</h1>
  {type_chips(t)}
</header>

<section aria-labelledby="h-sum">
  <h2 id="h-sum">요약</h2>
  {art}
</section>

<section aria-labelledby="h-list">
  <h2 id="h-list">시나리오</h2>
  <p class="prose muted">ID를 누르면 시나리오 페이지로 가요. 읽기·쓰기는 3번의 중앙값이고 회색은 최소–최대예요.</p>
  <div class="tw" data-name="{t} 시나리오 목록"><table>
    <thead><tr><th>ID</th><th>시나리오</th><th class="num">구분</th><th>측정한 동작</th><th class="num">측정 시간(초)</th><th class="num">읽기</th><th class="num">쓰기</th><th class="num">최고 MB/s</th><th class="num">회차 차이</th></tr></thead>
    <tbody>{"".join(trs)}</tbody></table></div>
</section>

<section aria-labelledby="h-vol">
  <h2 id="h-vol">총량과 시간축</h2>
  <figure>
    <div class="legend"><span><i style="background:var(--read)"></i>읽기</span><span><i style="background:var(--write)"></i>쓰기</span><span class="muted">점 = 중앙값, 선 = 최소~최대, 로그 눈금</span></div>
    <div id="f-vol" class="chart" style="height:{max(h, 200)}px"></div>
  </figure>
  <figure>
    <div class="legend"><span><i style="background:var(--read)"></i>읽기 (위)</span><span><i style="background:var(--write)"></i>쓰기 (아래)</span><span class="muted">칸마다 세로 범위가 달라요 · 칸을 누르면 시나리오 페이지</span></div>
    <div class="multi" id="f-tl"></div>
  </figure>
</section>

<section aria-labelledby="h-dist">
  <h2 id="h-dist">요청 모양</h2>
  <figure>
    {legend(D["meta"]["buckets"]["size"])}
    <div class="pair"><div id="f-size-R" class="chart" style="height:{max(h, 160)}px"></div><div id="f-size-W" class="chart" style="height:{max(h, 160)}px"></div></div>
  </figure>
  <figure>
    {legend(D["meta"]["buckets"]["dtoc"])}
    <div class="pair"><div id="f-dtoc-R" class="chart" style="height:{max(h, 160)}px"></div><div id="f-dtoc-W" class="chart" style="height:{max(h, 160)}px"></div></div>
  </figure>
  <figure>
    {legend(D["meta"]["buckets"]["gap"], 1)}
    <div id="f-gap" class="chart" style="height:{max(h, 160)}px"></div>
  </figure>
  <div class="tw" data-name="{t} 상세 지표"><table>
    <thead><tr><th>ID</th><th class="num">읽기</th><th class="num">쓰기</th><th class="num">쓰기 비중</th><th class="num">최고 MB/s</th><th class="num">이어진 요청 R/W</th><th class="num">응답 99% R/W (ms)</th><th class="num">동시 요청 최대</th><th class="num">메타데이터</th><th class="num">쉬는 시간</th><th class="num">회차 차이</th><th>많은 요청 형태</th></tr></thead>
    <tbody>{ctx["sig_table"](t)}</tbody></table></div>
</section>
{jank_html}
<nav class="pnav" aria-label="다른 유형">
  <span>{f'<a href="type-{prev_t}.html">← {prev_t} {E(D["types"][prev_t])}</a>' if prev_t else ''}</span>
  <span>{f'<a href="type-{next_t}.html">{next_t} {E(D["types"][next_t])} →</a>' if next_t else ''}</span>
</nav>
<footer>P1·P2 측정 2026-10-25, 대기 측정 2026-10-26 · <a href="index.html">전체 보고서로</a></footer>"""
        init = f"""  const K = DATA.order;
  UX.vol('f-vol', K, PROV.vol);
  UX.minis('f-tl', K, k => 's-' + DATA.ids[k] + '.html', PROV.timeline);
  document.querySelectorAll('[data-tl]').forEach(el => UX.timeline(el, el.dataset.tl, el.dataset.tl + ' ' + DATA.names[el.dataset.tl] + ' · 1초 단위 MB/s (위 읽기, 아래 쓰기)', PROV.timeline));
  UX.stack('f-size-R', K, 'size', 'R', DATA.buckets.size, '요청 크기 분포 · 읽기 (건수 %)', PROV.size);
  UX.stack('f-size-W', K, 'size', 'W', DATA.buckets.size, '요청 크기 분포 · 쓰기 (건수 %)', PROV.size);
  UX.stack('f-dtoc-R', K, 'dtoc', 'R', DATA.buckets.dtoc, '응답 시간 분포 · 읽기 (건수 %)', PROV.dtoc);
  UX.stack('f-dtoc-W', K, 'dtoc', 'W', DATA.buckets.dtoc, '응답 시간 분포 · 쓰기 (건수 %)', PROV.dtoc);
  UX.stack('f-gap', K, 'gap', null, DATA.buckets.gap, '요청 사이 간격 분포 (건수 %)', PROV.gap, 1);
  const selJ = document.getElementById('sel-jank');
  if (selJ) {{
    let jk = {json.dumps(jank_keys[0] if jank_keys else "")};
    const jc = UX.jank('f-jank', () => jk, PROV.jank);
    selJ.addEventListener('click', e => {{
      const bt = e.target.closest('button'); if (!bt) return;
      jk = bt.dataset.v; selJ.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === bt)));
      UX.render(jc);
    }});
  }}"""
        (site / f"type-{t}.html").write_text(doc(f"{t} {D['types'][t]} · UX I/O", HEAD, body, subset(C, keys, jank_keys), PROV, init))
        n += 1

    # ── 시나리오 페이지 ─────────────────────────────────
    for ii, sid in enumerate(all_ids):
        grp = [s for s in D["scenarios"] if s["id"] == sid]
        s0 = grp[0]
        t = s0["type"]
        keys = [s["key"] for s in grp]
        desc = re.sub(r"^\[[^\]]*\]\s*", "", s0["description"])
        notes = ""
        mm = re.search(r"\s(준비: .*)$", desc)
        if mm:
            notes = mm.group(1)
            desc = desc[:mm.start()]
        runs = s0["perRun"]
        ck = s0["checks"]
        run_rows = "".join(
            f"""<tr><td class="num">{r['repeat']}</td><td>{('cold' if r['repeat'] == 1 else 'warm') if len(grp) > 1 else (grp[0]['cache'] or '')}</td>
              <td class="num">{r['readMB']:.1f}</td><td class="num">{r['writeMB']:.1f}</td><td class="num">{r['discardMB']:.1f}</td><td class="num">{r['durSec']:.1f}</td>
              <td>{E(chk(ck.get(str(r['repeat'])) or ck.get(r['repeat']) or {}))}</td><td><code>{r['traceJobId']}</code></td></tr>"""
            for r in runs)
        # 그룹별(cold / warm 또는 하나) 블록
        blocks, init_lines = [], []
        for s in grp:
            k = s["key"]
            rep = s["rep"]["repeat"]
            tj = next((r["traceJobId"] for r in runs if r["repeat"] == rep), "")
            pv = (f'<p><b>이 그래프의 원자료</b> {rep}회차 · trace job <code>{tj}</code> · '
                  f'<code>~/.agent-standalone/archive/jobs/*/trace/{tj}/result_fsio_ufs.parquet</code></p>')
            gh = ""
            if len(grp) > 1:
                gh = f'<div class="group-h"><h3>{"첫 회차 (cold)" if s["cache"] == "cold" else "2·3회차 (warm)"}</h3><span class="muted">{"썸네일이 없는 상태" if s["cache"] == "cold" else "썸네일이 있는 상태, 2회 중앙값"}</span></div>'
            kv = [("읽기", rng(k, "readMB")), ("쓰기", rng(k, "writeMB")), ("블록 반납", mb(med(k, "discardMB"))),
                  ("최고 속도", f"{med(k, 'peakMBs'):.0f}<small>MB/s</small>"), ("측정 시간", f"{med(k, 'durSec'):.0f}<small>초</small>"),
                  ("쉬는 시간", f"{med(k, 'idlePct'):.0f}<small>%</small>"), ("동시 요청 최대", f"{med(k, 'qdP99'):.0f}<small>개 (p99)</small>"),
                  ("응답 99% 읽기", f"{med(k, 'dtocP99', 'R'):.2f}<small>ms</small>"), ("응답 99% 쓰기", f"{med(k, 'dtocP99', 'W'):.2f}<small>ms</small>"),
                  ("이어진 요청 R/W", f"{med(k, 'seq', 'R'):.0f}/{med(k, 'seq', 'W'):.0f}<small>%</small>"),
                  ("메타데이터", f"{med(k, 'metaPct'):.0f}<small>%</small>"), ("회차 차이", f"{s['cv']:.2f}<small>CV</small>")]
            if "wakesPerMin" in s:  # 대기(S) 이후 추출분에만 있다
                kv += [("깨어남", f"{med(k, 'wakesPerMin'):.0f}<small>번/분</small>"), ("가장 긴 쉼", f"{med(k, 'maxGapSec'):.1f}<small>초</small>"),
                       ("flush", f"{med(k, 'flushPerSec'):.1f}<small>번/초</small>")]
            kvh = "".join(f"<div><dt>{a}</dt><dd>{b}</dd></div>" for a, b in kv)
            st = "".join(f"<tr><td>{x['seq']}</td><td>{x['size']}</td><td>{'읽기' if x['dir'] == 'R' else '쓰기'}</td><td class='num'>{x['pct']:.1f}</td></tr>" for x in s["rep"]["streams"])
            pr = "".join(f"<tr><td>{E(p['name'])}</td><td class='num'>{p['pid']}</td><td class='num'>{p['readMB']:.1f}</td><td class='num'>{p['writeMB']:.1f}</td><td class='muted'>{E((p.get('threads') or '')[:120])}</td></tr>" for p in s["rep"]["procs"])
            fl = "".join(f"<tr><td><code>{E(f['name'])}</code></td><td>{E(f.get('kind', ''))}</td><td class='num'>{f['readMB']:.1f}</td><td class='num'>{f['writeMB']:.1f}</td></tr>" for f in s["rep"]["files"])
            kid = k.replace("-", "_")
            blocks.append(f"""
  {gh}
  <dl class="kv">{kvh}</dl>
  <figure><div id="tl-{kid}" class="chart" style="height:260px"></div>
    <figcaption>{rep}회차({"한 번만 잰 회차" if s["repeats"] < 2 else "3번 중 총량이 가운데인 회차"})의 1초 단위 읽기(위)·쓰기(아래) MB/s.</figcaption></figure>
  <figure>
    {legend(D["meta"]["buckets"]["size"])}
    <div class="pair"><div id="sz-{kid}" class="chart" style="height:150px"></div><div id="dt-{kid}" class="chart" style="height:150px"></div></div>
    {legend(D["meta"]["buckets"]["gap"], 1)}
    <div id="gp-{kid}" class="chart" style="height:110px"></div>
  </figure>
  <figure>
    <div class="pair"><div id="lr-{kid}" class="chart" style="height:300px"></div><div id="lw-{kid}" class="chart" style="height:300px"></div></div>
    <figcaption>세로는 저장장치 주소(0~{D['meta']['lbaMaxGB']:.0f}GB), 가로는 측정 시간({med(k, 'durSec'):.0f}초)이에요. 진할수록 많이 접근했어요.</figcaption>
  </figure>
  <div class="tw" data-name="{k} 많은 요청 형태"><table><thead><tr><th>순차/랜덤</th><th>크기</th><th>방향</th><th class="num">바이트 %</th></tr></thead><tbody>{st}</tbody></table></div>
  <div class="tw" data-name="{k} 프로세스 (확인 중)"><table><thead><tr><th>프로세스</th><th class="num">pid</th><th class="num">읽기 MB</th><th class="num">쓰기 MB</th><th>스레드</th></tr></thead><tbody>{pr}</tbody></table></div>
  <div class="tw" data-name="{k} 파일 (확인 중)"><table><thead><tr><th>파일</th><th>종류</th><th class="num">읽기 MB</th><th class="num">쓰기 MB</th></tr></thead><tbody>{fl}</tbody></table></div>
  <p class="cap">프로세스·파일 이름은 수집 도구의 표시라 일부가 맞지 않아요 (특히 커널 writeback 쓰기). 총량은 정확해요.</p>""")
            P = json.dumps(pv)
            init_lines.append(f"""  UX.timeline('tl-{kid}', '{k}', '{k} · 1초 단위 MB/s (위 읽기, 아래 쓰기)', PROV.timeline + {P}, {{ axes: true }});
  UX.dist('sz-{kid}', '{k}', 'size', DATA.buckets.size, '{k} 요청 크기 (건수 %)', PROV.size);
  UX.dist('dt-{kid}', '{k}', 'dtoc', DATA.buckets.dtoc, '{k} 응답 시간 (건수 %)', PROV.dtoc);
  UX.stack('gp-{kid}', ['{k}'], 'gap', null, DATA.buckets.gap, '{k} 요청 사이 간격 (건수 %)', PROV.gap, 1);
  UX.lba('lr-{kid}', () => '{k}', 'R', PROV.lba + {P});
  UX.lba('lw-{kid}', () => '{k}', 'W', PROV.lba + {P});""")
        # 스텝 (측정 구간 강조)
        on, li = False, []
        for i, x in enumerate(s0["steps"]):
            if x["type"] == "trace_start":
                on = True
            li.append(f'<li{" class=m" if on else ""}><span class="st">{x["type"]}</span>{E(x["label"])}</li>')
            if x["type"] == "trace_stop":
                on = False
        jk = [f"{sid}-{r}" for (i_, r) in sorted(J) if i_ == sid and "sec" in J[(i_, r)]]
        jank_html = ""
        if jk:
            btns = "".join(f'<button type="button" data-v="{j}" aria-pressed="{str(i == 0).lower()}">{j.split("-")[1]}회차</button>' for i, j in enumerate(jk))
            jrows = "".join(jank_row(sid, r, J[(sid, r)]) for (i_, r) in sorted(J) if i_ == sid and "jank" in J[(i_, r)])
            jank_html = f"""
<section aria-labelledby="h-jank">
  <h2 id="h-jank">화면 끊김</h2>
  <figure>
    <div class="controls"><span id="seg-j">회차</span><div class="seg" id="sel-jank" role="group" aria-labelledby="seg-j">{btns}</div></div>
    <div id="f-jank" class="chart" style="height:320px"></div>
  </figure>
  <div class="tw" data-name="{sid} 프레임 통계"><table>
    <thead><tr><th>회차</th><th class="num">#</th><th class="num">프레임</th><th class="num">끊긴 프레임</th><th class="num">프레임 시간 중앙/99% ms</th><th class="num">gfxinfo 90/99% ms</th><th class="num">프레임당 읽기 끊김/정상</th><th class="num">읽기 있던 프레임 끊김/정상</th></tr></thead>
    <tbody>{jrows}</tbody></table></div>
</section>"""
        prev_i, next_i = all_ids[ii - 1] if ii else None, all_ids[ii + 1] if ii + 1 < len(all_ids) else None
        tjs = "".join(f"<li>{r['repeat']}회차 <code>{r['traceJobId']}</code></li>" for r in runs)
        body = f"""
<header class="title">
  {crumb((f"type-{t}.html", f"{t} {D['types'][t]}"), (None, sid))}
  <div class="eyebrow">{sid} · P{s0['prio']} · {E(D['types'][t])}</div>
  <h1>{E(nm(s0))}</h1>
  <p class="lede">{E(desc)}</p>
  <p class="byline">측정한 동작: {E(DOING.get(sid, ''))}{(' · ' + E(notes)) if notes else ''}</p>
  {scen_chips(t, sid)}
</header>

<section aria-labelledby="h-runs">
  <h2 id="h-runs">회차별 값</h2>
  <figure><div id="f-runs" class="chart" style="height:220px"></div></figure>
  <div class="tw" data-name="{sid} 회차별 값"><table>
    <thead><tr><th class="num">회차</th><th>캐시</th><th class="num">읽기 MB</th><th class="num">쓰기 MB</th><th class="num">블록 반납 MB</th><th class="num">측정 시간 s</th><th>끝난 뒤 확인</th><th>trace job</th></tr></thead>
    <tbody>{run_rows}</tbody></table></div>
</section>

<section aria-labelledby="h-detail">
  <h2 id="h-detail">측정 구간 상세</h2>
  {"".join(blocks)}
</section>
{jank_html}
<section aria-labelledby="h-steps">
  <h2 id="h-steps">스텝</h2>
  <p class="prose muted">파란 줄이 측정(trace) 구간이에요. 반복(loop) 구간은 펼치지 않고 한 번만 적었어요.</p>
  <ol class="steps">{"".join(li)}</ol>
</section>

<section aria-labelledby="h-raw">
  <h2 id="h-raw">원자료</h2>
  <div class="prose"><ul>
    <li>시나리오 정의: <code>uxtest/scenarios/*/{sid}.scenario.json</code> (생성: <code>scenarios/gen.py</code>)</li>
    <li>실행 결과: <code>uxtest/{E(s0['runFile'])}</code></li>
    <li>저장장치 기록: <code>~/.agent-standalone/archive/jobs/*/trace/&lt;trace job&gt;/result_fsio_ufs.parquet</code><ul>{tjs}</ul></li>
    {f'<li>프레임 기록: <code>uxtest/{E(s0["runFile"][:-5])}/</code></li>' if jk else ''}
  </ul></div>
</section>

<nav class="pnav" aria-label="다른 시나리오">
  <span>{f'<a href="s-{prev_i}.html">← {prev_i}</a>' if prev_i else ''}</span>
  <span><a href="type-{t}.html">{t} 유형 전체</a></span>
  <span>{f'<a href="s-{next_i}.html">{next_i} →</a>' if next_i else ''}</span>
</nav>
<footer>P1·P2 측정 2026-10-25, 대기 측정 2026-10-26 · <a href="index.html">전체 보고서로</a></footer>"""
        init = f"""  UX.runs('f-runs', {json.dumps(runs)}, PROV.runs);
{chr(10).join(init_lines)}
  const selJ = document.getElementById('sel-jank');
  if (selJ) {{
    let jk = {json.dumps(jk[0] if jk else "")};
    const jc = UX.jank('f-jank', () => jk, PROV.jank);
    selJ.addEventListener('click', e => {{
      const bt = e.target.closest('button'); if (!bt) return;
      jk = bt.dataset.v; selJ.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === bt)));
      UX.render(jc);
    }});
  }}"""
        (site / f"s-{sid}.html").write_text(doc(f"{sid} {nm(s0)} · UX I/O", HEAD, body, subset(C, keys, jk), PROV, init))
        n += 1
    return n


def chk(v):
    if not v:
        return ""
    if v.get("captured"):
        return "저장 " + v["captured"].replace("files=", "").replace(" kb=", "개 · ") + "KB"
    return (v.get("focus") or "").split("/")[-1]


def jank_row(sid, rep, j):
    g = j.get("gfx") or {}
    return f"""<tr><td class="id">{sid}<span class="tag">{j['cache']}</span></td><td class="num">{rep}</td>
      <td class="num">{j['total']:,}</td><td class="num">{j['jank']['frames']} <span class="rg">({100 * j['jank']['frames'] / j['total']:.2f}%)</span></td>
      <td class="num">{j['frameDurP50']:.1f} / {j['frameDurP99']:.1f}</td><td class="num">{g.get('p90', '–')} / {g.get('p99', '–')}</td>
      <td class="num">{j['jank']['readsPerFrame']:.2f} / {j['normal']['readsPerFrame']:.2f}</td>
      <td class="num">{j['jank']['withReadPct']:.0f}% / {j['normal']['withReadPct']:.0f}%</td></tr>"""
