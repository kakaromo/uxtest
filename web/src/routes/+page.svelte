<script lang="ts">
	import { resolve } from '$app/paths';
	import Chart from '#lib/components/Chart.svelte';
	import CopyTable from '#lib/components/CopyTable.svelte';
	import { app, TYPE_ORDER } from '#lib/state.svelte.js';
	import { volSpec, mapSpec } from '#lib/charts/build.js';
	import { label, rows, rowsOf, nameOf, cname } from '#lib/view.js';
	import { mb, f } from '#lib/fmt.js';
	import { emph } from '#lib/insight.js';
	import { ArrowRight } from '@lucide/svelte';

	const c = $derived(app.content!);
	const all = $derived(rows());
	const types = $derived(TYPE_ORDER.filter((t) => app.index?.types[t]));
</script>

<svelte:head><title>UX I/O 분석 · 홈</title></svelte:head>

<header class="mb-10">
	<p class="text-label-s font-semibold text-primary">P1·P2·대기 측정 · 2026-10-25~26</p>
	<h1 class="mt-2 text-display-2 font-bold">UX 워크로드 유형별 UFS I/O 패턴</h1>
	<p class="mt-4 max-w-[720px] text-body-1 text-muted-foreground">{@html c.lede}</p>
	<p class="mt-3 text-body-3 text-ink-3">{@html c.byline}</p>
</header>

<section class="mb-12">
	<h2 id="summary" class="mb-2 text-h2 font-bold">핵심 결론</h2>
	<p class="text-body-2 text-muted-foreground">누르면 해당 유형 페이지로 가요.</p>
	<div class="prose-ux"><ol class="takes">{@html emph(c.takes)}</ol></div>
</section>

