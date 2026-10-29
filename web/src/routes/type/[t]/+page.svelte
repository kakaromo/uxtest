<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import * as Tabs from '#lib/components/ui/tabs/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import Chart from '#lib/components/Chart.svelte';
	import CopyTable from '#lib/components/CopyTable.svelte';
	import MiniTimeline from '#lib/components/MiniTimeline.svelte';
	import { app } from '#lib/state.svelte.js';
	import { volSpec, mapSpec, stackSpec, miniOption, PROV_TRACE } from '#lib/charts/build.js';
	import { label, rowsOf, nameOf, rowOf, PAIRS, cname } from '#lib/view.js';
	import { copy, copyGrid } from '#lib/clipboard.js';
	import { theme } from '#lib/charts/theme.js';
	import { chartsHTML } from '#lib/charts/source.js';
	import { toast } from 'svelte-sonner';
	import { mb, f, x } from '#lib/fmt.js';
	import { emph, headlines, tint } from '#lib/insight.js';
	import { Table2, CodeXml } from '@lucide/svelte';

	const t = $derived(page.params.t!);
	const rs = $derived(rowsOf(t));
	const ids = $derived([...new Set(rs.map((r) => r.id))]);
	const art = $derived(app.content?.types[t]);
	const B = $derived(app.index!.meta.buckets);
	const pairs = $derived(PAIRS.filter((p) => ids.includes(p.a) || ids.includes(p.b)));
	const jank = $derived((app.index?.jank ?? []).filter((j) => ids.includes(j.scenario) && j.jank));
	const cats = $derived(rs.map(cname));
	// Distributions 의 Read·Write 차트를 HTML 조각 하나로 복사 (Confluence HTML macro 하나에 붙이기)
	async function copyDist(keys: (keyof typeof distSpecs)[], name: string) {
		const th = theme();
		const h = 26 * rs.length + 70;
		const html = chartsHTML(
			keys.map((k) => ({ o: distSpecs[k].option(th), title: distSpecs[k].title, height: h })),
			{ title: `${app.index!.types[t]} · ${name}`, bg: th.surface, fg: th.fg, caption: '값은 Run 평균이에요. 단위는 차트 제목에 있어요.' }
		);
		(await copy(html)) ? toast.success(`${name} 차트 ${keys.length}개를 HTML 하나로 복사했어요. Confluence HTML macro에 붙이면 돼요`) : toast.error('복사하지 못했어요');
	}
	// 표 칸 농도: 같은 열 안에서 상대 크기
	const col = (get: (r: (typeof rs)[number]) => number, log = false) => {
		const vals = rs.map(get);
		return (r: (typeof rs)[number]) => tint(get(r), vals, log);
	};
	const tR = $derived(col((r) => r.readMB.med, true));
	const tW = $derived(col((r) => r.writeMB.med, true));
	const tP = $derived(col((r) => r.peakMBs.med, true));
	const tL = $derived(col((r) => Math.max(r.dtocP99.R.med, r.dtocP99.W.med)));
	const tQ = $derived(col((r) => r.qdP99.med));
	const tI = $derived(col((r) => r.idlePct.med));

	let dist = $state('size');
	const distSpecs = $derived({
		sizeR: stackSpec('Request size 분포 · Read (건수 %)', cats, B.size, rs.map((r) => r.size.R), PROV_TRACE + ' Run 평균.'),
		sizeW: stackSpec('Request size 분포 · Write (건수 %)', cats, B.size, rs.map((r) => r.size.W), PROV_TRACE + ' Run 평균.'),
		dtocR: stackSpec('Latency 분포 · Read (건수 %)', cats, B.dtoc, rs.map((r) => r.dtoc.R), PROV_TRACE + ' Latency = 요청을 보내고 완료 응답까지(dtoc).'),
		dtocW: stackSpec('Latency 분포 · Write (건수 %)', cats, B.dtoc, rs.map((r) => r.dtoc.W), PROV_TRACE + ' Latency = 요청을 보내고 완료 응답까지(dtoc).'),
		gap: stackSpec('DtoD 분포 · dispatch-to-dispatch (건수 %)', cats, B.gap, rs.map((r) => r.gap), PROV_TRACE + ' 앞 request를 보낸 시각부터 다음 request를 보낸 시각까지예요. 16ms·200ms 넘는 간격은 UFS가 절전이나 유휴 정리에 들어갈 수 있는 틈이에요.', 1),
		ctod: stackSpec('CtoD 분포 · complete-to-dispatch (건수 %)', cats, B.ctod ?? ['0 (overlap)', '<1ms', '1–16ms', '16–200ms', '≥200ms'], rs.map((r) => r.ctod ?? [0, 0, 0, 0, 0]), PROV_TRACE + ' 직전 request 완료부터 이번 request를 보낼 때까지(parquet ctod). 0은 앞 request가 아직 처리 중일 때예요. Run 평균.', 1),
		flow: stackSpec('Write path (바이트 %)', cats, B.flow, rs.map((r) => r.flow), PROV_TRACE + ' fsiotrace flag로 나눴어요. 10월 28일 이전 측정은 flag가 다른 파일 것으로 붙은 경우가 있어요.')
	});

	// Timelines 의 작은 차트를 HTML 조각 하나로 복사
	async function copyTl() {
		const th = theme();
		const list = rs.filter((r) => r.tl).map((r) => ({ o: miniOption(th, r.tl!.readMBs, r.tl!.writeMBs), title: `${label(r)} ${nameOf(r)}`, height: 96 }));
		const html = chartsHTML(list, { title: `${app.index!.types[t]} · 1s Timeline`, bg: th.surface, fg: th.fg, caption: '대표 Run의 1초 단위 Read(위)·Write(아래) MB/s예요. 칸마다 세로 눈금이 달라요.' });
		(await copy(html)) ? toast.success(`Timeline 차트 ${list.length}개를 HTML 하나로 복사했어요. Confluence HTML macro에 붙이면 돼요`) : toast.error('복사하지 못했어요');
	}
	function tlGrid() {
		return {
			cols: ['시나리오', '초', 'Read MB/s', 'Write MB/s'],
			rows: rs.flatMap((r) => (r.tl?.readMBs ?? []).map((v, i) => [label(r), i, v, r.tl!.writeMBs[i]]))
		};
	}
