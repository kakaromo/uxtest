<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import type { ECharts } from 'echarts';
	import * as ToggleGroup from '#lib/components/ui/toggle-group/index.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import Chart from '#lib/components/Chart.svelte';
	import CopyTable from '#lib/components/CopyTable.svelte';
	import { app, TYPE_ORDER } from '#lib/state.svelte.js';
	import { load } from '#lib/data.js';
	import { lbaPatternSpec, explorerSpec, overlaySpec, runsSpec, latSpec, lbaSpec, stackSpec, rwBarSpec, jankSpec, PROV_TRACE } from '#lib/charts/build.js';
	import { rows, rowsOf, nameOf, label } from '#lib/view.js';
	import { findings, rank } from '#lib/insight.js';
	import RankStrip from '#lib/components/RankStrip.svelte';
	import { mb, f, n0, x, sec } from '#lib/fmt.js';
	import type { ScenarioDoc, Run, Points } from '#lib/types.js';
	import { ChevronLeft, ChevronRight, CodeXml } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { theme } from '#lib/charts/theme.js';
	import { chartsHTML } from '#lib/charts/source.js';
	import { copy } from '#lib/clipboard.js';
	import { toast } from 'svelte-sonner';

	const id = $derived(page.params.id!);
	let doc = $state<ScenarioDoc | null>(null);
	let err = $state('');
	let repSel = $state('');
	let res = $state<'1s' | '100ms'>('1s');
	let groupSel = $state('');

	$effect(() => {
		const want = id;
		doc = null;
		err = '';
		load<ScenarioDoc>(`s-${want}`)
			.then((d) => {
				if (want !== id) return;
				doc = d;
				groupSel = d.rows[d.rows.length > 1 ? 1 : 0].key;
				const rep = d.rows[d.rows.length > 1 ? 1 : 0].rep.repeat;
				repSel = String(d.runs.find((r) => r.repeat === rep)?.repeat ?? d.runs[0]?.repeat ?? '');
				res = '1s';
			})
			.catch(() => (err = '이 시나리오 데이터를 불러오지 못했어요.'));
	});

	const row = $derived(doc?.rows.find((r) => r.key === groupSel) ?? doc?.rows[0]);
	const run = $derived<Run | undefined>(doc?.runs.find((r) => String(r.repeat) === repSel));
	const B = $derived(app.index!.meta.buckets);
	const QB = $derived(app.index!.meta.qdBuckets);
	const typeIds = $derived(app.man?.types[doc?.rows[0].type ?? ''] ?? []);
	const idx = $derived(typeIds.indexOf(id));
	const desc = $derived((row?.description ?? '').replace(/^\[[^\]]*\]\s*/, ''));
	const peers = $derived(doc ? rowsOf(doc.rows[0].type) : []);
	const all = $derived(rows());
	const repRun = $derived(doc?.runs.find((r) => r.repeat === row?.rep.repeat) ?? doc?.runs[0]);
	const facts = $derived(row ? findings(row, repRun, all) : []);
	const pos = $derived(
		row
			? [
					{ k: 'Write', get: (r: typeof row) => r.writeMB.med, log: true, fmt: mb },
					{ k: 'Read', get: (r: typeof row) => r.readMB.med, log: true, fmt: mb },
					{ k: 'Peak throughput', get: (r: typeof row) => r.peakMBs.med, log: true, fmt: (z: number) => `${f(z, 0)} MB/s` },
					{ k: 'Write Latency p99', get: (r: typeof row) => r.dtocP99.W.med, log: false, fmt: (z: number) => `${f(z, 2)} ms` },
					{ k: 'Idle', get: (r: typeof row) => r.idlePct.med, log: false, fmt: (z: number) => `${f(z, 0)}%` }
				].map((m) => ({ ...m, v: m.get(row), vals: all.map(m.get), r: rank(all, m.get, row) }))
			: []
	);
	const jank = $derived(doc?.jank.find((j) => String(j.repeat) === repSel && j.sec?.length));

	// Timeline 탐색기에서 고른 구간의 통계
	let zoom = $state<[number, number] | null>(null);
	const sel = $derived.by(() => {
		if (!run) return null;
		const n = run.tl1.r.length;
		const [a, b] = zoom ?? [0, n];
		const s = Math.max(0, Math.floor(a)),
			e = Math.min(n, Math.ceil(b));
		const sl = (k: keyof Run['tl1']) => run.tl1[k].slice(s, e);
		const sum = (v: number[]) => v.reduce((p, c) => p + c, 0);
		return {
			s,
			e,
			read: sum(sl('r')),
			write: sum(sl('w')),
			peak: Math.max(0, ...sl('r').map((v, i) => v + sl('w')[i])),
			qd: Math.max(0, ...sl('qdMax')),
			p99: Math.max(0, ...sl('p99R'), ...sl('p99W')),
			disc: sum(sl('disc')),
			flush: sum(sl('flush'))
		};
	});
	function hookZoom(c: ECharts) {
		c.on('datazoom', () => {
			const o: any = c.getOption();
			const z = o.dataZoom?.[0];
			const n = run?.tl1.r.length ?? 0;
			if (z) zoom = z.start === 0 && z.end === 100 ? null : [(z.start / 100) * n, (z.end / 100) * n];
		});
	}
	$effect(() => {
		void repSel;
		void res;
		zoom = null;
	});
	// LBA pattern: 고른 Run 의 요청 하나하나 (따로 받는 파일)
	let pts = $state<Points | null>(null);
	let ptsErr = $state(false);
	$effect(() => {
		const key = `p-${id}-${repSel}`;
		pts = null;
		ptsErr = false;
		if (!repSel) return;
		load<Points>(key)
			.then((p) => {
				if (key === `p-${id}-${repSel}`) pts = p;
			})
			.catch(() => (ptsErr = true));
	});
	const ptSpec = $derived(pts && run ? lbaPatternSpec(pts, run, `${row ? nameOf(row) : id} · Run ${run.repeat} LBA pattern (요청 ${pts.n.toLocaleString()}건)`) : null);
	const exSpec = $derived(run ? explorerSpec(run, res, `${row ? nameOf(row) : id} · Run ${run.repeat} Timeline (${res === '1s' ? '1초' : '100ms'} 단위 MB/s, 위 Read · 아래 Write)`) : null);
	const sizeSpec = $derived(run ? stackSpec('Request size 분포 (건수 %)', ['Read', 'Write'], B.size, [run.size.R, run.size.W], PROV_TRACE) : null);
	const dtocSpec = $derived(run ? stackSpec('Latency 분포 (건수 %)', ['Read', 'Write'], B.dtoc, [run.dtoc.R, run.dtoc.W], PROV_TRACE) : null);
	// Request size·Latency 분포 두 차트를 HTML 조각 하나로 (Confluence HTML macro 하나에 붙이기)
	async function copyDist() {
		if (!run || !sizeSpec || !dtocSpec) return;
		const th = theme();
		const html = chartsHTML(
			[sizeSpec, dtocSpec].map((c) => ({ o: c.option(th), title: c.title, height: 170 })),
			{ title: `${row ? nameOf(row) : id} · Run ${run.repeat}`, bg: th.surface, fg: th.fg }
		);
		(await copy(html)) ? toast.success('Request size·Latency 분포 차트 2개를 HTML 하나로 복사했어요. Confluence HTML macro에 붙이면 돼요') : toast.error('복사하지 못했어요');
	}
