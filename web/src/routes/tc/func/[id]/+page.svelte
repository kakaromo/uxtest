<script lang="ts">
	// 시나리오 함수 TC 한 함수의 동작 순서 (tcseq-<id>.json, wl/export_func_site.py export_seq)
	// 파일은 회차 안 번호(f12), DB 는 DB 파일 순서 번호(DB3)로만 보인다.
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import * as ToggleGroup from '#lib/components/ui/toggle-group/index.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import Chart from '#lib/components/Chart.svelte';
	import CopyTable from '#lib/components/CopyTable.svelte';
	import { tcSeqSpec, type SeqTl, type SeqStep } from '#lib/charts/build.js';
	import { copyGrid, saveCSV, type Grid } from '#lib/clipboard.js';
	import { load } from '#lib/data.js';
	import { f, n0, sec } from '#lib/fmt.js';
	import { ChevronRight, ListOrdered, Download } from '@lucide/svelte';

	/** 동작 줄: [시각 s, op, 대상(>=0 파일 f번호, <0 DB 번호, null 없음), 횟수 또는 SQLite 종류, 바이트 또는 SQLite page 수] */
	type Item = [number, number, number | null, number, number];
	type Burst = { s: number; e: number; ops: Record<string, number>; r: number; w: number; ni: number; it?: Item[] };
	type Rep = {
		seg: string; dur: number; files: number; prefill: number; prefillMB: number; dbs: number; ops: Record<string, number>; n: number;
		rMB: number; wMB: number; tl: SeqTl; bursts: Burst[]; itemsUpTo: number | null; steps: SeqStep[];
	};
	type Check = { k: string; o: number | number[] | null; t: number | number[] | null; ok: boolean | null };
	type Doc = {
		id: string; name: string; g: string; gk: string; allSteps: string[]; loops: { a: number; b: number; n: number }[];
		marks: Record<string, string>; reps: Rep[]; checks: Check[]; pass: number | null; of: number | null; checkRep: number | null; gap: number; fold: number;
	};

	const OPN: Record<number, string> = {
		0: 'Read', 1: 'Write', 2: 'buffered Write', 3: 'direct Write', 4: 'fsync', 6: 'unlink', 9: 'atomic commit', 10: 'atomic Write',
		13: '폴더 fsync', 15: 'SQLite', 16: 'sync', 17: 'rename', 18: 'touch'
	};
	const SQLK: Record<number, string> = { 1: 'WAL commit + checkpoint', 2: 'WAL commit', 3: 'WAL 쓰기 (fsync 없음)', 4: 'rollback journal transaction' };
	const opName = (o: number | string) => OPN[+o] ?? `op ${o}`;
	const sqlKind = (k: number) => (SQLK[k & 0xf] ?? `종류 ${k & 0xf}`) + (k & 0x10 ? ' (DB 다시 열기)' : '');
	const tgt = (x: number | null) => (x == null ? '' : x < 0 ? `DB${-x}` : `f${x}`);
	const size = (b: number) => (b >= 1e6 ? `${(b / 1e6).toFixed(b >= 1e8 ? 0 : 1)}MB` : b >= 1024 ? `${Math.round(b / 1024)}KB` : b > 0 ? `${b}B` : '');
	const kb = (b: number) => Math.round((b / 1024) * 10) / 10;
	const repNo = (r: Rep) => r.seg.split('-').pop();
	// op 색: Read, Write 계열, direct Write, SQLite, 나머지(fsync·unlink 등)
	const opTone = (o: number) => (o === 0 ? 'r' : o === 3 ? 'wd' : o === 15 ? 'db' : [1, 2, 9, 10].includes(o) ? 'w' : 'm');

	const id = $derived(page.params.id!);
	let doc = $state<Doc | null>(null);
	let err = $state('');
	let repSel = $state('0');
	let showAll = $state(false);
	let limit = $state(300);
	let open = $state<Set<number>>(new Set());

	$effect(() => {
		const want = id;
		doc = null;
		err = '';
		load<Doc>(`tcseq-${want}`)
			.then((d) => {
				if (want !== id) return;
				doc = d;
				repSel = '0';
			})
			.catch(() => (err = '이 함수의 동작 순서 데이터를 불러오지 못했어요.'));
	});

	const rep = $derived(doc ? doc.reps[+repSel] ?? doc.reps[0] : null);
	const isBig = (b: Burst) => b.r + b.w >= 1e5 || b.ni >= 6;
	const shown = $derived(rep ? rep.bursts.map((b, k) => ({ b, k })).filter((x) => showAll || isBig(x.b)) : []);
	const nSmall = $derived(rep ? rep.bursts.filter((b) => !isBig(b)).length : 0);
	// 회차를 바꾸면 첫 큰 묶음만 펼친다
	$effect(() => {
		const r = rep;
		showAll = false;
		limit = 300;
		const k = r ? r.bursts.findIndex((b) => isBig(b) && b.it) : -1;
		open = new Set(k >= 0 ? [k] : []);
	});
	function toggle(k: number) {
		const s = new Set(open);
		if (s.has(k)) s.delete(k);
		else s.add(k);
		open = s;
	}

	// 시나리오 조작 순서: step 번호(i)마다 측정 구간을 모은다 (반복 step 은 여러 번)
	const stepRows = $derived.by(() => {
		if (!doc || !rep) return [];
		return doc.allSteps.map((label, i) => {
			const m = rep.steps.filter((s) => s.i === i);
			const mark = doc!.marks[String(i)];
			if (!m.length) return { i, label, mark, m: null };
			return { i, label, mark, m: { s: Math.min(...m.map((x) => x.s)), e: Math.max(...m.map((x) => x.e)), r: m.reduce((a, x) => a + x.r, 0), w: m.reduce((a, x) => a + x.w, 0), n: m.reduce((a, x) => a + x.n, 0), k: m.length } };
		});
	});

	const topOps = (ops: Record<string, number>) => Object.entries(ops).slice(0, 5);
	const opsText = (ops: Record<string, number>) => topOps(ops).map(([o, c]) => `${opName(o)} ${c}`).join(', ');
	const itemOp = (it: Item) => (it[1] === 15 ? `SQLite ${sqlKind(it[3])}` : opName(it[1]));

	const burstGrid = (): Grid => ({
		cols: ['묶음', '시작 s', '끝 s', '주요 동작', 'Read KB', 'Write KB', '동작 줄'],
		rows: shown.map(({ b, k }) => [k + 1, b.s, b.e, opsText(b.ops), kb(b.r), kb(b.w), b.ni])
	});
	const seqGrid = (): Grid => {
		const rows: Grid['rows'] = [];
		rep!.bursts.forEach((b, k) => {
			for (const it of b.it ?? [])
				rows.push(it[1] === 15 ? [k + 1, it[0], tgt(it[2]), itemOp(it), 1, it[4], kb(it[4] * 4096)] : [k + 1, it[0], tgt(it[2]), opName(it[1]), it[3], null, kb(it[4])]);
		});
		return { cols: ['묶음', '시각 s', '대상', '동작', '횟수', 'SQLite page', '크기 KB'], rows };
	};
	const seqTitle = $derived(doc && rep ? `${doc.name} ${repNo(rep)}회차 동작 순서` : '');

	const fmtV = (v: number | number[] | null) => (Array.isArray(v) ? v.map((x) => Math.round(x)).join(' / ') : v == null ? '–' : Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(1));

	const spec = $derived(
		doc && rep
			? tcSeqSpec(
					rep.tl,
					rep.steps,
					`${doc.name} ${repNo(rep)}회차 시간 축 (${rep.tl.bin === 1 ? '1초' : rep.tl.bin + '초'} 단위 MB)`,
					`원본 측정을 함수로 바꾼 <code>wl/.private/funcs/funcs.bin</code>(<code>wl/gen_funcs.py</code>) → <code>wl/export_func_site.py</code>. TC 가 내는 동작의 바이트를 ${rep.tl.bin}초 칸마다 더했어요. Write 는 Write·buffered Write·atomic Write, SQLite 는 transaction 의 page 수 × 4KB 예요. Step 띠는 원본 측정 때 agent 가 남긴 시각이에요.`
				)
			: null
	);
