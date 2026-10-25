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
	import { volSpec, mapSpec, stackSpec, PROV_TRACE } from '#lib/charts/build.js';
	import { label, rowsOf, nameOf, rowOf, PAIRS } from '#lib/view.js';
	import { copyGrid } from '#lib/clipboard.js';
	import { mb, f, x } from '#lib/fmt.js';
	import { Table2 } from '@lucide/svelte';

	const t = $derived(page.params.t!);
	const rs = $derived(rowsOf(t));
	const ids = $derived([...new Set(rs.map((r) => r.id))]);
	const art = $derived(app.content?.types[t]);
	const B = $derived(app.index!.meta.buckets);
	const pairs = $derived(PAIRS.filter((p) => ids.includes(p.a) || ids.includes(p.b)));
	const jank = $derived((app.index?.jank ?? []).filter((j) => ids.includes(j.scenario) && j.jank));
	const cats = $derived(rs.map(label));

	let dist = $state('size');
	const distSpecs = $derived({
		sizeR: stackSpec('Request size 분포 · Read (건수 %)', cats, B.size, rs.map((r) => r.size.R), PROV_TRACE + ' Run 평균.'),
		sizeW: stackSpec('Request size 분포 · Write (건수 %)', cats, B.size, rs.map((r) => r.size.W), PROV_TRACE + ' Run 평균.'),
		dtocR: stackSpec('Latency 분포 · Read (건수 %)', cats, B.dtoc, rs.map((r) => r.dtoc.R), PROV_TRACE + ' Latency = 요청을 보내고 완료 응답까지(dtoc).'),
		dtocW: stackSpec('Latency 분포 · Write (건수 %)', cats, B.dtoc, rs.map((r) => r.dtoc.W), PROV_TRACE + ' Latency = 요청을 보내고 완료 응답까지(dtoc).'),
		gap: stackSpec('Inter-arrival 분포 (건수 %)', cats, B.gap, rs.map((r) => r.gap), PROV_TRACE + ' 16ms·200ms 넘는 간격은 UFS가 절전이나 유휴 정리에 들어갈 수 있는 틈이에요.', 1),
		flow: stackSpec('Write path (바이트 %)', cats, B.flow, rs.map((r) => r.flow), PROV_TRACE + ' fsiotrace 플래그로 나눴어요. 이름 귀속처럼 일부 플래그는 확인 중이에요.')
	});

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
		<h2 id="analysis" class="mb-2 text-h2 font-bold">해설</h2>
		<div class="prose-ux">{@html art.body}</div>
	</section>
{/if}