</script>

<svelte:head><title>UX I/O 분석 · {id} {app.names[id] ?? ''}</title></svelte:head>

<nav class="mb-4 flex flex-wrap items-center gap-1 text-body-3 text-ink-3">
	<a href={resolve('/')} class="hover:text-foreground">홈</a> ›
	{#if doc}<a href={resolve('/type/[t]', { t: doc.rows[0].type })} class="hover:text-foreground">{doc.rows[0].type} {doc.rows[0].typeName}</a> ›{/if}
	<span>{id}</span>
</nav>

{#if err}
	<p class="text-destructive">{err}</p>
{:else if !doc || !row}
	<Skeleton class="h-10 w-2/3" />
	<Skeleton class="mt-4 h-40 w-full" />
	<Skeleton class="mt-4 h-80 w-full" />
{:else}
	<header class="mb-8">
		<p class="text-label-s font-semibold text-primary">{id} · P{row.prio} · {row.typeName}</p>
		<h1 class="mt-2 text-h1 font-bold">{nameOf(row)}</h1>
		<p class="mt-3 max-w-[760px] text-body-2 text-muted-foreground">{desc}</p>
		<div class="mt-3 flex flex-wrap gap-2">
			<Badge variant="secondary">{row.repeats} runs</Badge>
			<Badge variant="secondary">trace window {sec(row.durSec.med)}</Badge>
			{#if row.cache}<Badge variant="secondary">{row.cache === 'cold' ? '캐시 없음(cold)' : '캐시 있음(warm)'}</Badge>{/if}
			{#if !row.success}<Badge variant="destructive">중간에 끊김 · 남은 구간만</Badge>{/if}
		</div>
		{#if doc.rows.length > 1}
			<div class="mt-4 flex items-center gap-3">
				<span class="text-label-s font-semibold text-muted-foreground">조건</span>
				<ToggleGroup.Root type="single" bind:value={groupSel} variant="outline" size="sm">
					{#each doc.rows as r (r.key)}
						<ToggleGroup.Item value={r.key}>{r.cache === 'cold' ? 'Run 1 (cold)' : 'Run 2·3 (warm)'}</ToggleGroup.Item>
					{/each}
				</ToggleGroup.Root>
			</div>
		{/if}
	</header>

	<section class="mb-12">
		<h2 id="summary" class="mb-4 text-h2 font-bold">Summary</h2>
		<ol class="grid gap-3 sm:grid-cols-2">
			{#each facts as fc, i (i)}
				<li class="flex items-start gap-4 rounded-2xl bg-card px-5 py-4 ring-1 {fc.tone === 'warn' ? 'ring-warning/60' : 'ring-border'}">
					<b class="min-w-[92px] text-h3 leading-tight font-bold tabular-nums {fc.tone === 'warn' ? 'text-foreground' : 'text-primary'}">{fc.stat}</b>
					<span class="pt-1 text-body-2">{#if fc.tone === 'warn'}<Badge variant="outline" class="mr-1 border-warning">주의</Badge>{/if}{fc.text}</span>
				</li>
			{/each}
		</ol>
		<div class="mt-4 rounded-2xl bg-card px-5 py-4 ring-1 ring-border">
			<h3 id="position" class="text-title-1 font-semibold" data-toc="전체 중 위치">전체 {all.length}개 중 위치</h3>
			<p class="text-body-3 text-ink-3">회색 점이 다른 시나리오, 파란 점이 {label(row)}예요. 오른쪽일수록 커요{pos.some((m) => m.log) ? ' (MB·MB/s는 로그 눈금)' : ''}.</p>
			<div class="mt-3 space-y-3">
				{#each pos as m (m.k)}
					<div class="grid grid-cols-[120px_1fr_110px] items-center gap-4 max-sm:grid-cols-[90px_1fr_90px]">
						<span class="text-body-3 font-semibold text-muted-foreground">{m.k}</span>
						<div><RankStrip vals={m.vals} v={m.v} log={m.log} fmt={m.fmt} /></div>
						<span class="text-right tabular-nums"><b class="text-body-2">{m.fmt(m.v)}</b><br /><span class="text-caption text-ink-3">{m.r.k}위 / {m.r.n}</span></span>
					</div>
				{/each}
			</div>
		</div>
	</section>

	<section class="mb-12">
		<h2 id="numbers" class="mb-4 text-h2 font-bold">Key metrics</h2>
		<dl class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
			{#each [['Read', mb(row.readMB.med), `${f(row.readMB.min, 0)}~${f(row.readMB.max, 0)} MB`], ['Write', mb(row.writeMB.med), `${f(row.writeMB.min, 0)}~${f(row.writeMB.max, 0)} MB`], ['Discard', mb(row.discardMB.med), ''], ['Peak throughput', `${f(row.peakMBs.med, 0)} MB/s`, '1초 칸 기준'], ['Idle', `${f(row.idlePct.med, 0)}%`, '요청 없는 100ms 칸'], ['QD p99', f(row.qdP99.med, 0), 'queue depth'], ['Latency p99 Read·Write', `${f(row.dtocP99.R.med, 2)} · ${f(row.dtocP99.W.med, 2)} ms`, ''], ['Sequential R·W', `${f(row.seq.R.med, 0)} · ${f(row.seq.W.med, 0)}%`, 'sequential ratio'], ['Metadata', `${f(row.metaPct.med, 0)}%`, 'Write 바이트 중'], ['Requests R·W', `${n0(row.readN.med)} · ${n0(row.writeN.med)}`, ''], ...(row.wakesPerMin ? [['Wakeups', `${f(row.wakesPerMin.med, 0)}번/분`, `Max gap ${f(row.maxGapSec?.med, 1)}초`], ['Flush', `${f(row.flushPerSec?.med, 1)}번/초`, '']] : []), ...(row.h8PerMin ? [['Hibern8', `${f(row.h8PerMin.med, 0)}번/분`, `시간의 ${f(row.h8Pct?.med, 0)}% · exit ${f(row.h8ExitMs?.med, 2)} ms`], ['Query (mgmt)', `${f(row.queryPerMin?.med, 0)}번/분`, (row.wbCheckPerMin?.med ?? 0) > 0 ? `WB 조회 ${f(row.wbCheckPerMin?.med, 0)}번/분` : 'bBackgroundOpStatus 위주']] : []), ['CV', f(row.cv, 2), row.cv > 0.5 ? '변동 큼 (CV>0.5)' : 'CV']] as k (k[0])}
				<div class="rounded-xl bg-card px-4 py-3 ring-1 ring-border">
					<dt class="text-body-3 text-muted-foreground">{k[0]}</dt>
					<dd class="mt-1 text-h4 font-bold tabular-nums">{k[1]}</dd>
					{#if k[2]}<dd class="text-caption text-ink-3">{k[2]}</dd>{/if}
				</div>
			{/each}
		</dl>
	</section>

	{#if run}
		<section class="mb-12 space-y-4">
			<h2 id="explorer" class="text-h2 font-bold">Timeline explorer</h2>
			<p class="text-body-2 text-muted-foreground">아래 막대를 끌거나 차트 위에서 스크롤해서 구간을 확대해요. 옅은 파란 띠는 시나리오 Step 구간이에요. 고른 구간의 합계가 바로 아래에 나와요.</p>
			<div class="flex flex-wrap items-center gap-4">
				<div class="flex items-center gap-2">
					<span class="text-label-s font-semibold text-muted-foreground">Run</span>
					<ToggleGroup.Root type="single" bind:value={repSel} variant="outline" size="sm">
						{#each doc.runs as r (r.repeat)}<ToggleGroup.Item value={String(r.repeat)}>Run {r.repeat}{r.cache ? ` ${r.cache}` : ''}</ToggleGroup.Item>{/each}
					</ToggleGroup.Root>
				</div>
				<div class="flex items-center gap-2">
					<span class="text-label-s font-semibold text-muted-foreground">단위</span>
					<ToggleGroup.Root type="single" bind:value={res} variant="outline" size="sm">
						<ToggleGroup.Item value="1s">1초</ToggleGroup.Item>
						<ToggleGroup.Item value="100ms" disabled={!run.tl100}>100ms</ToggleGroup.Item>
					</ToggleGroup.Root>
				</div>
			</div>
			{#if exSpec}<Chart spec={exSpec} height={res === '1s' ? 460 : 340} oninit={hookZoom} />{/if}
			{#if sel}
				<dl class="grid grid-cols-2 gap-2 rounded-xl bg-accent px-4 py-3 text-body-3 sm:grid-cols-4 lg:grid-cols-8">
					<div class="col-span-2 sm:col-span-4 lg:col-span-1"><dt class="text-muted-foreground">고른 구간</dt><dd class="font-bold tabular-nums">{sel.s}~{sel.e}초</dd></div>
					<div><dt class="text-muted-foreground">Read</dt><dd class="font-bold tabular-nums">{mb(sel.read)}</dd></div>
					<div><dt class="text-muted-foreground">Write</dt><dd class="font-bold tabular-nums">{mb(sel.write)}</dd></div>
					<div><dt class="text-muted-foreground">Peak MB/s</dt><dd class="font-bold tabular-nums">{f(sel.peak, 0)}</dd></div>
					<div><dt class="text-muted-foreground">QD max</dt><dd class="font-bold tabular-nums">{sel.qd}</dd></div>
					<div><dt class="text-muted-foreground">Latency p99 max</dt><dd class="font-bold tabular-nums">{f(sel.p99, 2)} ms</dd></div>
					<div><dt class="text-muted-foreground">discard</dt><dd class="font-bold tabular-nums">{n0(sel.disc)}건</dd></div>
					<div><dt class="text-muted-foreground">flush</dt><dd class="font-bold tabular-nums">{n0(sel.flush)}건</dd></div>
				</dl>
			{/if}
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="steps" class="text-h2 font-bold">Per-step I/O</h2>
			<p class="text-body-2 text-muted-foreground">trace window 안 Step마다 쓴 양이에요 (Run {run.repeat}). Step 시각은 agent 가 기록한 boot clock 이라 UFS 기록과 같은 시계예요.</p>
			<CopyTable title="{id} Run {run.repeat} Step별 I/O">
				<table>
					<thead><tr><th class="num">#</th><th>Step</th><th>Kind</th><th class="num">Start s</th><th class="num">End s</th><th class="num">Read MB</th><th class="num">Write MB</th><th class="num">Requests</th><th class="num">Latency p99 ms</th></tr></thead>
					<tbody>
						{#each run.steps as s, i (i)}
							<tr>
								<td class="num">{s.i}</td><td>{s.label}</td><td class="text-ink-3">{s.type}</td>
								<td class="num" data-v={s.s}>{f(s.s, 1)}</td><td class="num" data-v={s.e}>{f(s.e, 1)}</td>
								<td class="num" data-v={s.readMB}>{f(s.readMB)}</td><td class="num" data-v={s.writeMB}>{f(s.writeMB)}</td>
								<td class="num" data-v={s.n}>{n0(s.n)}</td><td class="num" data-v={s.p99}>{f(s.p99, 2)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</CopyTable>
			<details class="rounded-xl border bg-card px-4 py-3">
				<summary class="cursor-pointer text-label-s font-semibold">시나리오 전체 Step ({doc.steps.length}개)</summary>
				<ol class="mt-2 list-decimal space-y-0.5 pl-6 text-body-3">
					{#each doc.steps as s, i (i)}<li><span class="text-ink-3">{s.type}</span> {s.label}</li>{/each}
				</ol>
			</details>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="runs" class="text-h2 font-bold">Run comparison</h2>
			<div class="grid gap-3 lg:grid-cols-2">
				<Chart spec={runsSpec(doc.runs)} height={260} />
				<Chart spec={overlaySpec(doc.runs)} height={260} />
			</div>
			<CopyTable title="{id} Run별 지표" note="CV = Run Volume의 표준편차 ÷ 평균.">
				<table>
					<thead><tr><th class="num">Run</th><th>Cache</th><th class="num">Duration s</th><th class="num">Read MB</th><th class="num">Write MB</th><th class="num">discard MB</th><th class="num">Peak MB/s</th><th class="num">Latency p99 R/W</th><th class="num">QD p99</th><th class="num">Idle %</th><th>trace job</th></tr></thead>
					<tbody>
						{#each doc.runs as r (r.repeat)}
							<tr>
								<td class="num">{r.repeat}</td><td>{r.cache ?? ''}</td>
								<td class="num" data-v={r.durSec}>{f(r.durSec, 0)}</td>
								<td class="num" data-v={r.readMB}>{f(r.readMB)}</td><td class="num" data-v={r.writeMB}>{f(r.writeMB)}</td><td class="num" data-v={r.discardMB}>{f(r.discardMB)}</td>
								<td class="num" data-v={r.peakMBs}>{f(r.peakMBs, 0)}</td><td class="num">{f(r.dtocP99.R, 2)} / {f(r.dtocP99.W, 2)}</td>
								<td class="num" data-v={r.qdP99}>{r.qdP99}</td><td class="num" data-v={r.idlePct}>{f(r.idlePct, 0)}</td>
								<td class="font-mono text-[11px] text-ink-3">{r.traceJobId}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</CopyTable>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="shape" class="text-h2 font-bold">Request pattern · Latency</h2>
			<p class="text-body-2 text-muted-foreground">Run {run.repeat} 기준이에요. 위의 Run 선택을 바꾸면 같이 바뀌어요.</p>
			<div class="grid gap-3 lg:grid-cols-2">
				{#if sizeSpec && dtocSpec}
					<div class="flex flex-wrap items-center gap-1 text-body-3 text-ink-3 lg:col-span-2">
						<span class="mr-1">HTML 복사 (아래 두 차트를 하나로):</span>
						<Button variant="secondary" size="xs" onclick={copyDist}><CodeXml />Request size + Latency</Button>
					</div>
					<Chart spec={sizeSpec} height={170} />
					<Chart spec={dtocSpec} height={170} />
				{/if}
				<Chart spec={latSpec('Request size별 Latency (p50 막대, p99 선)', B.size, run.latSize, PROV_TRACE + ' 완료 응답(complete_rsp)의 dtoc 를 Request size 구간마다 백분위로.')} height={280} />
				<Chart spec={latSpec('QD별 Latency (p50 막대, p99 선)', QB, run.latQd, PROV_TRACE + ' 완료 시점의 queue depth 구간마다 dtoc 백분위.')} height={280} />
				<Chart spec={stackSpec('DtoD · dispatch-to-dispatch (건수 %)', ['전체'], B.gap, [run.gap], PROV_TRACE + ' 앞 request를 보낸 시각부터 다음 request를 보낸 시각까지예요. DtoC(Latency)와는 달라요. 16ms·200ms 넘는 간격은 UFS가 절전·유휴 정리에 들어갈 수 있는 틈이에요.', 1)} height={130} />
				{#if run.ctod}<Chart spec={stackSpec('CtoD · complete-to-dispatch (건수 %)', ['전체'], B.ctod ?? ['0 (overlap)', '<1ms', '1–16ms', '16–200ms', '≥200ms'], [run.ctod], PROV_TRACE + ' 직전 request가 완료된 시각부터 이번 request를 보낼 때까지예요(parquet ctod). 0은 앞 request가 아직 처리 중일 때 보낸 것이에요. 길수록 UFS가 실제로 쉰 틈이에요.', 1)} height={130} />{/if}
				<CopyTable title="Top streams (Bytes %)">
					<table>
						<thead><tr><th>Direction</th><th>Size</th><th>Sequential/Random</th><th class="num">Bytes %</th></tr></thead>
						<tbody>{#each run.streams as s, i (i)}<tr><td>{s.dir === 'R' ? 'Read' : 'Write'}</td><td>{s.size}</td><td>{s.seq === 'SEQ' ? 'Sequential' : 'Random'}</td><td class="num" data-v={s.pct}>{f(s.pct)}</td></tr>{/each}</tbody>
					</table>
				</CopyTable>
			</div>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="lba-pattern" class="text-h2 font-bold">LBA pattern</h2>
			<p class="text-body-2 text-muted-foreground">요청 하나가 점 하나예요 (Run {run.repeat}, 위의 Run 선택을 따라가요). 위는 LBA, 가운데는 QD와 Latency, 맨 아래는 UFS mgmt command(Hibern8 구간, Query)이에요. 차트 위에서 스크롤하거나 아래 막대를 끌면 시간을, 오른쪽 막대를 끌면 LBA 범위를 확대해요. 범례를 누르면 Read·Write 등을 끄고 켤 수 있어요.</p>
			{#if ptSpec}
				<Chart spec={ptSpec} height={pts?.mg ? 660 : 560} renderer="canvas" />
			{:else if ptsErr}
				<p class="text-body-3 text-destructive">이 Run의 요청 데이터를 불러오지 못했어요.</p>
			{:else}
				<Skeleton class="h-[560px] w-full rounded-xl" />
			{/if}
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="lba" class="text-h2 font-bold">LBA heatmap</h2>
			<div class="grid gap-3 lg:grid-cols-2">
				<Chart spec={lbaSpec(run, 'R', app.index!.meta.lbaMaxGB)} height={320} />
				<Chart spec={lbaSpec(run, 'W', app.index!.meta.lbaMaxGB)} height={320} />
			</div>
		</section>

		{#if run.h8PerMin !== undefined}
			<section class="mb-12 space-y-4">
				<h2 id="mgmt" class="text-h2 font-bold">UFS mgmt command</h2>
				<p class="text-body-2 text-muted-foreground">Run {run.repeat} 동안 UFS 링크가 Hibern8에 드나든 횟수와 Query request예요. 다른 지표(Volume·Idle·QD)는 이 command를 빼고 셌어요. 시나리오 median은 Hibern8 {f(row?.h8PerMin?.med, 0)}번/분, Hibern8 시간 {f(row?.h8Pct?.med, 0)}%, Query {f(row?.queryPerMin?.med, 0)}번/분이에요.</p>
				<div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
					{#each [['Hibern8', `${f(run.h8PerMin, 0)}번/분`, `시간의 ${f(run.h8Pct, 0)}%가 Hibern8`], ['Hibern8 exit', `${f(run.h8ExitMs, 2)} ms`, `enter ${f(run.h8EnterMs, 2)} ms`], ['Query', `${f(run.queryPerMin, 0)}번/분`, `응답 median ${f(run.queryMsP50, 2)} · p99 ${f(run.queryMsP99, 2)} ms`], ['WB buffer 조회', `${f(run.wbCheckPerMin, 0)}번/분`, `suspend ${run.suspendN ?? 0}번 · exception ${run.exceptionN ?? 0}건`]] as k (k[0])}
						<div class="rounded-xl bg-muted px-4 py-3"><div class="text-body-3 text-muted-foreground">{k[0]}</div><div class="text-h4 font-bold tabular-nums">{k[1]}</div><div class="text-caption text-muted-foreground">{k[2]}</div></div>
					{/each}
				</div>
				{#if run.mgmtN}
					<CopyTable title="{id} Run {run.repeat} mgmt command" note="Query request·UIC command(보낸 쪽)·exception event 건수예요.">
						<table>
							<thead><tr><th>Command</th><th class="num">Count</th><th class="num">/min</th></tr></thead>
							<tbody>{#each Object.entries(run.mgmtN).sort((a, b) => b[1] - a[1]) as [k, v] (k)}<tr><td class="font-mono text-[12px]">{k}</td><td class="num" data-v={v}>{n0(v)}</td><td class="num">{f((v / run.durSec) * 60, 1)}</td></tr>{/each}</tbody>
						</table>
					</CopyTable>
				{/if}
			</section>
		{/if}

		<section class="mb-12 space-y-4">
			<h2 id="who" class="text-h2 font-bold">Write path · Attribution</h2>
			{#if row?.toolFixed}
				<div class="flex items-start gap-2 rounded-xl border bg-muted px-4 py-3 text-body-3">
					<Badge variant="outline">고친 도구</Badge>
					<span>10월 28일 수집 도구의 name attribution을 고친 뒤에 잰 값이에요. 앱·파일 이름과 Metadata(node·checkpoint) flag를 믿을 수 있어요.</span>
				</div>
			{:else}
				<div class="flex items-start gap-2 rounded-xl border bg-muted px-4 py-3 text-body-3">
					<Badge variant="outline">다시 재는 중</Badge>
					<span>이전 수집 도구로 잰 값이에요. Volume·속도·Latency는 맞지만, 앱·파일 이름과 Metadata flag는 다른 파일 것으로 붙은 경우가 많아요(최대 38%). 고친 도구로 다시 재고 있어요.</span>
				</div>
			{/if}
			<div class="grid gap-3 lg:grid-cols-2">
				<Chart spec={stackSpec('Write path (바이트 %)', ['Write'], B.flow, [run.flow], PROV_TRACE)} height={130} />
				<Chart spec={rwBarSpec('File type별 (MB)', run.kinds.map((k) => k.kind), run.kinds.map((k) => k.readMB), run.kinds.map((k) => k.writeMB), PROV_TRACE + ' 파일 이름 확장자·경로로 나눴어요.')} height={Math.max(160, 30 * run.kinds.length + 60)} />
			</div>
			<CopyTable title="{id} Run {run.repeat} Process 상위">
				<table>
					<thead><tr><th>Process</th><th class="num">pid</th><th class="num">Read MB</th><th class="num">Write MB</th><th>Thread</th></tr></thead>
					<tbody>{#each run.procs as p, i (i)}<tr><td>{p.name}</td><td class="num">{p.pid}</td><td class="num" data-v={p.readMB}>{f(p.readMB)}</td><td class="num" data-v={p.writeMB}>{f(p.writeMB)}</td><td class="max-w-[320px] truncate text-ink-3" title={p.threads}>{p.threads}</td></tr>{/each}</tbody>
				</table>
			</CopyTable>
			<CopyTable title="{id} Run {run.repeat} 파일 상위">
				<table>
					<thead><tr><th>파일</th><th>Kind</th><th class="num">Read MB</th><th class="num">Write MB</th><th class="num">Requests</th></tr></thead>
					<tbody>{#each run.files as fl, i (i)}<tr><td class="max-w-[480px] font-mono text-[11px] break-all">{fl.name}</td><td>{fl.kind}</td><td class="num" data-v={fl.readMB}>{f(fl.readMB)}</td><td class="num" data-v={fl.writeMB}>{f(fl.writeMB)}</td><td class="num" data-v={fl.n}>{n0(fl.n)}</td></tr>{/each}</tbody>
				</table>
			</CopyTable>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="slow" class="text-h2 font-bold">Slowest 30 requests</h2>
			<CopyTable title="{id} Run {run.repeat} Slow requests" note="Latency = 요청을 보내고 완료 응답까지(dtoc). QD은 완료 시점의 queue depth예요.">
				<table>
					<thead><tr><th class="num">시각 s</th><th>방향</th><th class="num">Size KB</th><th class="num">LUN</th><th class="num">LBA</th><th class="num">QD</th><th class="num">Latency ms</th><th>Thread</th><th>파일</th></tr></thead>
					<tbody>
						{#each run.slow as s, i (i)}
							<tr>
								<td class="num" data-v={s.t}>{f(s.t, 2)}</td><td>{s.dir === 'R' ? 'Read' : 'Write'}</td><td class="num">{s.kb}</td><td class="num">{s.lun}</td>
								<td class="num">{s.lba}</td><td class="num">{s.qd}</td><td class="num font-semibold" data-v={s.dtoc}>{f(s.dtoc, 2)}</td>
								<td>{s.comm}</td><td class="max-w-[360px] font-mono text-[11px] break-all text-ink-3">{s.file}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</CopyTable>
		</section>

		{#if jank}
			<section class="mb-12 space-y-4">
				<h2 id="jank" class="text-h2 font-bold">Jank vs Read</h2>
				<Chart spec={jankSpec(jank)} height={340} />
			</section>
		{/if}
	{/if}

	<section class="mb-12 space-y-4">
		<h2 id="compare" class="text-h2 font-bold">Same-type comparison</h2>
		<CopyTable title="{row.typeName} 안에서 {label(row)} 대비" note="배수 = 그 시나리오 ÷ 이 시나리오 (median).">
			<table>
				<thead><tr><th>Scenario</th><th>이름</th><th class="num">Read MB</th><th class="num">Write MB</th><th class="num">Read ×</th><th class="num">Write ×</th><th class="num">Peak MB/s</th><th class="num">Latency p99 Write ms</th></tr></thead>
				<tbody>
					{#each peers as p, i (i)}
						<tr class={p.key === row.key ? 'font-semibold' : ''}>
							<td><a href={resolve('/s/[id]', { id: p.id })}>{label(p)}</a></td><td>{nameOf(p)}</td>
							<td class="num" data-v={p.readMB.med}>{f(p.readMB.med)}</td><td class="num" data-v={p.writeMB.med}>{f(p.writeMB.med)}</td>
							<td class="num" data-v={p.readMB.med / row.readMB.med}>{x(p.readMB.med / row.readMB.med)}</td>
							<td class="num" data-v={p.writeMB.med / row.writeMB.med}>{x(p.writeMB.med / row.writeMB.med)}</td>
							<td class="num" data-v={p.peakMBs.med}>{f(p.peakMBs.med, 0)}</td><td class="num" data-v={p.dtocP99.W.med}>{f(p.dtocP99.W.med, 2)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</CopyTable>
		<p class="text-caption text-ink-3">원자료: <code>{doc.runFile}</code> · trace job 은 Run 표에 있어요.</p>
	</section>

	<nav class="flex justify-between gap-3 border-t pt-6" aria-label="이전·다음 시나리오">
		{#if idx > 0}
			<a href={resolve('/s/[id]', { id: typeIds[idx - 1] })} class="inline-flex items-center gap-1 text-label-s font-semibold text-primary"><ChevronLeft class="size-4" />{typeIds[idx - 1]} {app.names[typeIds[idx - 1]]}</a>
		{:else}<span></span>{/if}
		{#if idx >= 0 && idx < typeIds.length - 1}
			<a href={resolve('/s/[id]', { id: typeIds[idx + 1] })} class="inline-flex items-center gap-1 text-label-s font-semibold text-primary">{typeIds[idx + 1]} {app.names[typeIds[idx + 1]]}<ChevronRight class="size-4" /></a>
		{/if}
	</nav>
{/if}
