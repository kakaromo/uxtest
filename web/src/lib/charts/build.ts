// 차트 option 만들기. 규칙: option 안 함수는 인자만 쓰는 순수 함수 (HTML 소스 복사 때 그대로 옮겨짐).
// 색·이름·툴팁 문자열은 미리 계산해 데이터 항목에 넣는다.
import type { ChartSpec } from '#lib/components/Chart.svelte';
import type { Row, Run, Jank, Points } from '#lib/types.js';
import { ends, type Theme } from './theme.js';
import { mb } from '#lib/fmt.js';

/** 보기 좋은 올림 (1·2·2.5·5 × 10^n) */
export const nice = (v: number) => {
	if (!(v > 0)) return 1;
	const e = Math.pow(10, Math.floor(Math.log10(v)));
	return ([1, 2, 2.5, 5, 10].find((k) => k * e >= v) ?? 10) * e;
};
const pctFmt = (v: number) => (v == null ? '' : v.toFixed(1) + '%');
const msFmt = (v: number) => (v == null ? '' : v.toFixed(2) + ' ms');
const catAxis = (t: Theme, data: string[]) => ({
	type: 'category',
	data,
	axisLabel: { ...t.axisLabel, color: t.ink },
	axisTick: { show: false },
	axisLine: { show: false }
});

export const PROV_TRACE =
	'Run별 UFS 기록 <code>~/.agent-standalone/archive/jobs/*/trace/&lt;trace job&gt;/result_fsio_ufs.parquet</code> → <code>report/extract.py</code>·<code>export_web.py</code>. 방향은 SCSI 명령(READ 0x28/0x88, WRITE 0x2A/0x8A)으로 판정해요.';

/** 시나리오별 Read·Write Volume: median 점 + 최소~최대 선, 로그 축 */
export function volSpec(rows: Row[], label: (r: Row) => string): ChartSpec {
	const rev = rows.slice().reverse();
	const lg = (v: number) => Math.max(v, 0.1);
	return {
		title: '시나리오별 Read·Write Volume (MB, median과 최소~최대)',
		prov: PROV_TRACE + ' Run마다 trace window 안 요청 바이트를 더하고, Run들의 median·최소·최대를 그렸어요.',
		data: () => ({
			cols: ['시나리오', '이름', 'Read median MB', 'Read 최소', 'Read 최대', 'Write median MB', 'Write 최소', 'Write 최대'],
			rows: rows.map((r) => [label(r), r.name, r.readMB.med, r.readMB.min, r.readMB.max, r.writeMB.med, r.writeMB.min, r.writeMB.max])
		}),
		option: (t) => {
			const range = (d: 'readMB' | 'writeMB', off: number) =>
				rev.map((r, i) => [lg(r[d].min), lg(r[d].max), i, off]);
			const pts = (d: 'readMB' | 'writeMB') =>
				rev.map((r, i) => ({
					value: [lg(r[d].med), i],
					tip: `<b>${label(r)} ${r.name}</b><br>${d === 'readMB' ? 'Read' : 'Write'} ${mb(r[d].med)} (${mb(r[d].min)}~${mb(r[d].max)})`
				}));
			const renderRange = (_p: any, api: any) => {
				const a = api.coord([api.value(0), api.value(2)]);
				const z = api.coord([api.value(1), api.value(2)]);
				const o = api.value(3);
				return { type: 'line', shape: { x1: a[0], y1: a[1] + o, x2: z[0], y2: z[1] + o }, style: { stroke: api.visual('color'), lineWidth: 2, opacity: 0.45 } };
			};
			return {
				grid: { left: 64, right: 24, top: 28, bottom: 32 },
				legend: { ...t.legend, top: 0, left: 0, data: ['Read', 'Write'] },
				tooltip: { ...t.tip, trigger: 'item', formatter: (p: any) => (p.data && p.data.tip) || '' },
				xAxis: {
					type: 'log',
					min: 0.1,
					max: 10000,
					axisLabel: { ...t.axisLabel, formatter: (v: number) => (v >= 1000 ? v / 1000 + 'G' : v + 'M') },
					splitLine: t.split,
					axisLine: { show: false }
				},
				yAxis: catAxis(t, rev.map(label)),
				series: [
					{ type: 'custom', name: 'Read', renderItem: renderRange, data: range('readMB', -4), itemStyle: { color: t.read }, silent: true, z: 1 },
					{ type: 'custom', name: 'Write', renderItem: renderRange, data: range('writeMB', 4), itemStyle: { color: t.write }, silent: true, z: 1 },
					{ type: 'scatter', name: 'Read', data: pts('readMB'), symbolSize: 10, symbolOffset: [0, -4], itemStyle: { color: t.read, borderColor: t.surface, borderWidth: 2 }, z: 2 },
					{ type: 'scatter', name: 'Write', data: pts('writeMB'), symbolSize: 10, symbolOffset: [0, 4], itemStyle: { color: t.write, borderColor: t.surface, borderWidth: 2 }, z: 2 }
				]
			};
		}
	};
}