</script>

<svelte:head><title>UX I/O 분석 · 시나리오 함수 TC · {doc?.name ?? id}</title></svelte:head>

<nav class="mb-4 flex flex-wrap items-center gap-1 text-body-3 text-ink-3">
	<a href={resolve('/')} class="hover:text-foreground">홈</a> ›
	<a href={resolve('/tc')} class="hover:text-foreground">TC 검증</a> ›
	<a href={resolve('/tc/func')} class="hover:text-foreground">시나리오 함수 TC</a> ›
	<span>{doc?.name ?? id}</span>
</nav>

{#if err}
	<p class="text-destructive">{err}</p>
{:else if !doc || !rep}
	<Skeleton class="h-10 w-2/3" />
	<Skeleton class="mt-4 h-40 w-full" />
	<Skeleton class="mt-4 h-80 w-full" />
{:else}
	<header class="mb-8">
		<p class="text-label-s font-semibold text-primary">시나리오 함수 TC · {doc.gk} 유형</p>
		<h1 class="mt-2 text-h1 font-bold">{doc.name}</h1>
		<p class="mt-3 max-w-[760px] text-body-2 text-muted-foreground">
			원본 측정에서 되살린 파일·DB 동작을 TC 가 같은 시각에 다시 내요. 이 페이지는 그 동작이 어떤 순서로 나가는지 보여요.
			원본 UFS 기록은 <a href={resolve('/s/[id]', { id: doc.id })} class="font-semibold text-primary">시나리오 페이지</a>에 있어요.
		</p>
		<div class="mt-3 flex items-start gap-2 rounded-xl border bg-muted px-4 py-3 text-body-3">
			<Badge variant="outline">읽는 법</Badge>
			<span>파일은 f번호, DB 는 DB번호로만 보여요. 원본 앱의 syscall 이 아니라 디스크에 닿은 I/O 를 다시 내는 TC 의 동작 순서예요.</span>
		</div>
		<div class="mt-4 flex flex-wrap items-center gap-2">
			<span class="text-label-s font-semibold text-muted-foreground">회차</span>
			<ToggleGroup.Root type="single" bind:value={repSel} variant="outline" size="sm">
				{#each doc.reps as r, k (r.seg)}<ToggleGroup.Item value={String(k)}>{repNo(r)}회차 · {sec(r.dur)}</ToggleGroup.Item>{/each}
			</ToggleGroup.Root>
		</div>
		<dl class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
			{#each [['길이', sec(rep.dur), rep.tl.bin > 1 ? `시간 축은 ${rep.tl.bin}초 칸` : ''], ['Read', `${f(rep.rMB, 1)} MB`, ''], ['Write', `${f(rep.wMB, 1)} MB`, 'SQLite 포함'], ['동작 수', n0(rep.n), `묶음 ${n0(rep.bursts.length)}개`], ['파일', `${n0(rep.files)}개`, `미리 채움 ${rep.prefill}개 · ${f(rep.prefillMB, 1)} MB`], ['SQLite DB', `${rep.dbs}개`, `transaction ${n0(rep.ops['15'] ?? 0)}번`]] as k (k[0])}
				<div class="rounded-xl bg-card px-4 py-3 ring-1 ring-border">
					<dt class="text-body-3 text-muted-foreground">{k[0]}</dt>
					<dd class="mt-1 text-h4 font-bold tabular-nums">{k[1]}</dd>
					{#if k[2]}<dd class="text-caption text-ink-3">{k[2]}</dd>{/if}
				</div>
			{/each}
		</dl>
	</header>

	<section class="mb-12 space-y-4">
		<h2 id="steps" class="text-h2 font-bold">시나리오 조작 순서</h2>
		<p class="max-w-[760px] text-body-2 text-muted-foreground">원본을 잴 때 폰에서 한 step 이에요. TC 에 들어가는 것은 측정 구간(굵은 줄)뿐이에요. 시각은 측정 시작부터 센 초예요. Read·Write·request 는 원본 UFS 기록 값이라 f2fs 가 더한 Write 도 들어 있어서 위 Write 와 다를 수 있어요.</p>
		<CopyTable title="{doc.name} {repNo(rep)}회차 조작 순서" note="반복하는 step 은 처음부터 마지막 반복까지의 구간과 합계를 보여요.">
			<table>
				<thead><tr><th class="num">#</th><th>Step</th><th class="num">시각 s</th><th class="num">Read MB</th><th class="num">Write MB</th><th class="num">request</th></tr></thead>
				<tbody>
					{#each stepRows as s (s.i)}
						{#if s.m}
							<tr class="font-semibold">
								<td class="num">{s.i + 1}</td>
								<td>{s.label}{#if s.m.k > 1}<span class="rg">×{s.m.k}</span>{/if}</td>
								<td class="num">{f(s.m.s, 1)} ~ {f(s.m.e, 1)}</td>
								<td class="num" data-v={s.m.r}>{f(s.m.r, 1)}</td>
								<td class="num" data-v={s.m.w}>{f(s.m.w, 1)}</td>
								<td class="num" data-v={s.m.n}>{n0(s.m.n)}</td>
							</tr>
						{:else}
							<tr class="text-ink-3">
								<td class="num">{s.i + 1}</td>
								<td>{s.label}</td>
								<td class="num" colspan="4">{s.mark === 'trace_start' ? '여기서 측정 시작' : s.mark === 'trace_stop' ? '여기서 측정 끝' : '측정 밖'}</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</CopyTable>
	</section>

	<section class="mb-12 space-y-4">
		<h2 id="timeline" class="text-h2 font-bold">시간 축</h2>
		<p class="max-w-[760px] text-body-2 text-muted-foreground">
			{rep.tl.bin === 1 ? '1초' : `${rep.tl.bin}초`} 칸마다 TC 가 내는 Read·Write 양이에요{rep.tl.bin > 1 ? '. 10분이 넘는 함수라 10초 칸으로 묶었어요' : ''}. 가운데 줄은 fsync 와 SQLite transaction 수, 아래 띠는 측정 구간의 step 이에요. 차트 위에서 스크롤하거나 아래 막대를 끌어 확대해요.
		</p>
		{#if spec}<Chart {spec} height={380} renderer={rep.tl.r.length > 600 ? 'canvas' : 'svg'} />{/if}
	</section>

	<section class="mb-12 space-y-4">
		<h2 id="bursts" class="text-h2 font-bold">I/O 묶음과 동작 순서</h2>
		<p class="max-w-[760px] text-body-2 text-muted-foreground">
			{doc.gap}초 넘게 쉬면 묶음을 끊어요. 줄을 누르면 그 묶음의 동작이 순서대로 펼쳐져요. 같은 파일에 같은 동작이 {Math.round(doc.fold * 1000)}ms 안에 이어지면 한 줄로 접어요. SQLite transaction 은 접지 않아요.
		</p>
		<CopyTable
			title="{doc.name} {repNo(rep)}회차 I/O 묶음"
			grid={burstGrid}
			note={rep.itemsUpTo != null ? `파일 크기 때문에 동작 줄은 앞 ${rep.itemsUpTo}개 묶음까지만 실었어요. 그 뒤 묶음은 동작 수와 양만 보여요.` : ''}
		>
			{#snippet actions()}
				<Button variant="quiet" size="xs" onclick={() => copyGrid(seqGrid(), seqTitle, '동작 순서')} title="이 회차의 동작 줄 전체(시각, 대상, 동작, 횟수, 크기)를 Confluence 에 붙여넣을 표로 복사"><ListOrdered />Copy sequence</Button>
				<Button variant="quiet" size="xs" onclick={() => saveCSV(seqGrid(), seqTitle)} title="동작 줄 전체를 UTF-8 CSV 로 저장"><Download />Sequence CSV</Button>
			{/snippet}
			<table>
				<thead><tr><th class="num">묶음</th><th class="num">시각 s</th><th>주요 동작</th><th class="num">Read</th><th class="num">Write</th></tr></thead>
				<tbody>
					{#each shown.slice(0, limit) as { b, k } (k)}
						{@const isOpen = open.has(k)}
						<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
						<tr class="brow" class:open={isOpen} onclick={() => b.it && toggle(k)}>
							<td class="num">
								{#if b.it}
									<button type="button" class="exp" aria-expanded={isOpen} aria-label="{k + 1}번 묶음 동작 {isOpen ? '접기' : '펼치기'}"><ChevronRight class="size-3.5" />{k + 1}</button>
								{:else}{k + 1}{/if}
							</td>
							<td class="num">{f(b.s, 1)} ~ {f(b.e, 1)}</td>
							<td><span class="ops">{#each topOps(b.ops) as [o, c] (o)}<span class="tone-{opTone(+o)}">{opName(o)} {c}</span>{/each}</span></td>
							<td class="num">{size(b.r)}</td>
							<td class="num">{size(b.w)}</td>
						</tr>
						{#if isOpen && b.it}
							<tr class="seq">
								<td colspan="5">
									<ol>
										{#each b.it as it, j (j)}
											<li class="tone-{opTone(it[1])}">
												<span class="t">{it[0].toFixed(3)}</span>
												<span class="tg">{tgt(it[2])}</span>
												{#if it[1] === 15}
													<span class="op"><span class="chip">SQLite</span>{sqlKind(it[3])}</span>
													<span class="sz">page {it[4]}</span>
												{:else}
													<span class="op">{opName(it[1])}{#if it[3] > 1}<span class="rg">×{it[3]}</span>{/if}</span>
													<span class="sz">{size(it[4])}</span>
												{/if}
											</li>
										{/each}
									</ol>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</CopyTable>
		<div class="flex flex-wrap gap-2">
			{#if nSmall}<Button variant="secondary" size="sm" onclick={() => (showAll = !showAll)}>{showAll ? '큰 묶음만 보기' : `작은 묶음 ${n0(nSmall)}개도 보기`}</Button>{/if}
			{#if shown.length > limit}<Button variant="secondary" size="sm" onclick={() => (limit += 300)}>묶음 더 보기 ({n0(shown.length - limit)}개 남음)</Button>{/if}
		</div>
		<p class="text-body-3 text-ink-3">작은 묶음은 100KB 아래이고 동작 줄이 6개보다 적은 묶음이에요. Copy table 은 지금 보이는 묶음 목록을, Copy sequence 는 이 회차의 동작 줄 전체를 복사해요.</p>
	</section>

	<section class="mb-12 space-y-4">
		<h2 id="compare" class="text-h2 font-bold">원본과 TC 비교</h2>
		{#if doc.checks.length}
			<p class="max-w-[760px] text-body-2 text-muted-foreground">
				이 함수만 따로 돌린 결과예요 ({doc.reps[doc.checkRep ?? 0] ? repNo(doc.reps[doc.checkRep ?? 0]) : 1}회차, {doc.pass}/{doc.of} 통과). 다른 회차는 가중치 TC 안에서 비교해요.
			</p>
			<CopyTable title="{doc.name} 원본과 TC" note="Volume 은 MB, 분포 항목(Request size, Sequential, Inter-arrival)은 칸별 %예요. 원본 값이 아주 작은 항목은 판정하지 않아요.">
				<table>
					<thead><tr><th>지표</th><th class="num">원본</th><th class="num">TC</th><th>판정</th></tr></thead>
					<tbody>
						{#each doc.checks as c (c.k)}
							<tr>
								<td class="whitespace-nowrap">{c.k}</td>
								<td class="num">{fmtV(c.o)}</td>
								<td class="num">{fmtV(c.t)}</td>
								<td>{#if c.ok === true}<Badge variant="secondary">통과</Badge>{:else if c.ok === false}<Badge variant="destructive">미달</Badge>{:else}<span class="text-ink-3">판정 안 함</span>{/if}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</CopyTable>
		{:else}
			<p class="text-body-2 text-muted-foreground">이 함수의 단독 결과가 아직 없어요.</p>
		{/if}
	</section>

	<nav class="border-t pt-6">
		<a href={resolve('/tc/func')} class="text-label-s font-semibold text-primary">시나리오 함수 TC 목록으로</a>
	</nav>
{/if}

<style>
	.brow {
		cursor: pointer;
	}
	.exp {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		font-variant-numeric: tabular-nums;
		color: var(--foreground);
	}
	.exp :global(svg) {
		transition: transform 0.15s;
		color: var(--ink-3);
	}
	.exp[aria-expanded='true'] :global(svg) {
		transform: rotate(90deg);
	}
	.exp:focus-visible {
		outline: 2px solid var(--primary);
		outline-offset: 2px;
		border-radius: 4px;
	}
	.ops {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 10px;
		color: var(--muted-foreground);
	}
	.ops > span {
		white-space: nowrap;
	}
	.ops > span::before,
	.seq li::before {
		content: '';
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 2px;
		margin-right: 5px;
		vertical-align: 0;
		background: var(--tone);
	}
	.tone-r { --tone: var(--read); }
	.tone-w { --tone: var(--write); }
	.tone-wd { --tone: var(--wd); }
	.tone-db { --tone: var(--db); }
	.tone-m { --tone: var(--line-strong); }
	:global(.ux-table) tr.seq td {
		background: var(--background);
		padding: 8px 12px 12px;
	}
	.seq ol {
		margin: 0;
		padding: 0;
		list-style: none;
		/* 좁은 화면에서 표가 옆으로 넘쳐도 동작 줄은 화면 폭 안에 (크기 칸이 잘리지 않게) */
		position: sticky;
		left: 0;
		max-width: min(100%, calc(100vw - 64px));
		max-height: 420px;
		overflow: auto;
		font-size: 12px;
	}
	.seq li {
		display: grid;
		grid-template-columns: 12px 64px 52px minmax(0, 1fr) auto;
		align-items: baseline;
		gap: 8px;
		padding: 2px 0;
		border-bottom: 1px dashed var(--border);
	}
	.seq li::before {
		margin: 0;
		align-self: center;
	}
	.seq li:last-child {
		border-bottom: 0;
	}
	.seq .t,
	.seq .tg,
	.seq .sz {
		font-family: var(--font-mono, ui-monospace, monospace);
		font-variant-numeric: tabular-nums;
		color: var(--ink-3);
	}
	.seq .sz {
		text-align: right;
		white-space: nowrap;
	}
	.seq .op {
		overflow-wrap: anywhere;
	}
	.chip {
		display: inline-block;
		margin-right: 6px;
		padding: 0 6px;
		border-radius: 999px;
		background: color-mix(in srgb, var(--db) 16%, transparent);
		color: var(--db);
		font-weight: 600;
		font-size: 11px;
	}
	.rg {
		color: var(--ink-3);
		margin-left: 4px;
	}
</style>