<section class="mb-12 space-y-4">
	<h2 id="signature" class="text-h2 font-bold">Workload signature</h2>
	<p class="text-body-2 text-muted-foreground">시나리오마다 양, 모양, Latency을 한 줄로 모았어요. 회색은 Run 최소~최대예요.</p>
	<CopyTable title="{t} Workload signature" note="Write ratio = Write 바이트 ÷ 전체. Sequential = 직전 요청 끝 LBA 에서 바로 이어진 바이트 비율. CV(Run 차이)가 0.5를 넘으면 Run마다 많이 달랐다는 뜻이에요.">
		<table>
			<thead>
				<tr><th>ID</th><th>시나리오</th><th class="num">Read MB</th><th class="num">Write MB</th><th class="num">Write ratio</th><th class="num">Peak MB/s</th><th class="num">이어진 R/W %</th><th class="num">Latency p99 R/W ms</th><th class="num">QD p99</th><th class="num">메타 %</th><th class="num">쉬는 %</th><th class="num">CV</th><th>많은 요청 형태</th></tr>
			</thead>
			<tbody>
				{#each rs as r (r.key)}
					{@const tot = r.readMB.med + r.writeMB.med}
					<tr>
						<td><a href={resolve('/s/[id]', { id: r.id })}>{label(r)}</a></td>
						<td>{nameOf(r)}</td>
						<td class="num" data-v={r.readMB.med}>{f(r.readMB.med)}<span class="rg">{f(r.readMB.min, 0)}~{f(r.readMB.max, 0)}</span></td>
						<td class="num" data-v={r.writeMB.med}>{f(r.writeMB.med)}<span class="rg">{f(r.writeMB.min, 0)}~{f(r.writeMB.max, 0)}</span></td>
						<td class="num" data-v={tot ? (100 * r.writeMB.med) / tot : 0}>{tot ? f((100 * r.writeMB.med) / tot, 0) : 0}%</td>
						<td class="num" data-v={r.peakMBs.med}>{f(r.peakMBs.med, 0)}</td>
						<td class="num">{f(r.seq.R.med, 0)} / {f(r.seq.W.med, 0)}</td>
						<td class="num">{f(r.dtocP99.R.med, 2)} / {f(r.dtocP99.W.med, 2)}</td>
						<td class="num" data-v={r.qdP99.med}>{f(r.qdP99.med, 0)}</td>
						<td class="num" data-v={r.metaPct.med}>{f(r.metaPct.med, 0)}</td>
						<td class="num" data-v={r.idlePct.med}>{f(r.idlePct.med, 0)}</td>
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
	<h2 id="volume" class="text-h2 font-bold">Volume</h2>
	<Chart spec={volSpec(rs, label)} height={28 * rs.length + 80} />
</section>

<section class="mb-12 space-y-4">
	<h2 id="distributions" class="text-h2 font-bold">Distributions</h2>
	<Tabs.Root bind:value={dist} class="flex-col">
		<Tabs.List class="self-start">
			<Tabs.Trigger value="size">Request size</Tabs.Trigger>
			<Tabs.Trigger value="dtoc">Latency</Tabs.Trigger>
			<Tabs.Trigger value="gap">Inter-arrival</Tabs.Trigger>
			<Tabs.Trigger value="flow">Write path</Tabs.Trigger>
		</Tabs.List>
		<Tabs.Content value="size" class="grid gap-3 lg:grid-cols-2">
			<Chart spec={distSpecs.sizeR} height={26 * rs.length + 70} />
			<Chart spec={distSpecs.sizeW} height={26 * rs.length + 70} />
		</Tabs.Content>
		<Tabs.Content value="dtoc" class="grid gap-3 lg:grid-cols-2">
			<Chart spec={distSpecs.dtocR} height={26 * rs.length + 70} />
			<Chart spec={distSpecs.dtocW} height={26 * rs.length + 70} />
		</Tabs.Content>
		<Tabs.Content value="gap"><Chart spec={distSpecs.gap} height={26 * rs.length + 70} /></Tabs.Content>
		<Tabs.Content value="flow"><Chart spec={distSpecs.flow} height={26 * rs.length + 70} /></Tabs.Content>
	</Tabs.Root>
</section>

<section class="mb-12 space-y-4">
	<h2 id="map" class="text-h2 font-bold">Workload map</h2>
	<Chart spec={mapSpec(rs, label, `${t} 유형 지도`)} height={420} />
</section>

{#if pairs.length}
	<section class="mb-12 space-y-4">
		<h2 id="pairs" class="text-h2 font-bold">Paired conditions</h2>
		<p class="text-body-2 text-muted-foreground">조건 하나만 바꾼 시나리오 쌍이에요. 배수는 오른쪽 ÷ 왼쪽이에요.</p>
		<CopyTable title="{t} 조건 비교">
			<table>
				<thead><tr><th>비교</th><th>왼쪽</th><th class="num">Read MB</th><th class="num">Write MB</th><th>오른쪽</th><th class="num">Read MB</th><th class="num">Write MB</th><th class="num">Read 배수</th><th class="num">Write 배수</th></tr></thead>
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
				<thead><tr><th>시나리오</th><th class="num">Run</th><th>캐시</th><th class="num">프레임</th><th class="num">Jank frame</th><th class="num">프레임 p50/p99 ms</th><th class="num">프레임당 Read (끊김/정상)</th><th class="num">Read 겹침 % (끊김/정상)</th></tr></thead>
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