/** 100% 누적 가로 막대: cats 줄마다 names 구간 비율 */
export function stackSpec(title: string, cats: string[], names: string[], vals: number[][], prov: string, shift = 0): ChartSpec {
	const rc = cats.slice().reverse();
	const rv = vals.slice().reverse();
	return {
		title,
		prov,
		data: () => ({ cols: ['항목', ...names.map((n) => n + ' %')], rows: cats.map((c, i) => [c, ...vals[i]]) }),
		option: (t) => ({
			grid: { left: 72, right: 12, top: 30, bottom: 24 },
			legend: { ...t.legend, top: 0, left: 0 },
			tooltip: { ...t.tip, trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: pctFmt },
			xAxis: { type: 'value', max: 100, axisLabel: { ...t.axisLabel, formatter: '{value}%' }, splitLine: t.split },
			yAxis: catAxis(t, rc),
			series: names.map((n, i) => ({
				type: 'bar',
				name: n,
				stack: 's',
				barWidth: '62%',
				data: rv.map((v) => v[i]),
				itemStyle: { color: t.ramp.slice(shift)[i] ?? t.ramp[4], borderColor: t.surface, borderWidth: 1, borderRadius: ends(i, names.length) }
			}))
		})
	};
}

/** Timeline 탐색기: 위 R/W 속도(Write는 아래로), 가운데 QD(QD), 아래 Latency p99. Step 구간은 띠로. */
export function explorerSpec(run: Run, res: '1s' | '100ms', title: string): ChartSpec {
	const fine = res === '100ms' && run.tl100;
	const dt = fine ? 0.1 : 1;
	const r = fine ? run.tl100!.r.map((v) => v * 10) : run.tl1.r;
	const w = fine ? run.tl100!.w.map((v) => v * 10) : run.tl1.w;
	const xs = r.map((_, i) => +(i * dt).toFixed(1));
	const steps = run.steps.filter((s) => s.e > 0 && s.s < run.durSec && s.type !== 'trace_start' && s.type !== 'trace_stop');
	return {
		title,
		prov: PROV_TRACE + ` ${fine ? '100ms' : '1초'} 칸마다 요청 바이트를 더해 MB/s 로 바꿨어요. QD은 요청을 보낼 때의 queue depth, Latency은 응답까지 걸린 시간(dtoc)의 칸별 99번째 값이에요. 띠는 시나리오 Step 구간이에요.`,
		data: () => ({
			cols: ['초', 'Read MB/s', 'Write MB/s', ...(fine ? [] : ['QD max', 'QD avg', 'Read Latency p99 ms', 'Write Latency p99 ms', 'discard 건수', 'flush 건수'])],
			rows: xs.map((x, i) =>
				fine ? [x, r[i], w[i]] : [x, r[i], w[i], run.tl1.qdMax[i], run.tl1.qdAvg[i], run.tl1.p99R[i], run.tl1.p99W[i], run.tl1.disc[i], run.tl1.flush[i]]
			)
		}),
		option: (t) => {
			const m = nice(Math.max(...r, ...w, 0.1));
			const bands = steps.map((s, i) => [
				{ xAxis: Math.max(0, s.s), name: s.label, itemStyle: { color: i % 2 ? 'rgba(49,130,246,0.06)' : 'rgba(49,130,246,0.11)' } },
				{ xAxis: Math.min(run.durSec, s.e) }
			]);
			const x = (gi: number, show: boolean) => ({
				type: 'value',
				gridIndex: gi,
				min: 0,
				max: +(xs.length * dt).toFixed(1),
				axisLabel: { ...t.axisLabel, show, formatter: '{value}s' },
				axisTick: { show: false },
				axisLine: { show: false },
				splitLine: { show: false }
			});
			const y = (gi: number, name: string, extra = {}) => ({
				type: 'value',
				gridIndex: gi,
				name,
				nameTextStyle: { color: t.mute, align: 'left', fontSize: 11 },
				axisLabel: t.axisLabel,
				splitLine: t.split,
				...extra
			});
			const pair = (a: number[]) => a.map((v, i) => [xs[i], v]);
			return {
				animation: false,
				axisPointer: { link: [{ xAxisIndex: 'all' }] },
				tooltip: { ...t.tip, trigger: 'axis', valueFormatter: (v: number) => (v == null ? '' : (Math.round(v * 100) / 100).toString()) },
				legend: { ...t.legend, top: 0, left: 0 },
				grid: fine
					? [{ left: 56, right: 16, top: 56, bottom: 64 }]
					: [
							{ left: 56, right: 16, top: 56, height: '38%' },
							{ left: 56, right: 16, top: '60%', height: '12%' },
							{ left: 56, right: 16, top: '77%', height: '12%' }
						],
				dataZoom: [
					{ type: 'inside', xAxisIndex: fine ? [0] : [0, 1, 2], filterMode: 'none' },
					{ type: 'slider', xAxisIndex: fine ? [0] : [0, 1, 2], height: 18, bottom: 6, filterMode: 'none', borderColor: 'transparent', fillerColor: 'rgba(49,130,246,0.15)', handleStyle: { color: t.primary }, textStyle: { color: t.mute, fontSize: 10 }, labelFormatter: (v: number) => Math.round(v) + 's' }
				],
				xAxis: fine ? [x(0, true)] : [x(0, false), x(1, false), x(2, true)],
				yAxis: fine
					? [y(0, '', { min: -m, max: m, axisLabel: { ...t.axisLabel, formatter: (v: number) => Math.abs(v).toFixed(0) } })]
					: [
							y(0, '', { min: -m, max: m, axisLabel: { ...t.axisLabel, formatter: (v: number) => Math.abs(v).toFixed(0) } }),
							y(1, 'QD', { minInterval: 1, splitNumber: 2 }),
							y(2, 'Latency p99 ms', { splitNumber: 2 })
						],
				series: [
					{ type: 'line', name: 'Read', data: pair(r), symbol: 'none', step: 'end', lineStyle: { width: 1.2, color: t.read }, itemStyle: { color: t.read }, areaStyle: { color: t.read, opacity: 0.25 }, markArea: { silent: true, label: { show: false }, data: bands } },
					{ type: 'line', name: 'Write', data: pair(w.map((v) => -v)), symbol: 'none', step: 'end', lineStyle: { width: 1.2, color: t.write }, itemStyle: { color: t.write }, areaStyle: { color: t.write, opacity: 0.25 } },
					...(fine
						? []
						: [
								{ type: 'line', name: 'QD max', xAxisIndex: 1, yAxisIndex: 1, data: pair(run.tl1.qdMax), symbol: 'none', step: 'end', lineStyle: { width: 1.2, color: t.ramp[3] }, itemStyle: { color: t.ramp[3] } },
								{ type: 'line', name: 'Read Latency p99', xAxisIndex: 2, yAxisIndex: 2, data: pair(run.tl1.p99R), symbol: 'none', lineStyle: { width: 1.2, color: t.read }, itemStyle: { color: t.read } },
								{ type: 'line', name: 'Write Latency p99', xAxisIndex: 2, yAxisIndex: 2, data: pair(run.tl1.p99W), symbol: 'none', lineStyle: { width: 1.2, color: t.write, type: 'dashed' }, itemStyle: { color: t.write } }
							])
				]
			};
		}
	};
}