<section class="mb-12">
	<h2 id="types" class="mb-4 text-h2 font-bold">유형</h2>
	<div class="grid gap-3 sm:grid-cols-2">
		{#each types as t (t)}
			{@const rs = rowsOf(t)}
			{@const ids = [...new Set(rs.map((r) => r.id))]}
			<a href={resolve('/type/[t]', { t })} class="group flex flex-col gap-2 rounded-2xl border bg-card p-5 transition-colors hover:border-primary">
				<div class="flex items-center gap-2">
					<span class="grid size-7 place-items-center rounded-sm bg-accent text-[13px] font-bold text-accent-foreground">{t}</span>
					<b class="text-title-1">{app.index!.types[t]}</b>
					<span class="ml-auto text-body-3 text-ink-3">시나리오 {ids.length}개</span>
				</div>
				<p class="text-body-2">{@html emph(c.types[t]?.title ?? '')}</p>
				<p class="text-body-3 text-ink-3">
					Read {mb(Math.min(...rs.map((r) => r.readMB.med)))}~{mb(Math.max(...rs.map((r) => r.readMB.med)))} · Write
					{mb(Math.min(...rs.map((r) => r.writeMB.med)))}~{mb(Math.max(...rs.map((r) => r.writeMB.med)))}
				</p>
				<span class="mt-auto inline-flex items-center gap-1 text-label-s font-semibold text-primary">유형 분석 보기 <ArrowRight class="size-4 transition-transform group-hover:translate-x-0.5" /></span>
			</a>
		{/each}
	</div>
</section>

<section class="mb-12 space-y-4">
	<h2 id="glance" class="text-h2 font-bold">유형별 한눈에</h2>
	<CopyTable title="유형별 한눈에"><table>{@html c.glance}</table></CopyTable>
	<h3 id="volume" class="pt-4 text-h4 font-bold" data-toc="Volume 비교">Volume by scenario</h3>
	<Chart spec={volSpec(all, cname)} height={22 * all.length + 70} caption="카메라·갤러리는 GB 단위, 웹·피드는 MB 단위라 가로축을 로그 눈금으로 그렸어요." />
	<h3 id="map" class="pt-4 text-h4 font-bold" data-toc="Workload map">Workload map</h3>
	<Chart spec={mapSpec(all, cname)} height={460} caption="오른쪽일수록 순차, 위쪽일수록 Write 위주예요." />
</section>

<section class="mb-12 space-y-4">
	<h2 id="scenarios" class="text-h2 font-bold">All scenarios</h2>
	<CopyTable title="All scenarios" note="값은 Run들의 median, 회색은 최소~최대예요. ID를 누르면 시나리오 분석 페이지로 가요.">
		<table>
			<thead><tr><th>ID</th><th>유형</th><th>시나리오</th><th>P</th><th class="num">Duration s</th><th class="num">Read MB</th><th class="num">Write MB</th><th class="num">Peak MB/s</th><th class="num">Idle %</th><th class="num">Run</th></tr></thead>
			<tbody>
				{#each all as r (r.key)}
					<tr>
						<td><a href={resolve('/s/[id]', { id: r.id })}>{label(r)}</a></td>
						<td>{r.typeName}</td>
						<td>{nameOf(r)}</td>
						<td class="num">P{r.prio}</td>
						<td class="num" data-v={r.durSec.med}>{f(r.durSec.med, 0)}</td>
						<td class="num" data-v={r.readMB.med}>{f(r.readMB.med)}<span class="rg">{f(r.readMB.min, 0)}~{f(r.readMB.max, 0)}</span></td>
						<td class="num" data-v={r.writeMB.med}>{f(r.writeMB.med)}<span class="rg">{f(r.writeMB.min, 0)}~{f(r.writeMB.max, 0)}</span></td>
						<td class="num" data-v={r.peakMBs.med}>{f(r.peakMBs.med, 0)}</td>
						<td class="num" data-v={r.idlePct.med}>{f(r.idlePct.med, 0)}</td>
						<td class="num">{r.repeats}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</CopyTable>
</section>

{#if c.mgmt}
	<section class="mb-12 space-y-4">
		<h2 id="mgmt" class="mb-3 text-h2 font-bold">UFS mgmt command</h2>
		<div class="prose-ux">{@html c.mgmt}</div>
		{#if c.mgmtTable}<CopyTable title="유형별 UFS mgmt command"><table>{@html c.mgmtTable}</table></CopyTable>{/if}
		<CopyTable title="시나리오별 UFS mgmt command" note="/분 값과 H8 exit는 Run들의 median, suspend(fBackgroundOpsEn clear)와 qTimestamp 쓰기는 Run 합이에요.">
			<table>
				<thead><tr><th>ID</th><th class="num">Hibern8 /분</th><th class="num">Hibern8 시간 %</th><th class="num">H8 exit ms</th><th class="num">Query /분</th><th class="num">bBackgroundOpStatus /분</th><th class="num">WB 조회 /분</th><th class="num">suspend</th><th class="num">qTimestamp</th></tr></thead>
				<tbody>
					{#each all.filter((r) => r.h8PerMin) as r (r.key)}
						<tr>
							<td><a href={resolve('/s/[id]', { id: r.id })}>{label(r)}</a></td>
							<td class="num" data-v={r.h8PerMin?.med}>{f(r.h8PerMin?.med, 0)}</td>
							<td class="num" data-v={r.h8Pct?.med}>{f(r.h8Pct?.med, 0)}</td>
							<td class="num" data-v={r.h8ExitMs?.med}>{f(r.h8ExitMs?.med, 2)}</td>
							<td class="num" data-v={r.queryPerMin?.med}>{f(r.queryPerMin?.med, 0)}</td>
							<td class="num" data-v={r.bkopsPerMin?.med}>{f(r.bkopsPerMin?.med, 0)}</td>
							<td class="num" data-v={r.wbCheckPerMin?.med}>{f(r.wbCheckPerMin?.med, 0)}</td>
							<td class="num">{r.mgmtN?.['Clear Flag(fBackgroundOpsEn)'] ?? 0}</td>
							<td class="num">{r.mgmtN?.['Write Attribute(qTimestamp)'] ?? 0}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</CopyTable>
	</section>
{/if}

<section class="mb-12">
	<h2 id="method" class="mb-3 text-h2 font-bold">측정 방법</h2>
	<div class="prose-ux">{@html c.method}</div>
</section>

<section class="mb-12">
	<h2 id="limits" class="mb-3 text-h2 font-bold">한계</h2>
	<div class="prose-ux">{@html c.limits}</div>
</section>
