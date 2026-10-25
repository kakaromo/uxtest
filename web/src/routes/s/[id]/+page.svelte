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
	import { load } from '#lib/crypto.js';
	import { explorerSpec, overlaySpec, runsSpec, latSpec, lbaSpec, stackSpec, rwBarSpec, jankSpec, PROV_TRACE } from '#lib/charts/build.js';
	import { rowsOf, nameOf, label } from '#lib/view.js';
	import { mb, f, n0, x, sec } from '#lib/fmt.js';
	import type { ScenarioDoc, Run } from '#lib/types.js';
	import { ChevronLeft, ChevronRight } from '@lucide/svelte';

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
	const jank = $derived(doc?.jank.find((j) => String(j.repeat) === repSel && j.sec?.length));

	// 시간축 탐색기에서 고른 구간의 통계
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
	const exSpec = $derived(run ? explorerSpec(run, res, `${id} · ${run.repeat}회차 시간축 (${res === '1s' ? '1초' : '100ms'} 단위 MB/s, 위 읽기 · 아래 쓰기)`) : null);
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
			<Badge variant="secondary">{row.repeats}회 측정</Badge>
			<Badge variant="secondary">측정 구간 {sec(row.durSec.med)}</Badge>
			{#if row.cache}<Badge variant="secondary">{row.cache === 'cold' ? '캐시 없음(cold)' : '캐시 있음(warm)'}</Badge>{/if}
			{#if !row.success}<Badge variant="destructive">중간에 끊김 · 남은 구간만</Badge>{/if}
		</div>
		{#if doc.rows.length > 1}
			<div class="mt-4 flex items-center gap-3">
				<span class="text-label-s font-semibold text-muted-foreground">조건</span>
				<ToggleGroup.Root type="single" bind:value={groupSel} variant="outline" size="sm">
					{#each doc.rows as r (r.key)}
						<ToggleGroup.Item value={r.key}>{r.cache === 'cold' ? '첫 회차 (cold)' : '2·3회차 (warm)'}</ToggleGroup.Item>
					{/each}
				</ToggleGroup.Root>
			</div>
		{/if}
	</header>

	<section class="mb-12">
		<h2 id="numbers" class="mb-4 text-h2 font-bold">핵심 수치</h2>
		<dl class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
			{#each [['읽기', mb(row.readMB.med), `${f(row.readMB.min, 0)}~${f(row.readMB.max, 0)} MB`], ['쓰기', mb(row.writeMB.med), `${f(row.writeMB.min, 0)}~${f(row.writeMB.max, 0)} MB`], ['블록 반납(discard)', mb(row.discardMB.med), ''], ['최고 속도', `${f(row.peakMBs.med, 0)} MB/s`, '1초 칸 기준'], ['쉬는 시간', `${f(row.idlePct.med, 0)}%`, '요청 없는 100ms 칸'], ['동시 요청 p99', f(row.qdP99.med, 0), '큐 깊이'], ['지연 p99 읽기·쓰기', `${f(row.dtocP99.R.med, 2)} · ${f(row.dtocP99.W.med, 2)} ms`, ''], ['이어진 요청 R·W', `${f(row.seq.R.med, 0)} · ${f(row.seq.W.med, 0)}%`, '순차 비율'], ['메타데이터', `${f(row.metaPct.med, 0)}%`, '쓰기 바이트 중'], ['요청 수 R·W', `${n0(row.readN.med)} · ${n0(row.writeN.med)}`, ''], ...(row.wakesPerMin ? [['깨어남', `${f(row.wakesPerMin.med, 0)}번/분`, `가장 긴 쉼 ${f(row.maxGapSec?.med, 1)}초`], ['flush', `${f(row.flushPerSec?.med, 1)}번/초`, '']] : []), ['회차 차이', f(row.cv, 2), row.cv > 0.5 ? '변동 큼 (CV>0.5)' : 'CV']] as k (k[0])}
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
			<h2 id="explorer" class="text-h2 font-bold">시간축 탐색</h2>
			<p class="text-body-2 text-muted-foreground">아래 막대를 끌거나 차트 위에서 스크롤해서 구간을 확대해요. 옅은 파란 띠는 시나리오 스텝 구간이에요. 고른 구간의 합계가 바로 아래에 나와요.</p>
			<div class="flex flex-wrap items-center gap-4">
				<div class="flex items-center gap-2">
					<span class="text-label-s font-semibold text-muted-foreground">회차</span>
					<ToggleGroup.Root type="single" bind:value={repSel} variant="outline" size="sm">
						{#each doc.runs as r (r.repeat)}<ToggleGroup.Item value={String(r.repeat)}>{r.repeat}회차{r.cache ? ` ${r.cache}` : ''}</ToggleGroup.Item>{/each}
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
					<div><dt class="text-muted-foreground">읽기</dt><dd class="font-bold tabular-nums">{mb(sel.read)}</dd></div>
					<div><dt class="text-muted-foreground">쓰기</dt><dd class="font-bold tabular-nums">{mb(sel.write)}</dd></div>
					<div><dt class="text-muted-foreground">최고 MB/s</dt><dd class="font-bold tabular-nums">{f(sel.peak, 0)}</dd></div>
					<div><dt class="text-muted-foreground">동시 요청 최대</dt><dd class="font-bold tabular-nums">{sel.qd}</dd></div>
					<div><dt class="text-muted-foreground">지연 p99 최대</dt><dd class="font-bold tabular-nums">{f(sel.p99, 2)} ms</dd></div>
					<div><dt class="text-muted-foreground">discard</dt><dd class="font-bold tabular-nums">{n0(sel.disc)}건</dd></div>
					<div><dt class="text-muted-foreground">flush</dt><dd class="font-bold tabular-nums">{n0(sel.flush)}건</dd></div>
				</dl>
			{/if}
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="steps" class="text-h2 font-bold">스텝별 I/O</h2>
			<p class="text-body-2 text-muted-foreground">측정 구간 안 스텝마다 쓴 양이에요 ({run.repeat}회차). 스텝 시각은 agent 가 기록한 boot clock 이라 저장장치 기록과 같은 시계예요.</p>
			<CopyTable title="{id} {run.repeat}회차 스텝별 I/O">
				<table>
					<thead><tr><th class="num">#</th><th>스텝</th><th>종류</th><th class="num">시작 s</th><th class="num">끝 s</th><th class="num">읽기 MB</th><th class="num">쓰기 MB</th><th class="num">요청</th><th class="num">지연 p99 ms</th></tr></thead>
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
				<summary class="cursor-pointer text-label-s font-semibold">시나리오 전체 스텝 ({doc.steps.length}개)</summary>
				<ol class="mt-2 list-decimal space-y-0.5 pl-6 text-body-3">
					{#each doc.steps as s, i (i)}<li><span class="text-ink-3">{s.type}</span> {s.label}</li>{/each}
				</ol>
			</details>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="runs" class="text-h2 font-bold">회차 비교</h2>
			<div class="grid gap-3 lg:grid-cols-2">
				<Chart spec={runsSpec(doc.runs)} height={260} />
				<Chart spec={overlaySpec(doc.runs)} height={260} />
			</div>
			<CopyTable title="{id} 회차별 지표" note="CV = 회차 총량의 표준편차 ÷ 평균.">
				<table>
					<thead><tr><th class="num">회차</th><th>캐시</th><th class="num">측정 s</th><th class="num">읽기 MB</th><th class="num">쓰기 MB</th><th class="num">discard MB</th><th class="num">최고 MB/s</th><th class="num">지연 p99 R/W</th><th class="num">동시 요청 p99</th><th class="num">쉬는 %</th><th>trace job</th></tr></thead>
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
			<h2 id="shape" class="text-h2 font-bold">요청 모양과 지연</h2>
			<p class="text-body-2 text-muted-foreground">{run.repeat}회차 기준이에요. 위의 회차 선택을 바꾸면 같이 바뀌어요.</p>
			<div class="grid gap-3 lg:grid-cols-2">
				<Chart spec={stackSpec('요청 크기 분포 (건수 %)', ['읽기', '쓰기'], B.size, [run.size.R, run.size.W], PROV_TRACE)} height={170} />
				<Chart spec={stackSpec('응답 시간 분포 (건수 %)', ['읽기', '쓰기'], B.dtoc, [run.dtoc.R, run.dtoc.W], PROV_TRACE)} height={170} />
				<Chart spec={latSpec('요청 크기별 지연 (p50 막대, p99 선)', B.size, run.latSize, PROV_TRACE + ' 완료 응답(complete_rsp)의 dtoc 를 요청 크기 구간마다 백분위로.')} height={280} />
				<Chart spec={latSpec('동시 요청 수별 지연 (p50 막대, p99 선)', QB, run.latQd, PROV_TRACE + ' 완료 시점의 큐 깊이 구간마다 dtoc 백분위.')} height={280} />
				<Chart spec={stackSpec('요청 사이 간격 (건수 %)', ['전체'], B.gap, [run.gap], PROV_TRACE + ' 16ms·200ms 넘는 간격은 저장장치가 절전·유휴 정리에 들어갈 수 있는 틈이에요.', 1)} height={130} />
				<CopyTable title="많은 요청 형태 (바이트 %)">
					<table>
						<thead><tr><th>방향</th><th>크기</th><th>순차/랜덤</th><th class="num">바이트 %</th></tr></thead>
						<tbody>{#each run.streams as s, i (i)}<tr><td>{s.dir === 'R' ? '읽기' : '쓰기'}</td><td>{s.size}</td><td>{s.seq === 'SEQ' ? '이어짐' : '랜덤'}</td><td class="num" data-v={s.pct}>{f(s.pct)}</td></tr>{/each}</tbody>
					</table>
				</CopyTable>
			</div>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="lba" class="text-h2 font-bold">저장장치 위치</h2>
			<div class="grid gap-3 lg:grid-cols-2">
				<Chart spec={lbaSpec(run, 'R', app.index!.meta.lbaMaxGB)} height={320} />
				<Chart spec={lbaSpec(run, 'W', app.index!.meta.lbaMaxGB)} height={320} />
			</div>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="who" class="text-h2 font-bold">경로와 주체</h2>
			<div class="flex items-start gap-2 rounded-xl border bg-muted px-4 py-3 text-body-3">
				<Badge variant="outline">확인 중</Badge>
				<span>총량·속도·지연은 저장장치 요청 그대로라 믿을 수 있어요. 어떤 앱·파일이 썼는지는 수집 도구의 이름 귀속이 일부 맞지 않아 참고용이에요.</span>
			</div>
			<div class="grid gap-3 lg:grid-cols-2">
				<Chart spec={stackSpec('쓰기 경로 (바이트 %)', ['쓰기'], B.flow, [run.flow], PROV_TRACE)} height={130} />
				<Chart spec={rwBarSpec('파일 종류별 (MB)', run.kinds.map((k) => k.kind), run.kinds.map((k) => k.readMB), run.kinds.map((k) => k.writeMB), PROV_TRACE + ' 파일 이름 확장자·경로로 나눴어요.')} height={Math.max(160, 30 * run.kinds.length + 60)} />
			</div>
			<CopyTable title="{id} {run.repeat}회차 프로세스 상위">
				<table>
					<thead><tr><th>프로세스</th><th class="num">pid</th><th class="num">읽기 MB</th><th class="num">쓰기 MB</th><th>스레드</th></tr></thead>
					<tbody>{#each run.procs as p, i (i)}<tr><td>{p.name}</td><td class="num">{p.pid}</td><td class="num" data-v={p.readMB}>{f(p.readMB)}</td><td class="num" data-v={p.writeMB}>{f(p.writeMB)}</td><td class="max-w-[320px] truncate text-ink-3" title={p.threads}>{p.threads}</td></tr>{/each}</tbody>
				</table>
			</CopyTable>
			<CopyTable title="{id} {run.repeat}회차 파일 상위">
				<table>
					<thead><tr><th>파일</th><th>종류</th><th class="num">읽기 MB</th><th class="num">쓰기 MB</th><th class="num">요청</th></tr></thead>
					<tbody>{#each run.files as fl, i (i)}<tr><td class="max-w-[480px] font-mono text-[11px] break-all">{fl.name}</td><td>{fl.kind}</td><td class="num" data-v={fl.readMB}>{f(fl.readMB)}</td><td class="num" data-v={fl.writeMB}>{f(fl.writeMB)}</td><td class="num" data-v={fl.n}>{n0(fl.n)}</td></tr>{/each}</tbody>
				</table>
			</CopyTable>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="slow" class="text-h2 font-bold">느린 요청 상위 30</h2>
			<CopyTable title="{id} {run.repeat}회차 느린 요청" note="지연 = 요청을 보내고 완료 응답까지(dtoc). 동시 요청은 완료 시점의 큐 깊이예요.">
				<table>
					<thead><tr><th class="num">시각 s</th><th>방향</th><th class="num">크기 KB</th><th class="num">LUN</th><th class="num">LBA</th><th class="num">동시 요청</th><th class="num">지연 ms</th><th>스레드</th><th>파일</th></tr></thead>
					<tbody>
						{#each run.slow as s, i (i)}
							<tr>
								<td class="num" data-v={s.t}>{f(s.t, 2)}</td><td>{s.dir === 'R' ? '읽기' : '쓰기'}</td><td class="num">{s.kb}</td><td class="num">{s.lun}</td>
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
				<h2 id="jank" class="text-h2 font-bold">화면 끊김과 읽기</h2>
				<Chart spec={jankSpec(jank)} height={340} />
			</section>
		{/if}
	{/if}

	<section class="mb-12 space-y-4">
		<h2 id="compare" class="text-h2 font-bold">같은 유형과 비교</h2>
		<CopyTable title="{row.typeName} 안에서 {label(row)} 대비" note="배수 = 그 시나리오 ÷ 이 시나리오 (중앙값).">
			<table>
				<thead><tr><th>시나리오</th><th>이름</th><th class="num">읽기 MB</th><th class="num">쓰기 MB</th><th class="num">읽기 배수</th><th class="num">쓰기 배수</th><th class="num">최고 MB/s</th><th class="num">지연 p99 쓰기 ms</th></tr></thead>
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
		<p class="text-caption text-ink-3">원자료: <code>{doc.runFile}</code> · trace job 은 회차 표에 있어요.</p>
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