/** Run 겹침: 1초 단위 Read(위)·Write(아래), Run마다 선 하나 */
export function overlaySpec(runs: Run[]): ChartSpec {
	return {
		title: 'Run별 1초 단위 Read(위)·Write(아래) 겹쳐 보기',
		prov: PROV_TRACE + ' Run마다 자기 trace 첫 요청을 0초로 맞췄어요.',
		data: () => {
			const n = Math.max(...runs.map((r) => r.tl1.r.length));
			return {
				cols: ['초', ...runs.flatMap((r) => [`Run ${r.repeat} Read MB/s`, `Run ${r.repeat} Write MB/s`])],
				rows: [...Array(n).keys()].map((i) => [i, ...runs.flatMap((r) => [r.tl1.r[i] ?? null, r.tl1.w[i] ?? null])])
			};
		},
		option: (t) => {
			const shade = [t.ramp[1], t.ramp[3], t.ramp[4]];
			const m = nice(Math.max(...runs.flatMap((r) => [...r.tl1.r, ...r.tl1.w]), 0.1));
			return {
				animation: false,
				legend: { ...t.legend, top: 0, left: 0 },
				tooltip: { ...t.tip, trigger: 'axis', valueFormatter: (v: number) => (v == null ? '' : Math.abs(v).toFixed(2) + ' MB/s') },
				grid: { left: 56, right: 16, top: 56, bottom: 30 },
				xAxis: { type: 'value', min: 0, axisLabel: { ...t.axisLabel, formatter: '{value}s' }, splitLine: { show: false } },
				yAxis: { type: 'value', min: -m, max: m, axisLabel: { ...t.axisLabel, formatter: (v: number) => Math.abs(v).toFixed(0) }, splitLine: t.split, name: 'MB/s (위 Read · 아래 Write)', nameTextStyle: { color: t.mute, align: 'left' } },
				series: runs.flatMap((r, i) => [
					{ type: 'line', name: `Run ${r.repeat}`, data: r.tl1.r.map((v, s) => [s, v]), symbol: 'none', lineStyle: { width: 1.4, color: shade[i % 3] }, itemStyle: { color: shade[i % 3] } },
					{ type: 'line', name: `Run ${r.repeat}`, data: r.tl1.w.map((v, s) => [s, -v]), symbol: 'none', lineStyle: { width: 1.4, color: shade[i % 3], type: 'dashed' }, itemStyle: { color: shade[i % 3] } }
				])
			};
		}
	};
}