</script>

<svelte:head><title>UX I/O 분석 · {t} {app.index?.types[t]}</title></svelte:head>

<nav class="mb-4 text-body-3 text-ink-3"><a href={resolve('/')} class="hover:text-foreground">홈</a> › {t} {app.index?.types[t]}</nav>
<header class="mb-8">
	<p class="text-label-s font-semibold text-primary">{t} 유형 · 시나리오 {ids.length}개</p>
	<h1 class="mt-2 text-h1 font-bold">{app.index?.types[t]}</h1>
	{#if art}<p class="mt-2 text-title-1 text-muted-foreground">{@html art.title}</p>{/if}
</header>

{#if art}
	<section class="mb-12">
		<h2 id="analysis" class="mb-2 text-h2 font-bold">Summary</h2>
		<div class="prose-ux summary">{@html emph(headlines(art.body))}</div>
	</section>
{/if}

<section class="mb-12 space-y-4">
	<h2 id="volume" class="text-h2 font-bold">Volume</h2>
	<p class="text-body-2 text-muted-foreground">시나리오마다 Read·Write 양이에요. 막대가 길수록 많이 썼어요 (로그 눈금).</p>
	<Chart spec={volSpec(rs, cname)} height={28 * rs.length + 80} />
</section>

<section class="mb-12 space-y-4">
	<h2 id="signature" class="text-h2 font-bold">Workload signature</h2>
	<p class="text-body-2 text-muted-foreground">시나리오마다 양, 모양, Latency를 한 줄로 모았어요. 칸이 진할수록 이 유형 안에서 큰 값이에요. 회색은 Run 최소~최대예요.</p>
	<CopyTable title="{t} Workload signature" note="Write ratio = Write 바이트 ÷ 전체. Sequential = 직전 요청 끝 LBA 에서 바로 이어진 바이트 비율. CV(Run 차이)가 0.5를 넘으면 Run마다 많이 달랐다는 뜻이에요.">
		<table>
			<thead>
				<tr><th>ID</th><th>Scenario</th><th class="num">Read MB</th><th class="num">Write MB</th><th class="num">Write ratio</th><th class="num">Peak MB/s</th><th class="num">Sequential R/W %</th><th class="num">Latency p99 R/W ms</th><th class="num">QD p99</th><th class="num">Metadata %</th><th class="num">Idle %</th><th class="num">CV</th><th>Top streams</th></tr>
			</thead>
			<tbody>
				{#each rs as r (r.key)}
					{@const tot = r.readMB.med + r.writeMB.med}
					<tr>
						<td><a href={resolve('/s/[id]', { id: r.id })}>{label(r)}</a></td>
						<td>{nameOf(r)}</td>
						<td class="num" style={tR(r)} data-v={r.readMB.med}>{f(r.readMB.med)}<span class="rg">{f(r.readMB.min, 0)}~{f(r.readMB.max, 0)}</span></td>
						<td class="num" style={tW(r)} data-v={r.writeMB.med}>{f(r.writeMB.med)}<span class="rg">{f(r.writeMB.min, 0)}~{f(r.writeMB.max, 0)}</span></td>
						<td class="num" data-v={tot ? (100 * r.writeMB.med) / tot : 0}>{tot ? f((100 * r.writeMB.med) / tot, 0) : 0}%</td>
						<td class="num" style={tP(r)} data-v={r.peakMBs.med}>{f(r.peakMBs.med, 0)}</td>
						<td class="num">{f(r.seq.R.med, 0)} / {f(r.seq.W.med, 0)}</td>
						<td class="num" style={tL(r)}>{f(r.dtocP99.R.med, 2)} / {f(r.dtocP99.W.med, 2)}</td>
						<td class="num" style={tQ(r)} data-v={r.qdP99.med}>{f(r.qdP99.med, 0)}</td>
						<td class="num" data-v={r.metaPct.med}>{f(r.metaPct.med, 0)}</td>
						<td class="num" style={tI(r)} data-v={r.idlePct.med}>{f(r.idlePct.med, 0)}</td>
						<td class="num {r.cv > 0.5 ? 'text-destructive' : ''}" data-v={r.cv}>{f(r.cv, 2)}</td>
						<td class="whitespace-nowrap">{(r.rep.streams ?? []).slice(0, 2).map((s) => `${s.seq} ${s.size} ${s.dir} ${s.pct.toFixed(0)}%`).join(' · ')}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</CopyTable>
</section>

<section class="mb-12 space-y-4">
	<div class="flex items-end gap-3">
		<h2 id="timelines" class="flex-1 text-h2 font-bold">Timelines</h2>
		<Button variant="quiet" size="xs" onclick={copyTl}><CodeXml />HTML 복사</Button>
		<Button variant="quiet" size="xs" onclick={() => copyGrid(tlGrid(), `${t} 1s Timeline`, '데이터')}><Table2 />Copy data</Button>
	</div>
	<p class="text-body-2 text-muted-foreground">대표 Run(Volume이 가운데인 Run)의 1초 단위 Read(위, 파랑)·Write(아래, 회색)예요. 칸마다 세로 눈금이 달라요. 누르면 시나리오 분석으로 가요.</p>
	<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
		{#each rs as r (r.key)}
			{#if r.tl}
				<a href={resolve('/s/[id]', { id: r.id })} class="rounded-xl border bg-card p-3 transition-colors hover:border-primary">
					<div class="flex items-baseline gap-2">
						<b class="text-[14px]">{label(r)}</b>
						<span class="ml-auto text-caption text-ink-3 tabular-nums">{r.tl.readMBs.length}s · R↑{f(Math.max(...r.tl.readMBs), 0)} W↓{f(Math.max(...r.tl.writeMBs), 0)} MB/s</span>
					</div>
					<p class="truncate text-body-3 text-muted-foreground">{nameOf(r)}</p>
					<MiniTimeline r={r.tl.readMBs} w={r.tl.writeMBs} />
				</a>
			{/if}
		{/each}
	</div>
</section>

<section class="mb-12 space-y-4">
	<h2 id="distributions" class="text-h2 font-bold">Distributions</h2>
	<Tabs.Root bind:value={dist} class="flex-col">
		<Tabs.List class="self-start">
			<Tabs.Trigger value="size">Request size</Tabs.Trigger>
			<Tabs.Trigger value="dtoc">Latency</Tabs.Trigger>
			<Tabs.Trigger value="gap">DtoD</Tabs.Trigger>
			<Tabs.Trigger value="ctod">CtoD</Tabs.Trigger>
			<Tabs.Trigger value="flow">Write path</Tabs.Trigger>
		</Tabs.List>
		<div class="flex flex-wrap items-center gap-1 text-body-3 text-ink-3">
			<span class="mr-1">HTML 복사 (차트 여러 개를 하나로):</span>
			<Button variant="secondary" size="xs" onclick={() => copyDist(['sizeR', 'sizeW'], 'Request size 분포')}><CodeXml />Request size</Button>
			<Button variant="secondary" size="xs" onclick={() => copyDist(['dtocR', 'dtocW'], 'Latency 분포')}><CodeXml />Latency</Button>
			<Button variant="secondary" size="xs" onclick={() => copyDist(['sizeR', 'sizeW', 'dtocR', 'dtocW'], 'Request size·Latency 분포')}><CodeXml />Request size + Latency</Button>
			<Button variant="secondary" size="xs" onclick={() => copyDist(['gap', 'ctod'], 'DtoD·CtoD 분포')}><CodeXml />DtoD + CtoD</Button>
			<Button variant="secondary" size="xs" onclick={() => copyDist(['sizeR', 'sizeW', 'dtocR', 'dtocW', 'gap', 'ctod', 'flow'], 'Distributions 전체')}><CodeXml />전체 7개</Button>
		</div>
		<Tabs.Content value="size" class="grid gap-3 lg:grid-cols-2">
			<Chart spec={distSpecs.sizeR} height={26 * rs.length + 70} />
			<Chart spec={distSpecs.sizeW} height={26 * rs.length + 70} />
		</Tabs.Content>
		<Tabs.Content value="dtoc" class="grid gap-3 lg:grid-cols-2">
			<Chart spec={distSpecs.dtocR} height={26 * rs.length + 70} />
			<Chart spec={distSpecs.dtocW} height={26 * rs.length + 70} />
		</Tabs.Content>
		<Tabs.Content value="gap"><Chart spec={distSpecs.gap} height={26 * rs.length + 70} /></Tabs.Content>
		<Tabs.Content value="ctod"><Chart spec={distSpecs.ctod} height={26 * rs.length + 70} /></Tabs.Content>
		<Tabs.Content value="flow"><Chart spec={distSpecs.flow} height={26 * rs.length + 70} /></Tabs.Content>
	</Tabs.Root>
</section>

<section class="mb-12 space-y-4">
	<h2 id="map" class="text-h2 font-bold">Workload map</h2>
	<Chart spec={mapSpec(rs, cname, `${t} 유형 지도`)} height={420} />
</section>

{#if pairs.length}
	<section class="mb-12 space-y-4">
		<h2 id="pairs" class="text-h2 font-bold">Paired conditions</h2>
		<p class="text-body-2 text-muted-foreground">조건 하나만 바꾼 시나리오 쌍이에요. 배수는 오른쪽 ÷ 왼쪽이에요.</p>
		<CopyTable title="{t} 조건 비교">
			<table>
				<thead><tr><th>비교</th><th>왼쪽</th><th class="num">Read MB</th><th class="num">Write MB</th><th>오른쪽</th><th class="num">Read MB</th><th class="num">Write MB</th><th class="num">Read ×</th><th class="num">Write ×</th></tr></thead>
				<tbody>
					{#each pairs as p (p.a + p.b)}
						{@const a = rowOf(p.a)}
						{@const b = rowOf(p.b)}
						{#if a && b}
							<tr>
								<td>{p.what}</td>
								<td><a href={resolve('/s/[id]', { id: a.id })}>{a.id}</a></td>
								<td class="num" data-v={a.readMB.med}>{f(a.readMB.med)}</td>
								<td class="num" data-v={a.writeMB.med}>{f(a.writeMB.med)}</td>
								<td><a href={resolve('/s/[id]', { id: b.id })}>{b.id}</a></td>
								<td class="num" data-v={b.readMB.med}>{f(b.readMB.med)}</td>
								<td class="num" data-v={b.writeMB.med}>{f(b.writeMB.med)}</td>
								<td class="num" data-v={b.readMB.med / a.readMB.med}>{x(b.readMB.med / a.readMB.med)}</td>
								<td class="num" data-v={b.writeMB.med / a.writeMB.med}>{x(b.writeMB.med / a.writeMB.med)}</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</CopyTable>
	</section>
{/if}

{#if jank.length}
	<section class="mb-12 space-y-4">
		<h2 id="jank" class="text-h2 font-bold">Jank vs I/O</h2>
		<CopyTable title="Jank frame과 Read" note="Jank frame = Perfetto FrameTimeline 에서 앱이 늦어 놓친 프레임. 프레임당 Read = 프레임 ±100ms 안 갤러리 Read 건수.">
			<table>
				<thead><tr><th>Scenario</th><th class="num">Run</th><th>Cache</th><th class="num">Frames</th><th class="num">Jank frame</th><th class="num">Frame p50/p99 ms</th><th class="num">Read per frame (Jank/OK)</th><th class="num">Read overlap % (Jank/OK)</th></tr></thead>
				<tbody>
					{#each jank as j (j.scenario + j.repeat)}
						<tr>
							<td><a href={resolve('/s/[id]', { id: j.scenario })}>{j.scenario}</a></td>
							<td class="num">{j.repeat}</td>
							<td>{j.cache}</td>
							<td class="num" data-v={j.total}>{j.total.toLocaleString()}</td>
							<td class="num" data-v={j.jank!.frames}>{j.jank!.frames} <span class="rg">({f((100 * j.jank!.frames) / j.total, 2)}%)</span></td>
							<td class="num">{f(j.frameDurP50, 1)} / {f(j.frameDurP99, 1)}</td>
							<td class="num">{f(j.jank!.readsPerFrame, 2)} / {f(j.normal!.readsPerFrame, 2)}</td>
							<td class="num">{f(j.jank!.withReadPct, 0)} / {f(j.normal!.withReadPct, 0)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</CopyTable>
	</section>
{/if}

<section class="mb-12 space-y-4">
	<h2 id="scenarios" class="text-h2 font-bold">Scenarios</h2>
	<div class="grid gap-3 sm:grid-cols-2">
		{#each ids as id (id)}
			{@const r = rowOf(id)!}
			<a href={resolve('/s/[id]', { id })} class="flex flex-col gap-1 rounded-xl border bg-card p-4 transition-colors hover:border-primary">
				<div class="flex items-center gap-2">
					<b class="text-[15px]">{id}</b>
					<Badge variant="secondary">P{r.prio}</Badge>
					{#if !r.success}<Badge variant="destructive">중간에 끊김</Badge>{/if}
					<span class="ml-auto text-body-3 text-ink-3 tabular-nums">R {mb(r.readMB.med)} · W {mb(r.writeMB.med)}</span>
				</div>
				<p class="text-body-2">{nameOf(r)}</p>
			</a>
		{/each}
	</div>
</section>
