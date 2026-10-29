// 차트를 "그 차트만으로 동작하는 HTML 조각"으로 만든다.
// option 안의 함수(formatter 등)는 바깥 변수를 쓰지 않는 순수 함수만 쓰는 게 규칙이라, 소스 그대로 옮겨도 동작한다.
export function optionJS(o: unknown, indent = 1) {
	const fns: string[] = [];
	const json = JSON.stringify(
		o,
		(_k, v) => {
			if (typeof v === 'function') return `__UXFN${fns.push(v.toString()) - 1}__`;
			if (typeof v === 'number' && !Number.isInteger(v)) return Math.round(v * 1e4) / 1e4;
			return v;
		},
		indent
	);
	return json.replace(/"__UXFN(\d+)__"/g, (_m, i) => fns[+i]);
}

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

export function chartHTML(o: unknown, opt: { title: string; height: number; bg: string; fg: string; caption?: string; renderer?: 'svg' | 'canvas' }) {
	const id = 'ux-' + Math.random().toString(36).slice(2, 8);
	return `<!-- ${opt.title} · UX I/O 분석 사이트에서 복사 -->
<figure style="margin:0;font-family:'Pretendard Variable',Pretendard,-apple-system,sans-serif;background:${opt.bg};color:${opt.fg};padding:16px;border-radius:16px">
  <figcaption style="font-weight:600;font-size:14px;margin-bottom:8px">${esc(opt.title)}</figcaption>
  <div id="${id}" style="width:100%;height:${opt.height}px"></div>${opt.caption ? `\n  <p style="font-size:12px;opacity:.7;margin:8px 0 0">${esc(opt.caption)}</p>` : ''}
</figure>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<script>
(function () {
  var el = document.getElementById('${id}');
  var chart = echarts.init(el, null, { renderer: '${opt.renderer ?? 'svg'}' });
  chart.setOption(${optionJS(o, 2)});
  window.addEventListener('resize', function () { chart.resize(); });
})();
</script>
`;
}

/** 차트 여러 개를 HTML 조각 하나로 (Confluence HTML macro 하나에 붙이기). 좁으면 세로로 쌓인다 */
export function chartsHTML(list: { o: unknown; title: string; height: number }[], opt: { title: string; bg: string; fg: string; caption?: string; renderer?: 'svg' | 'canvas' }) {
	const id = 'ux-' + Math.random().toString(36).slice(2, 8);
	const boxes = list
		.map(
			(c, i) => `    <div style="flex:1 1 360px;min-width:0">
      <div style="font-weight:600;font-size:13px;margin-bottom:4px">${esc(c.title)}</div>
      <div id="${id}-${i}" style="width:100%;height:${c.height}px"></div>
    </div>`
		)
		.join('\n');
	return `<!-- ${opt.title} · UX I/O 분석 사이트에서 복사 -->
<figure style="margin:0;font-family:'Pretendard Variable',Pretendard,-apple-system,sans-serif;background:${opt.bg};color:${opt.fg};padding:16px;border-radius:16px">
  <figcaption style="font-weight:600;font-size:15px;margin-bottom:12px">${esc(opt.title)}</figcaption>
  <div style="display:flex;flex-wrap:wrap;gap:16px">
${boxes}
  </div>${opt.caption ? `\n  <p style="font-size:12px;opacity:.7;margin:8px 0 0">${esc(opt.caption)}</p>` : ''}
</figure>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<script>
(function () {
  var opts = [
${list.map((c) => '    ' + optionJS(c.o, 4).trimStart()).join(',\n')}
  ];
  var charts = opts.map(function (o, i) {
    var c = echarts.init(document.getElementById('${id}-' + i), null, { renderer: '${opt.renderer ?? 'svg'}' });
    c.setOption(o);
    return c;
  });
  window.addEventListener('resize', function () { charts.forEach(function (c) { c.resize(); }); });
})();
</script>
`;
}