/** 구간(크기·QD)별 Latency p50/p99, Read·Write */
export function latSpec(title: string, buckets: string[], lat: Run['latSize'], prov: string): ChartSpec {
	const g = (d: 'R' | 'W', k: number) => buckets.map((_, i) => (lat[d][i] ? lat[d][i]![k] : null));
	return {
		title,
		prov,
		data: () => ({
			cols: ['구간', 'Read p50 ms', 'Read p90 ms', 'Read p99 ms', 'Read 건수', 'Write p50 ms', 'Write p90 ms', 'Write p99 ms', 'Write 건수'],
			rows: buckets.map((b, i) => [b, ...(lat.R[i] ?? [null, null, null, 0]), ...(lat.W[i] ?? [null, null, null, 0])])
		}),
		option: (t) => ({
			legend: { ...t.legend, top: 0, left: 0 },
			tooltip: { ...t.tip, trigger: 'axis', valueFormatter: msFmt },
			grid: { left: 52, right: 16, top: 34, bottom: 30 },
			xAxis: { ...catAxis(t, buckets) },
			yAxis: { type: 'value', name: 'ms', nameTextStyle: { color: t.mute }, axisLabel: t.axisLabel, splitLine: t.split },
			series: [
				{ type: 'bar', name: 'Read p50', data: g('R', 0), itemStyle: { color: t.ramp[1], borderRadius: [4, 4, 0, 0] }, barMaxWidth: 18 },
				{ type: 'bar', name: 'Write p50', data: g('W', 0), itemStyle: { color: t.ink, borderRadius: [4, 4, 0, 0] }, barMaxWidth: 18 },
				{ type: 'line', name: 'Read p99', data: g('R', 2), symbolSize: 8, lineStyle: { width: 2, color: t.read }, itemStyle: { color: t.read, borderColor: t.surface, borderWidth: 2 } },
				{ type: 'line', name: 'Write p99', data: g('W', 2), symbolSize: 8, lineStyle: { width: 2, color: t.write, type: 'dashed' }, itemStyle: { color: t.write, borderColor: t.surface, borderWidth: 2 } }
			]
		})
	};
}

