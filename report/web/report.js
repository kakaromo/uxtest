// 보고서 공용 스크립트: 차트 그리기 + 차트·표 복사 + 차트 소스 보기.
// 각 페이지는 window.DATA 를 넣고, UX.* 차트 함수를 불러 그린다.
(function () {
  'use strict';
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmtMB = v => v >= 1000 ? (v / 1000).toFixed(2) + ' GB' : v.toFixed(v < 10 ? 1 : 0) + ' MB';
  const ramp = () => ['--r1', '--r2', '--r3', '--r4', '--r5'].map(css);
  const ends = (i, n) => i === 0 ? [4, 0, 0, 4] : i === n - 1 ? [0, 4, 4, 0] : 0;
  function base() {
    const mute = css('--ink-3');
    return {
      ink: css('--ink-2'), mute, font: css('--font'),
      axisLabel: { color: mute, fontFamily: css('--font'), fontSize: 11 },
      split: { lineStyle: { color: css('--surface-3') } },
      tip: {
        backgroundColor: css('--ink'), borderWidth: 0, padding: [8, 12], confine: true,
        extraCssText: 'border-radius:12px;box-shadow:0 4px 12px oklch(0.155 0.060 261 / 0.12)',
        textStyle: { color: css('--bg'), fontSize: 12, fontFamily: css('--font') }
      }
    };
  }

  // ── 알림 ──────────────────────────────────────────────
  let toastEl, toastT;
  function toast(msg) {
    if (!toastEl) { toastEl = document.createElement('div'); toastEl.className = 'toast'; toastEl.setAttribute('role', 'status'); document.body.appendChild(toastEl); }
    toastEl.textContent = msg; toastEl.classList.add('on');
    clearTimeout(toastT); toastT = setTimeout(() => toastEl.classList.remove('on'), 1800);
  }

  // ── 클립보드 / 파일 ───────────────────────────────────
  function legacyCopy(text) {
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;left:-9999px;top:0';
    document.body.appendChild(ta); ta.select();
    let ok = false; try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    ta.remove(); return ok;
  }
  async function copyText(text, html) {
    try {
      if (html && window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
        await navigator.clipboard.write([new ClipboardItem({
          'text/plain': new Blob([text], { type: 'text/plain' }),
          'text/html': new Blob([html], { type: 'text/html' })
        })]);
        return true;
      }
      await navigator.clipboard.writeText(text); return true;
    } catch (e) { return legacyCopy(text); }
  }
  function download(name, blob) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  const cell = v => v == null ? '' : typeof v === 'number' ? String(Math.round(v * 1000) / 1000) : String(v);
  const toTSV = d => [d.cols, ...d.rows].map(r => r.map(c => cell(c).replace(/[\t\n]/g, ' ')).join('\t')).join('\n');
  const toCSV = d => '﻿' + [d.cols, ...d.rows].map(r => r.map(c => { const s = cell(c); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }).join(',')).join('\n');
  const toHTML = d => '<table><thead><tr>' + d.cols.map(c => `<th>${esc(c)}</th>`).join('') + '</tr></thead><tbody>' +
    d.rows.map(r => '<tr>' + r.map(c => `<td>${esc(cell(c))}</td>`).join('') + '</tr>').join('') + '</tbody></table>';
  const slug = s => String(s).replace(/[^\w가-힣.-]+/g, '_').replace(/^_|_$/g, '').slice(0, 60) || 'data';

  // ── 차트 등록 ─────────────────────────────────────────
  // spec: { title, build(b) → ECharts option, data() → {cols, rows}, prov: HTML(출처 설명) }
  const items = [];
  // 차트를 [도구 막대, 차트, 소스 패널] 묶음으로 감싼다 (그리드 안에서도 한 칸을 차지하게)
  function wrap(el, bar, src) {
    const w = document.createElement('div'); w.className = 'cw';
    el.parentNode.insertBefore(w, el);
    w.append(bar, el, src);
  }
  function btn(label, title, fn) {
    const b = document.createElement('button'); b.type = 'button'; b.className = 'tb'; b.textContent = label; b.title = title;
    b.addEventListener('click', fn); return b;
  }
  function chart(el, spec) {
    if (typeof el === 'string') el = document.getElementById(el);
    if (!el) return null;
    const item = { el, spec, chart: null, opt: null, src: null };
    const bar = document.createElement('div'); bar.className = 'cbar';
    bar.innerHTML = `<span class="ct">${esc(spec.title || '')}</span>`;
    const tools = document.createElement('div'); tools.className = 'tools';
    tools.append(
      btn('이미지 복사', '차트를 PNG 이미지로 클립보드에 복사', () => copyImage(item)),
      btn('PNG', '차트를 PNG 파일로 저장', () => savePng(item)),
      btn('데이터 복사', '차트 데이터를 표 형식으로 복사 (엑셀·시트에 붙여넣기)', () => copyData(item)),
      btn('소스', '차트 데이터·출처·설정 보기', () => toggleSrc(item)));
    bar.appendChild(tools);
    const src = document.createElement('div'); src.className = 'src'; src.hidden = true;
    wrap(el, bar, src);
    item.src = src; item.btnSrc = tools.lastChild;
    items.push(item); render(item);
    return item;
  }
  function render(item) {
    if (item.chart) item.chart.dispose();
    item.opt = item.spec.build(base());
    item.chart = echarts.init(item.el, null, { renderer: 'svg' });
    item.chart.setOption(item.opt);
    if (!item.src.hidden) fillSrc(item);
  }
  function pngURL(item) {
    const w = item.el.clientWidth || 800, h = item.el.clientHeight || 400;
    const box = document.createElement('div');
    box.style.cssText = `position:fixed;left:-20000px;top:0;width:${w}px;height:${h}px`;
    document.body.appendChild(box);
    const c = echarts.init(box, null, { renderer: 'canvas', width: w, height: h });
    c.setOption(Object.assign({}, item.opt, { animation: false }));
    const url = c.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: css('--surface') });
    c.dispose(); box.remove(); return url;
  }
  async function copyImage(item) {
    const blob = await (await fetch(pngURL(item))).blob();
    try {
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
      toast('차트 이미지를 복사했어요');
    } catch (e) {
      download(slug(item.spec.title) + '.png', blob);
      toast('이 브라우저에서는 이미지 복사가 막혀 있어 PNG로 저장했어요');
    }
  }
  async function savePng(item) {
    download(slug(item.spec.title) + '.png', await (await fetch(pngURL(item))).blob());
  }
  async function copyData(item) {
    const d = item.spec.data();
    toast(await copyText(toTSV(d), toHTML(d)) ? `데이터 ${d.rows.length}줄을 복사했어요` : '복사하지 못했어요. 소스에서 CSV로 받아 주세요');
  }
  function toggleSrc(item) {
    item.src.hidden = !item.src.hidden;
    item.btnSrc.setAttribute('aria-pressed', String(!item.src.hidden));
    if (!item.src.hidden) fillSrc(item);
  }
  function optJSON(o) {
    return JSON.stringify(o, (k, v) => typeof v === 'function' ? 'ƒ ' + (v.name || '함수') : v, 2);
  }
  function fillSrc(item) {
    const d = item.spec.data(), max = 400;
    const rows = d.rows.slice(0, max);
    item.src.innerHTML =
      `<div class="prov">${item.spec.prov || ''}</div>
       <div class="srcbar"><b>데이터</b><span class="muted">${d.rows.length}줄 × ${d.cols.length}열${d.rows.length > max ? ` · 앞 ${max}줄만 표시 (복사·CSV는 전체)` : ''}</span>
         <span class="sp"></span></div>
       <div class="tw small"><table><thead><tr>${d.cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead>
         <tbody>${rows.map(r => '<tr>' + r.map(c => `<td${typeof c === 'number' ? ' class="num"' : ''}>${esc(cell(c))}</td>`).join('') + '</tr>').join('')}</tbody></table></div>
       <details class="opt"><summary>차트 설정 (ECharts option)</summary><pre></pre></details>`;
    const sb = item.src.querySelector('.sp');
    sb.replaceWith(Object.assign(document.createElement('div'), { className: 'tools' }));
    const tools = item.src.querySelector('.srcbar .tools');
    tools.append(
      btn('CSV 저장', 'UTF-8 CSV 파일로 저장', () => download(slug(item.spec.title) + '.csv', new Blob([toCSV(d)], { type: 'text/csv' }))),
      btn('설정 복사', 'ECharts option JSON 복사', async () => toast(await copyText(optJSON(item.opt)) ? '차트 설정을 복사했어요' : '복사하지 못했어요')));
    item.src.querySelector('pre').textContent = optJSON(item.opt);
  }

  // ── 표 복사 ───────────────────────────────────────────
  function tableData(t) {
    const rows = [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(td => td.innerText.replace(/\s+/g, ' ').trim()));
    return { cols: rows[0] || [], rows: rows.slice(1) };
  }
  function tables() {
    document.querySelectorAll('.tw:not(.small)').forEach(w => {
      if (w.dataset.tools) return; w.dataset.tools = '1';
      const t = w.querySelector('table'); if (!t) return;
      const name = w.dataset.name || '표';
      const bar = document.createElement('div'); bar.className = 'cbar tbar';
      bar.innerHTML = `<span class="ct">${esc(name)}</span>`;
      const tools = document.createElement('div'); tools.className = 'tools';
      tools.append(
        btn('표 복사', '엑셀·시트에 붙여넣을 수 있게 복사', async () => {
          const d = tableData(t);
          toast(await copyText(toTSV(d), t.outerHTML) ? `표 ${d.rows.length}줄을 복사했어요` : '복사하지 못했어요. CSV로 받아 주세요');
        }),
        btn('CSV', 'UTF-8 CSV 파일로 저장', () => download(slug(name) + '.csv', new Blob([toCSV(tableData(t))], { type: 'text/csv' }))));
      bar.appendChild(tools);
      w.parentNode.insertBefore(bar, w);
    });
  }

  // ── 공용 차트 ─────────────────────────────────────────
  const D = () => window.DATA;
  const L = k => D().labels[k];
  const tipAxis = b => ({ ...b.tip, trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: css('--surface-3'), opacity: 0.5 } } });
  const catY = (b, rev) => ({ type: 'category', data: rev.map(L), axisLabel: { ...b.axisLabel, color: b.ink }, axisTick: { show: false }, axisLine: { show: false } });

  // 시나리오별 읽기·쓰기 총량 (중앙값 점 + 최소~최대 선, 로그 축)
  function vol(el, keys, prov) {
    const rev = keys.slice().reverse();
    return chart(el, {
      title: '시나리오별 읽기·쓰기 총량 (MB, 3회 중앙값·최소·최대)', prov,
      data: () => ({ cols: ['시나리오', '이름', '읽기 중앙값 MB', '읽기 최소', '읽기 최대', '쓰기 중앙값 MB', '쓰기 최소', '쓰기 최대'],
        rows: keys.map(k => { const v = D().vol[k]; return [L(k), D().names[k], v.R.med, v.R.min, v.R.max, v.W.med, v.W.min, v.W.max]; }) }),
      build: b => {
        const lg = v => Math.max(v, 0.1);
        const ser = (d, col, off) => [{
          type: 'custom', name: (d === 'R' ? '읽기' : '쓰기') + ' 범위', renderItem: (p, api) => {
            const a = api.coord([lg(api.value(0)), api.value(2)]), z = api.coord([lg(api.value(1)), api.value(2)]);
            return { type: 'line', shape: { x1: a[0], y1: a[1] + off, x2: z[0], y2: z[1] + off }, style: { stroke: col, lineWidth: 2, opacity: 0.45 } };
          }, data: rev.map(k => [lg(D().vol[k][d].min), lg(D().vol[k][d].max), L(k)]), encode: { x: [0, 1], y: 2 }, z: 1, silent: true
        }, {
          type: 'custom', name: d === 'R' ? '읽기' : '쓰기', renderItem: (p, api) => {
            const pt = api.coord([lg(api.value(0)), api.value(1)]);
            return { type: 'circle', shape: { cx: pt[0], cy: pt[1] + off, r: 5 }, style: { fill: col, stroke: css('--surface'), lineWidth: 2 } };
          }, data: rev.map(k => [lg(D().vol[k][d].med), L(k), k]), encode: { x: 0, y: 1, tooltip: [0] }, z: 2
        }];
        return {
          grid: { left: 78, right: 24, top: 8, bottom: 36 },
          tooltip: { ...tipAxis(b), formatter: ps => { const k = rev[ps[0].dataIndex], v = D().vol[k];
            return `<b>${esc(D().names[k])}</b><br>읽기 ${fmtMB(v.R.med)} <span style="opacity:.7">(${fmtMB(v.R.min)}–${fmtMB(v.R.max)})</span><br>쓰기 ${fmtMB(v.W.med)} <span style="opacity:.7">(${fmtMB(v.W.min)}–${fmtMB(v.W.max)})</span>`; } },
          xAxis: { type: 'log', min: 0.1, max: 10000, axisLabel: { ...b.axisLabel, formatter: v => v >= 1000 ? v / 1000 + 'G' : v + 'M' }, splitLine: b.split, axisLine: { show: false } },
          yAxis: catY(b, rev),
          series: [...ser('R', css('--read'), -4), ...ser('W', css('--write'), 4)]
        };
      }
    });
  }

  // 100% 누적 가로 막대 (요청 크기 / 응답 시간: key, d=R|W / 간격: key='gap', d=null)
  function stack(el, keys, key, d, names, title, prov, shift) {
    const rev = keys.slice().reverse();
    const val = k => d ? D()[key][k][d] : D()[key][k];
    return chart(el, {
      title, prov,
      data: () => ({ cols: ['시나리오', ...names.map(n => n + ' %')], rows: keys.map(k => [L(k), ...val(k)]) }),
      build: b => {
        const cols = ramp().slice(shift || 0);
        return {
          grid: { left: 78, right: 12, top: 8, bottom: 28 },
          tooltip: { ...tipAxis(b), formatter: ps => `<b>${esc(D().names[rev[ps[0].dataIndex]])}</b><br>` + ps.map(p => `${p.marker}${p.seriesName} ${p.value.toFixed(1)}%`).join('<br>') },
          legend: { show: false },
          xAxis: { type: 'value', max: 100, axisLabel: { ...b.axisLabel, formatter: '{value}%' }, splitLine: b.split },
          yAxis: catY(b, rev),
          series: names.map((n, i) => ({ type: 'bar', name: n, stack: 's', barWidth: '64%', data: rev.map(k => val(k)[i]),
            itemStyle: { color: cols[i], borderColor: css('--surface'), borderWidth: 1, borderRadius: ends(i, names.length) } }))
        };
      }
    });
  }

  // 한 시나리오의 분포: 읽기·쓰기 두 줄
  function dist(el, k, key, names, title, prov) {
    const rows = [['읽기', D()[key][k].R], ['쓰기', D()[key][k].W]];
    return chart(el, {
      title, prov,
      data: () => ({ cols: ['방향', ...names.map(n => n + ' %')], rows: rows.map(r => [r[0], ...r[1]]) }),
      build: b => {
        const cols = ramp();
        return {
          grid: { left: 44, right: 12, top: 8, bottom: 28 },
          tooltip: { ...tipAxis(b), formatter: ps => `<b>${rows[1 - ps[0].dataIndex][0]}</b><br>` + ps.map(p => `${p.marker}${p.seriesName} ${p.value.toFixed(1)}%`).join('<br>') },
          xAxis: { type: 'value', max: 100, axisLabel: { ...b.axisLabel, formatter: '{value}%' }, splitLine: b.split },
          yAxis: { type: 'category', data: ['쓰기', '읽기'], axisLabel: { ...b.axisLabel, color: b.ink }, axisTick: { show: false }, axisLine: { show: false } },
          series: names.map((n, i) => ({ type: 'bar', name: n, stack: 's', barWidth: '56%', data: [rows[1][1][i], rows[0][1][i]],
            itemStyle: { color: cols[i], borderColor: css('--surface'), borderWidth: 1, borderRadius: ends(i, names.length) } }))
        };
      }
    });
  }

  // 1초 단위 읽기(위)·쓰기(아래) 속도
  function timeline(el, k, title, prov, opts) {
    opts = opts || {};
    const tl = D().timeline[k];
    return chart(el, {
      title, prov,
      data: () => ({ cols: ['초', '읽기 MB/s', '쓰기 MB/s'], rows: tl.readMBs.map((r, i) => [i, r, tl.writeMBs[i]]) }),
      build: b => {
        const R = css('--read'), W = css('--write');
        const m = Math.max(...tl.readMBs, ...tl.writeMBs, 0.1);
        return {
          animation: false,
          grid: opts.axes ? { left: 52, right: 12, top: 12, bottom: 28 } : { left: 2, right: 2, top: 6, bottom: 6 },
          tooltip: { ...b.tip, trigger: 'axis', formatter: ps => `${ps[0].dataIndex}초<br>읽기 ${tl.readMBs[ps[0].dataIndex]} MB/s<br>쓰기 ${tl.writeMBs[ps[0].dataIndex]} MB/s` },
          xAxis: { type: 'category', show: !!opts.axes, data: tl.readMBs.map((_, i) => i), boundaryGap: false,
            axisLabel: { ...b.axisLabel, interval: Math.ceil(tl.readMBs.length / 8), formatter: v => v + 's' }, axisTick: { show: false }, axisLine: { show: false } },
          yAxis: { type: 'value', show: !!opts.axes, min: -m, max: m, axisLabel: { ...b.axisLabel, formatter: v => Math.abs(v).toFixed(0) }, splitLine: b.split, name: opts.axes ? 'MB/s (위 읽기 · 아래 쓰기)' : '', nameTextStyle: { color: b.mute, align: 'left' } },
          series: [
            { type: 'line', name: '읽기', data: tl.readMBs, symbol: 'none', lineStyle: { width: 1.5, color: R }, areaStyle: { color: R, opacity: 0.2 } },
            { type: 'line', name: '쓰기', data: tl.writeMBs.map(v => -v), symbol: 'none', lineStyle: { width: 1.5, color: W }, areaStyle: { color: W, opacity: 0.2 },
              markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: css('--line'), width: 1, type: 'solid' }, data: [{ yAxis: 0 }] } }]
        };
      }
    });
  }

  // 작은 시간축 여러 개 (각 칸은 시나리오 페이지로 연결). 도구는 묶음 전체에 하나.
  function minis(box, keys, link, prov) {
    if (typeof box === 'string') box = document.getElementById(box);
    const cs = [];
    function draw() {
      cs.splice(0).forEach(c => c.dispose()); box.innerHTML = '';
      const R = css('--read'), W = css('--write'), b = base();
      keys.forEach(k => {
        const tl = D().timeline[k];
        const pr = Math.max(...tl.readMBs, 0), pw = Math.max(...tl.writeMBs, 0);
        const d = document.createElement(link ? 'a' : 'div'); d.className = 'mini';
        if (link) d.href = link(k);
        d.innerHTML = `<div class="h"><b>${esc(L(k))}</b><span>${tl.readMBs.length}s · R↑${pr.toFixed(0)} W↓${pw.toFixed(0)} MB/s</span></div><div class="nm">${esc(D().names[k])}</div><div style="height:96px"></div>`;
        box.appendChild(d);
        const c = echarts.init(d.lastChild, null, { renderer: 'svg' }); cs.push(c);
        const m = Math.max(pr, pw, 0.1);
        c.setOption({
          grid: { left: 2, right: 2, top: 4, bottom: 4 }, animation: false,
          tooltip: { ...b.tip, trigger: 'axis', formatter: ps => `${ps[0].dataIndex}s<br>읽기 ${tl.readMBs[ps[0].dataIndex]} MB/s<br>쓰기 ${tl.writeMBs[ps[0].dataIndex]} MB/s` },
          xAxis: { type: 'category', show: false, data: tl.readMBs.map((_, i) => i), boundaryGap: false },
          yAxis: { type: 'value', show: false, min: -m, max: m },
          series: [
            { type: 'line', data: tl.readMBs, symbol: 'none', lineStyle: { width: 1.2, color: R }, areaStyle: { color: R, opacity: 0.25 } },
            { type: 'line', data: tl.writeMBs.map(v => -v), symbol: 'none', lineStyle: { width: 1.2, color: W }, areaStyle: { color: W, opacity: 0.25 } }]
        });
      });
    }
    const pseudo = { el: box, spec: {
      title: '1초 단위 읽기·쓰기 속도 (전체)', prov,
      data: () => ({ cols: ['시나리오', '초', '읽기 MB/s', '쓰기 MB/s'], rows: keys.flatMap(k => D().timeline[k].readMBs.map((r, i) => [L(k), i, r, D().timeline[k].writeMBs[i]])) }) },
      redraw: draw, resize: () => cs.forEach(c => c.resize()) };
    const bar = document.createElement('div'); bar.className = 'cbar';
    bar.innerHTML = `<span class="ct">${esc(pseudo.spec.title)}</span>`;
    const tools = document.createElement('div'); tools.className = 'tools';
    const src = document.createElement('div'); src.className = 'src'; src.hidden = true;
    pseudo.src = src;
    tools.append(
      btn('데이터 복사', '모든 칸의 1초 단위 값을 표로 복사', () => copyData(pseudo)),
      btn('CSV', 'UTF-8 CSV 파일로 저장', () => download('timeline.csv', new Blob([toCSV(pseudo.spec.data())], { type: 'text/csv' }))),
      btn('소스', '데이터 출처 보기', () => { src.hidden = !src.hidden; if (!src.hidden) src.innerHTML = `<div class="prov">${prov || ''}</div><p class="muted">칸을 누르면 그 시나리오 페이지에서 큰 그래프와 원자료를 볼 수 있어요.</p>`; }));
    bar.appendChild(tools);
    wrap(box, bar, src);
    items.push(pseudo); draw();
  }

  // 유형 지도 (순차 비율 × 쓰기 비중)
  function map(el, keys, prov) {
    const pts = () => keys.map(k => { const v = D().vol[k], r = v.R.med, w = v.W.med, s = D().seq[k];
      return { k, x: (r * s.R + w * s.W) / Math.max(r + w, 1e-9), y: 100 * w / Math.max(r + w, 1e-9), t: r + w }; });
    return chart(el, {
      title: '유형 지도 (가로 이어진 요청 %, 세로 쓰기 비중 %, 점 크기 총량)', prov,
      data: () => ({ cols: ['시나리오', '유형', '이어진 요청 %', '쓰기 비중 %', '총량 MB'], rows: pts().map(p => [L(p.k), D().type[p.k], p.x, p.y, p.t]) }),
      build: b => {
        const P = pts(), T = [...new Set(keys.map(k => D().type[k]))];
        return {
          grid: { left: 52, right: 24, top: 16, bottom: 44 },
          tooltip: { ...b.tip, formatter: p => { const q = p.data.raw; return `<b>${esc(D().names[q.k])}</b><br>이어진 요청 ${q.x.toFixed(0)}% · 쓰기 비중 ${q.y.toFixed(0)}%<br>총 ${fmtMB(q.t)}`; } },
          xAxis: { type: 'value', min: 0, max: 100, name: '이어진 요청 %', nameLocation: 'middle', nameGap: 28, nameTextStyle: { color: b.mute }, axisLabel: b.axisLabel, splitLine: b.split },
          yAxis: { type: 'value', min: 0, max: 100, name: '쓰기 비중 %', nameLocation: 'middle', nameGap: 36, nameTextStyle: { color: b.mute }, axisLabel: b.axisLabel, splitLine: b.split },
          series: T.map(t => ({ type: 'scatter', name: t, data: P.filter(p => D().type[p.k] === t).map(p => ({ value: [p.x, p.y], raw: p, symbolSize: 8 + 4 * Math.sqrt(p.t / 100) })),
            itemStyle: { color: css('--brand'), borderColor: css('--surface'), borderWidth: 2, opacity: 0.75 },
            label: { show: true, position: 'right', formatter: p => L(p.data.raw.k), color: b.ink, fontSize: 11, fontFamily: b.font },
            labelLayout: { hideOverlap: false, moveOverlap: 'shiftY' } }))
        };
      }
    });
  }

  // 저장장치 위치(LBA) × 시간 접근 지도. getK() 로 현재 시나리오를 고른다.
  function lba(el, getK, d, prov) {
    const cells = () => D().lba[getK()].filter(x => x[2] === d).map(x => [x[0], x[1], x[3]]);
    return chart(el, {
      title: `저장장치 위치 접근 지도 · ${d === 'R' ? '읽기' : '쓰기'}`, prov,
      data: () => { const k = getK(), dur = D().dur[k], G = D().lbaMaxGB;
        return { cols: ['시나리오', '시작 초', '끝 초', 'LBA 시작 GB', 'LBA 끝 GB', 'MB'],
          rows: cells().map(c => [L(k), c[0] * dur / 60, (c[0] + 1) * dur / 60, c[1] * G / 48, (c[1] + 1) * G / 48, c[2]]) }; },
      build: b => {
        const k = getK(), P = cells(), G = D().lbaMaxGB, dur = D().dur[k];
        const mx = Math.max(...P.map(p => p[2]), 0.001), col = d === 'R' ? css('--read') : css('--write');
        return {
          grid: { left: 44, right: 8, top: 8, bottom: 26 },
          tooltip: { ...b.tip, formatter: p => `${(p.data[0] * dur / 60).toFixed(0)}–${((p.data[0] + 1) * dur / 60).toFixed(0)}s · LBA ${(p.data[1] * G / 48).toFixed(0)}–${((p.data[1] + 1) * G / 48).toFixed(0)}GB<br>${p.data[2].toFixed(2)} MB` },
          xAxis: { type: 'category', data: [...Array(60).keys()], axisLabel: { ...b.axisLabel, interval: 14, formatter: v => (v * dur / 60).toFixed(0) + 's' }, axisTick: { show: false }, axisLine: { show: false } },
          yAxis: { type: 'category', data: [...Array(48).keys()], axisLabel: { ...b.axisLabel, interval: 11, formatter: v => (v * G / 48).toFixed(0) + 'G' }, axisTick: { show: false }, axisLine: { show: false } },
          visualMap: { show: false, min: 0, max: Math.sqrt(mx), dimension: 3, inRange: { color: [css('--heat-0'), col] } },
          series: [{ type: 'heatmap', data: P.map(p => [p[0], p[1], p[2], Math.sqrt(p[2])]), itemStyle: { borderColor: css('--surface'), borderWidth: 0.5 } }]
        };
      }
    });
  }

  // 갤러리 읽기와 끊긴 프레임 (1초 단위). getK() → DATA.jank 키
  function jank(el, getK, prov) {
    return chart(el, {
      title: '갤러리 읽기(위)와 끊긴 프레임(아래), 1초 단위', prov,
      data: () => ({ cols: ['초', '끊긴 프레임 수', '갤러리 읽기 MB'], rows: (D().jank[getK()] || { sec: [] }).sec.map(x => [x[0], x[1], x[2]]) }),
      build: b => {
        const s = (D().jank[getK()] || { sec: [] }).sec, xs = s.map(x => x[0]);
        return {
          axisPointer: { link: [{ xAxisIndex: 'all' }] },
          tooltip: { ...b.tip, trigger: 'axis', formatter: ps => `${ps[0].axisValue}s<br>읽기 ${s[ps[0].dataIndex][2]} MB · 끊긴 프레임 ${s[ps[0].dataIndex][1]}` },
          grid: [{ left: 52, right: 12, top: 22, height: '48%' }, { left: 52, right: 12, top: '68%', bottom: 30 }],
          xAxis: [{ type: 'category', data: xs, gridIndex: 0, axisLabel: { show: false }, axisTick: { show: false }, axisLine: { show: false } },
            { type: 'category', data: xs, gridIndex: 1, axisLabel: { ...b.axisLabel, interval: Math.ceil(xs.length / 8), formatter: v => v + 's' }, axisTick: { show: false }, axisLine: { show: false } }],
          yAxis: [{ type: 'value', gridIndex: 0, name: '갤러리 읽기 MB/s', nameTextStyle: { color: b.mute, align: 'left' }, axisLabel: b.axisLabel, splitLine: b.split },
            { type: 'value', gridIndex: 1, name: '끊긴 프레임/s', nameTextStyle: { color: b.mute, align: 'left' }, axisLabel: b.axisLabel, splitLine: b.split, minInterval: 1 }],
          series: [{ type: 'bar', name: '읽기', data: s.map(x => x[2]), xAxisIndex: 0, yAxisIndex: 0, itemStyle: { color: css('--read'), borderRadius: [3, 3, 0, 0] }, barCategoryGap: '10%' },
            { type: 'bar', name: '끊긴 프레임', data: s.map(x => x[1]), xAxisIndex: 1, yAxisIndex: 1, itemStyle: { color: css('--write'), borderRadius: [3, 3, 0, 0] }, barCategoryGap: '10%' }]
        };
      }
    });
  }

  // 회차별 읽기·쓰기 막대 (시나리오 페이지)
  function runs(el, rows, prov) {
    return chart(el, {
      title: '회차별 읽기·쓰기 (MB)', prov,
      data: () => ({ cols: ['회차', '읽기 MB', '쓰기 MB', '블록 반납 MB', '측정 시간 s', 'trace job'], rows: rows.map(r => [r.repeat, r.readMB, r.writeMB, r.discardMB, r.durSec, r.traceJobId]) }),
      build: b => ({
        grid: { left: 52, right: 12, top: 28, bottom: 28 },
        legend: { top: 0, right: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: b.ink, fontFamily: b.font, fontSize: 12 } },
        tooltip: { ...tipAxis(b), formatter: ps => `${ps[0].axisValue}<br>` + ps.map(p => `${p.marker}${p.seriesName} ${fmtMB(p.value)}`).join('<br>') },
        xAxis: { type: 'category', data: rows.map(r => r.repeat + '회차'), axisLabel: { ...b.axisLabel, color: b.ink }, axisTick: { show: false }, axisLine: { show: false } },
        yAxis: { type: 'value', axisLabel: b.axisLabel, splitLine: b.split },
        series: [{ type: 'bar', name: '읽기', data: rows.map(r => r.readMB), itemStyle: { color: css('--read'), borderRadius: [4, 4, 0, 0] }, barMaxWidth: 36 },
          { type: 'bar', name: '쓰기', data: rows.map(r => r.writeMB), itemStyle: { color: css('--write'), borderRadius: [4, 4, 0, 0] }, barMaxWidth: 36 }]
      })
    });
  }

  function redrawAll() { items.forEach(it => it.redraw ? it.redraw() : render(it)); }
  function resizeAll() { items.forEach(it => it.resize ? it.resize() : it.chart && it.chart.resize()); }

  window.UX = { chart, render, vol, stack, dist, timeline, minis, map, lba, jank, runs, tables, toast, fmtMB, css, ramp };

  document.addEventListener('DOMContentLoaded', () => {
    tables();
    document.querySelectorAll('details').forEach(d => d.addEventListener('toggle', () => { if (d.open) resizeAll(); }));
    let t; window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(resizeAll, 120); });
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redrawAll);
    new MutationObserver(redrawAll).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  });
})();