/** LBA × 시간 */
export function lbaSpec(run: Run, d: 'R' | 'W', lbaMaxGB: number): ChartSpec {
	const cells = run.lba.filter((c) => c[2] === d).map((c) => [c[0], c[1], c[3]]);
	const dur = run.durSec;
	return {
		title: `LBA heatmap · ${d === 'R' ? 'Read' : 'Write'}`,
		prov: PROV_TRACE + ` LUN 0 의 LBA(4KB 단위)를 48칸(칸당 ${(lbaMaxGB / 48).toFixed(1)}GB), Duration을 60칸으로 나눠 칸마다 MB 를 더했어요. 색은 제곱근 눈금이에요.`,
		data: () => ({
			cols: ['시작 초', '끝 초', 'LBA 시작 GB', 'LBA 끝 GB', 'MB'],
			rows: cells.map((c) => [(c[0] * dur) / 60, ((c[0] + 1) * dur) / 60, (c[1] * lbaMaxGB) / 48, ((c[1] + 1) * lbaMaxGB) / 48, c[2]])
		}),
		option: (t) => {
			const mx = Math.max(...cells.map((c) => c[2]), 0.001);
			const step = dur / 60;
			const g = lbaMaxGB / 48;
			return {
				grid: { left: 44, right: 8, top: 8, bottom: 26 },
				tooltip: { ...t.tip, formatter: (p: any) => p.data[4] },
				xAxis: { type: 'category', data: [...Array(60).keys()].map((i) => Math.round(i * step) + 's'), axisLabel: { ...t.axisLabel, interval: 14 }, axisTick: { show: false }, axisLine: { show: false } },
				yAxis: { type: 'category', data: [...Array(48).keys()].map((i) => Math.round(i * g) + 'G'), axisLabel: { ...t.axisLabel, interval: 11 }, axisTick: { show: false }, axisLine: { show: false } },
				visualMap: { show: false, min: 0, max: Math.sqrt(mx), dimension: 3, inRange: { color: [t.heat0, d === 'R' ? t.read : t.write] } },
				series: [
					{
						type: 'heatmap',
						data: cells.map((c) => [c[0], c[1], c[2], Math.sqrt(c[2]), `${Math.round(c[0] * step)}~${Math.round((c[0] + 1) * step)}s · LBA ${Math.round(c[1] * g)}~${Math.round((c[1] + 1) * g)}GB<br>${c[2].toFixed(2)} MB`]),
						itemStyle: { borderColor: t.surface, borderWidth: 0.5 }
					}
				]
			};
		}
	};
}

/** 범주별 Read·Write 막대 (가로) */
export function rwBarSpec(title: string, cats: string[], r: number[], w: number[], prov: string, unit = 'MB'): ChartSpec {
	const rc = cats.slice().reverse();
	return {
		title,
		prov,
		data: () => ({ cols: ['항목', `Read ${unit}`, `Write ${unit}`], rows: cats.map((c, i) => [c, r[i], w[i]]) }),
		option: (t) => ({
			legend: { ...t.legend, top: 0, left: 0 },
			tooltip: { ...t.tip, trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v: number) => (v == null ? '' : v.toFixed(1)) },
			grid: { left: 110, right: 16, top: 30, bottom: 24 },
			xAxis: { type: 'value', axisLabel: t.axisLabel, splitLine: t.split },
			yAxis: catAxis(t, rc),
			series: [
				{ type: 'bar', name: 'Read', data: r.slice().reverse(), itemStyle: { color: t.read, borderRadius: [0, 4, 4, 0] }, barMaxWidth: 14 },
				{ type: 'bar', name: 'Write', data: w.slice().reverse(), itemStyle: { color: t.write, borderRadius: [0, 4, 4, 0] }, barMaxWidth: 14 }
			]
		})
	};
}

/** Run별 Read·Write 막대 (세로) */
export function runsSpec(runs: { repeat: number; readMB: number; writeMB: number; discardMB: number; durSec: number; traceJobId: string }[]): ChartSpec {
	return {
		title: 'Run별 Read·Write (MB)',
		prov: PROV_TRACE,
		data: () => ({
			cols: ['Run', 'Read MB', 'Write MB', 'Discard MB', 'Duration s', 'trace job'],
			rows: runs.map((r) => [r.repeat, r.readMB, r.writeMB, r.discardMB, r.durSec, r.traceJobId])
		}),
		option: (t) => ({
			legend: { ...t.legend, top: 0, right: 0 },
			tooltip: { ...t.tip, trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v: number) => (v == null ? '' : v.toFixed(1) + ' MB') },
			grid: { left: 52, right: 12, top: 30, bottom: 26 },
			xAxis: catAxis(t, runs.map((r) => r.repeat + 'Run')),
			yAxis: { type: 'value', axisLabel: t.axisLabel, splitLine: t.split },
			series: [
				{ type: 'bar', name: 'Read', data: runs.map((r) => r.readMB), itemStyle: { color: t.read, borderRadius: [4, 4, 0, 0] }, barMaxWidth: 36 },
				{ type: 'bar', name: 'Write', data: runs.map((r) => r.writeMB), itemStyle: { color: t.write, borderRadius: [4, 4, 0, 0] }, barMaxWidth: 36 }
			]
		})
	};
}

/** 유형 지도: 가로 Sequential 비율, 세로 Write ratio, 점 크기 Volume */
export function mapSpec(rows: Row[], label: (r: Row) => string, title = 'Workload map'): ChartSpec {
	const pts = rows.map((r) => {
		const R = r.readMB.med,
			W = r.writeMB.med,
			T = Math.max(R + W, 1e-9);
		return { r, x: (R * r.seq.R.med + W * r.seq.W.med) / T, y: (100 * W) / T, t: R + W };
	});
	return {
		title: `${title} (가로 Sequential %, 세로 Write ratio %, 점 크기 Volume)`,
		prov: PROV_TRACE + ' Sequential = 같은 LUN·방향의 직전 요청 끝 LBA 에서 바로 Sequential의 바이트 비율이에요.',
		data: () => ({ cols: ['시나리오', '유형', 'Sequential %', 'Write ratio %', 'Volume MB'], rows: pts.map((p) => [label(p.r), p.r.type, p.x, p.y, p.t]) }),
		option: (t) => ({
			grid: { left: 52, right: 28, top: 16, bottom: 44 },
			tooltip: { ...t.tip, formatter: (p: any) => p.data.tip },
			xAxis: { type: 'value', min: 0, max: 100, name: 'Sequential %', nameLocation: 'middle', nameGap: 28, nameTextStyle: { color: t.mute }, axisLabel: t.axisLabel, splitLine: t.split },
			yAxis: { type: 'value', min: 0, max: 100, name: 'Write ratio %', nameLocation: 'middle', nameGap: 36, nameTextStyle: { color: t.mute }, axisLabel: t.axisLabel, splitLine: t.split },
			series: [
				{
					type: 'scatter',
					data: pts.map((p) => ({
						value: [p.x, p.y],
						name: label(p.r),
						symbolSize: Math.min(8 + 4 * Math.sqrt(p.t / 100), 44),
						tip: `<b>${label(p.r)} ${p.r.name}</b><br>Sequential ${p.x.toFixed(0)}% · Write ratio ${p.y.toFixed(0)}%<br>총 ${mb(p.t)}`
					})),
					itemStyle: { color: t.primary, borderColor: t.surface, borderWidth: 2, opacity: 0.75 },
					label: { show: true, position: 'right', formatter: '{b}', color: t.ink, fontSize: 11, fontFamily: t.font },
					labelLayout: { hideOverlap: false, moveOverlap: 'shiftY' }
				}
			]
		})
	};
}

/** 갤러리 Read(위)·Jank frame(아래), 1초 단위 */
export function jankSpec(j: Jank): ChartSpec {
	const s = j.sec ?? [];
	return {
		title: `갤러리 Read와 Jank frame · Run ${j.repeat} (${j.cache})`,
		prov: 'Perfetto FrameTimeline(앱이 늦어 Jank frame)과 같은 시각의 fsio 갤러리 Read. 시계는 trace 시작 때 잰 boot clock 차이로 맞췄어요.',
		data: () => ({ cols: ['초', 'Jank frame 수', '갤러리 Read MB'], rows: s.map((x) => [x[0], x[1], x[2]]) }),
		option: (t) => ({
			axisPointer: { link: [{ xAxisIndex: 'all' }] },
			tooltip: { ...t.tip, trigger: 'axis' },
			grid: [
				{ left: 52, right: 12, top: 24, height: '46%' },
				{ left: 52, right: 12, top: '68%', bottom: 30 }
			],
			xAxis: [
				{ type: 'category', data: s.map((x) => x[0]), gridIndex: 0, axisLabel: { show: false }, axisTick: { show: false }, axisLine: { show: false } },
				{ type: 'category', data: s.map((x) => x[0]), gridIndex: 1, axisLabel: { ...t.axisLabel, formatter: '{value}s' }, axisTick: { show: false }, axisLine: { show: false } }
			],
			yAxis: [
				{ type: 'value', gridIndex: 0, name: '갤러리 Read MB/s', nameTextStyle: { color: t.mute, align: 'left' }, axisLabel: t.axisLabel, splitLine: t.split },
				{ type: 'value', gridIndex: 1, name: 'Jank frame/s', nameTextStyle: { color: t.mute, align: 'left' }, axisLabel: t.axisLabel, splitLine: t.split, minInterval: 1 }
			],
			series: [
				{ type: 'bar', name: 'Read', data: s.map((x) => x[2]), itemStyle: { color: t.read, borderRadius: [3, 3, 0, 0] } },
				{ type: 'bar', name: 'Jank frame', data: s.map((x) => x[1]), xAxisIndex: 1, yAxisIndex: 1, itemStyle: { color: t.write, borderRadius: [3, 3, 0, 0] } }
			]
		})
	};
}

/** 작은 Timeline (유형 페이지 묶음용, 도구 없음) */
export function miniOption(t: Theme, r: number[], w: number[]) {
	const m = Math.max(...r, ...w, 0.1);
	return {
		animation: false,
		grid: { left: 2, right: 2, top: 4, bottom: 4 },
		tooltip: { ...t.tip, trigger: 'axis', valueFormatter: (v: number) => (v == null ? '' : Math.abs(v).toFixed(1) + ' MB/s') },
		xAxis: { type: 'category', show: false, data: r.map((_, i) => i + 's'), boundaryGap: false },
		yAxis: { type: 'value', show: false, min: -m, max: m },
		series: [
			{ type: 'line', name: 'Read', data: r, symbol: 'none', lineStyle: { width: 1.2, color: t.read }, itemStyle: { color: t.read }, areaStyle: { color: t.read, opacity: 0.25 } },
			{ type: 'line', name: 'Write', data: w.map((v) => -v), symbol: 'none', lineStyle: { width: 1.2, color: t.write }, itemStyle: { color: t.write }, areaStyle: { color: t.write, opacity: 0.25 } }
		]
	};
}

/** agent Trace 의 LBA 패턴처럼: 요청 하나 = 점. 위 LBA, 가운데 QD, 아래 Latency(로그), 같은 시간축 */
export const PT_DIRS = [
	{ k: 'R', name: 'Read', color: '' },
	{ k: 'W', name: 'Write', color: '#f97316' },
	{ k: 'D', name: 'Discard', color: '#a855f7' },
	{ k: 'F', name: 'Flush', color: '#22c55e' }
] as const;

export function ptRows(p: Points) {
	// [초, LBA GB, LBA, KB, QD, Latency ms, LUN]
	const by: Record<string, number[][]> = { R: [], W: [], D: [], F: [] };
	let ms = 0;
	for (let i = 0; i < p.n; i++) {
		ms += p.t[i];
		by[p.d[i]]?.push([ms / 1000, +((p.lba[i] * 4096) / 2 ** 30).toFixed(4), p.lba[i], p.kb[i], p.qd[i], p.lat[i] / 1000, p.lun?.[i] ?? 0]);
	}
	return by;
}

export function lbaPatternSpec(p: Points, run: Run, title: string): ChartSpec {
	const by = ptRows(p);
	const dirs = PT_DIRS.filter((d) => by[d.k].length);
	const steps = run.steps.filter((s) => s.e > 0 && s.s < run.durSec && s.type !== 'trace_start' && s.type !== 'trace_stop');
	return {
		title,
		prov:
			PROV_TRACE +
			` 요청 하나가 점 하나예요 (이 Run ${p.n.toLocaleString()}건 전부, 샘플링 없음). 가로는 요청을 보낸 시각(완료 시각 − dtoc), 세로는 LUN 안 LBA를 GB로 바꾼 값이에요. QD는 완료 시점 queue depth, Latency는 dtoc예요. 띠는 시나리오 Step 구간이에요.`,
		data: () => ({
			cols: ['초', '방향', 'LBA GB', 'LBA (4KB)', 'KB', 'QD', 'Latency ms', 'LUN'],
			rows: dirs.flatMap((d) => by[d.k].map((r) => [r[0], d.name, r[1], r[2], r[3], r[4], r[5], r[6]])).sort((a, b) => (a[0] as number) - (b[0] as number))
		}),
		option: (t) => {
			const col = (c: string) => c || t.read;
			const bands = steps.map((s, i) => [
				{ xAxis: Math.max(0, s.s), name: s.label, itemStyle: { color: i % 2 ? 'rgba(49,130,246,0.05)' : 'rgba(49,130,246,0.1)' } },
				{ xAxis: Math.min(run.durSec, s.e) }
			]);
			const x = (gi: number, show: boolean) => ({
				type: 'value',
				gridIndex: gi,
				min: 0,
				max: Math.ceil(run.durSec),
				axisLabel: { ...t.axisLabel, show, formatter: '{value}s' },
				axisTick: { show: false },
				axisLine: { show: false },
				splitLine: { show: false }
			});
			const y = (gi: number, name: string, extra = {}) => ({
				type: 'value',
				gridIndex: gi,
				name,
				nameLocation: 'middle',
				nameRotate: 90,
				nameGap: 42,
				nameTextStyle: { color: t.mute, fontSize: 11 },
				axisLabel: t.axisLabel,
				splitLine: t.split,
				...extra
			});
			const sc = (di: number, color: string, name: string, gi: number, yDim: number) => ({
				type: 'scatter',
				name,
				datasetIndex: di,
				xAxisIndex: gi,
				yAxisIndex: gi,
				encode: { x: 0, y: yDim },
				symbolSize: gi === 0 ? 3 : 2.5,
				large: true,
				largeThreshold: 4000,
				itemStyle: { color, opacity: 0.75 },
				emphasis: { disabled: true }
			});
			return {
				animation: false,
				dataset: dirs.map((d) => ({ source: by[d.k] })),
				axisPointer: { link: [{ xAxisIndex: 'all' }] },
				tooltip: {
					...t.tip,
					trigger: 'item',
					formatter: (q: any) => {
						const v = q.value;
						if (!Array.isArray(v)) return q.seriesName || '';
						return q.seriesName + ' · ' + v[0].toFixed(3) + 's<br>LBA ' + v[2].toLocaleString() + ' (' + v[1].toFixed(2) + ' GB)' + (v[6] ? ' · LUN ' + v[6] : '') + '<br>' + v[3] + ' KB · QD ' + v[4] + ' · ' + v[5].toFixed(3) + ' ms';
					}
				},
				legend: { ...t.legend, top: 0, left: 0, icon: 'circle', data: dirs.map((d) => d.name) },
				grid: [
					{ left: 64, right: 56, top: 36, height: '52%' },
					{ left: 64, right: 56, top: '64%', height: '11%' },
					{ left: 64, right: 56, top: '79%', height: '11%' }
				],
				dataZoom: [
					{ type: 'inside', xAxisIndex: [0, 1, 2], filterMode: 'none' },
					{ type: 'slider', xAxisIndex: [0, 1, 2], height: 16, bottom: 4, filterMode: 'none', borderColor: 'transparent', fillerColor: 'rgba(49,130,246,0.15)', handleStyle: { color: t.primary }, textStyle: { color: t.mute, fontSize: 10 }, labelFormatter: (v: number) => Math.round(v) + 's' },
					{ type: 'slider', yAxisIndex: [0], width: 14, right: 8, top: 36, bottom: '48%', filterMode: 'none', borderColor: 'transparent', fillerColor: 'rgba(49,130,246,0.15)', handleStyle: { color: t.primary }, textStyle: { color: t.mute, fontSize: 10 }, labelFormatter: (v: number) => v.toFixed(1) + 'G' }
				],
				xAxis: [x(0, false), x(1, false), x(2, true)],
				yAxis: [
					y(0, 'LBA GB', { min: 0, scale: false }),
					y(1, 'QD', { minInterval: 1, splitNumber: 2 }),
					y(2, 'Latency ms', { type: 'log', splitNumber: 2, axisLabel: { ...t.axisLabel, formatter: (v: number) => (v >= 1 ? v.toFixed(0) : v.toString()) } })
				],
				series: [
					{ type: 'line', name: '__steps__', data: [], silent: true, tooltip: { show: false }, markArea: { silent: true, label: { show: false }, data: bands } },
					...dirs.flatMap((d, di) => [sc(di, col(d.color), d.name, 0, 1), sc(di, col(d.color), d.name, 1, 4), sc(di, col(d.color), d.name, 2, 5)])
				]
			};
		}
	};
}
