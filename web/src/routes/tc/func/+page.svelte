<script lang="ts">
	// 시나리오 함수 TC 검증: 시나리오 = 함수, 함수를 유형으로 묶고 유형 가중치로 TC 하나를 돌림 (tcfunc.json, wl/export_func_site.py)
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import Chart from '#lib/components/Chart.svelte';
	import CopyTable from '#lib/components/CopyTable.svelte';
	import { groupBarSpec } from '#lib/charts/build.js';
	import { load } from '#lib/data.js';
	import { f } from '#lib/fmt.js';

	type Fail = { k: string; o: string; t: string };
	type Struct = { name: string; reps: number; dur: number; files: number; rmb: number; wmb: number; R: number; W: number; WD: number; FS: number; UN: number; AW: number; SQL: number; db: number };
	type Func = { id: string; g: string; gk: string; w: number; p: number; n: number; fails: Fail[]; pad: number | null; prev: string[]; s: Struct };
	type Tl = { t: number; d: number; g: string; f: string; nm: string; rep: string; p: number | null; n: number | null };
	type Mix = {
		name: string; label: string; weight: string; seed: number; dur: number; n: number;
		target: Record<string, number>; actual: Record<string, number>;
		ip: number; io: number; solo: number; tp: number; to: number; late: number; req: number | null; warms: number | null; errs: number;
		cats: Record<string, [number, number]>; fail: Record<string, number>; total: { k: string; o: string; t: string; ok: boolean | null }[];
		comp: Record<string, [string, number, number][]>; tl: Tl[];
	};
	type Doc = {
		funcs: Func[]; groups: { g: string; gk: string; nf: number; p: number; n: number }[]; mixes: Mix[];
		checkcmp: { k: string; solo: number; mix: number; lo: number; hi: number }[]; cmp: string[]; groupKo: Record<string, string>; groupColor: Record<string, number>;
		allp: number; alln: number; padPct: number;
	};

	let doc = $state<Doc | null>(null);
	let err = $state('');
	onMount(() => {
		load<Doc>('tcfunc')
			.then((d) => (doc = d))
			.catch(() => (err = '시나리오 함수 TC 데이터를 불러오지 못했어요.'));
	});

	let fsel = $state('all');
	let ssel = $state('all');
	let tip = $state<{ x: number; y: number; it: Tl } | null>(null);

	const pct = (p: number, n: number) => (n ? (p / n) * 100 : 0);
	const mix = (name: string) => doc!.mixes.find((m) => m.name === name);
	const col = (g: string) => (doc!.groupColor[g] !== undefined ? `var(--tg${doc!.groupColor[g]})` : 'var(--ink-4)');
	const usedGroups = $derived(
		doc ? [...new Set(doc.mixes.flatMap((m) => Object.keys(m.target)))].sort((a, b) => doc!.groupColor[a] - doc!.groupColor[b]) : []
	);
	const sortedGroups = $derived(doc ? doc.groups.slice().sort((a, b) => b.p / b.n - a.p / a.n) : []);

	const groupSpec = $derived(
		doc
			? groupBarSpec(
					'유형별 판정 통과율, 함수 단독 (%)',
					sortedGroups.map((g) => `${g.gk} (${g.nf})`),
					[{ name: '통과', vals: sortedGroups.map((g) => +pct(g.p, g.n).toFixed(1)) }],
					'함수마다 회차 1을 재생하고 <code>wl/metrics.py</code> 의 <code>judge</code> 로 원본 회차와 판정했어요. 유형 안 함수의 통과 항목 수를 더해 판정 항목 수로 나눴어요. 괄호는 함수 수예요.',
					(t) => [t.ramp[3]]
				)
			: null
	);
	// 유형 비중 오차: 모든 가중치 TC 의 유형별 |실제 - 목표| 최댓값 (%p)
	const shareErr = $derived(
		doc ? Math.max(...doc.mixes.flatMap((m) => Object.keys(m.target).map((g) => Math.abs((m.actual[g] ?? 0) - m.target[g])))) : 0
	);
	const cc = (k: string) => doc!.checkcmp.find((c) => c.k === k);
	const tot = (m: Mix | undefined, k: string) => m?.total.find((x) => x.k === k);
	const solofail = (id: string, k: string) => doc!.funcs.find((x) => x.id === id)?.fails.find((x) => x.k === k);
	const cmpRows = $derived(doc ? doc.checkcmp.filter((c) => c.mix + c.solo > 0) : []);
	const cmpSpec = $derived(
		doc
			? groupBarSpec(
					'항목별 판정 실패율: 함수 단독 vs 가중치 TC (%)',
					cmpRows.map((c) => c.k),
					[
						{ name: '함수 단독', vals: cmpRows.map((c) => c.solo) },
						{ name: '가중치 TC', vals: cmpRows.map((c) => c.mix) }
					],
					`가장 최근 가중치 TC 두 벌(${doc.cmp.join(', ')})의 함수 구간마다 틀린 항목을 셌어요. 함수 단독은 같은 구간 목록에 그 함수를 혼자 돌렸을 때의 판정을 넣어 셌어요.`,
					(t) => [t.mute, t.ramp[3]]
				)
			: null
	);
</script>

<svelte:head><title>UX I/O 분석 · 시나리오 함수 TC</title></svelte:head>

<nav class="mb-4 text-body-3 text-ink-3"><a href={resolve('/')} class="hover:text-foreground">홈</a> › <a href={resolve('/tc')} class="hover:text-foreground">TC 검증</a> › 시나리오 함수 TC</nav>

{#if err}
	<p class="text-destructive">{err}</p>
{:else if !doc}
	<Skeleton class="h-10 w-2/3" />
	<Skeleton class="mt-4 h-40 w-full" />
	<Skeleton class="mt-4 h-80 w-full" />
{:else}
	{@const m1w = mix('m1w')}
	{@const m2w = mix('m2w')}
	{@const m1 = mix('m1')}
	{@const m2 = mix('m2')}
	{@const m2d = mix('m2d')}
		{@const m1f = mix('m1f')}
		{@const m2f = mix('m2f')}
		{@const m1h = mix('m1h')}
		{@const m2h = mix('m2h')}
		{@const m2i = mix('m2i')}
		{@const late = [m1h, m2i].filter((m) => m !== undefined)}
		{@const fl = cc('Flush/s')}
		{@const qd = cc('QD p99')}
		{@const fw = cc('FS Write')}
		{@const ck = cc('Checkpoint/s')}
		{@const s3 = solofail('S3', 'FS Write')}
		{#snippet mixCard(m: Mix)}
				{@const total = m.tl.length ? m.tl[m.tl.length - 1].t + m.tl[m.tl.length - 1].d : m.dur}
				<div class="mixcard">
					<h3 class="text-h4 font-bold">{m.name} <span class="text-body-3 font-normal text-ink-3">{m.label} · seed {m.seed} · 함수 {m.n}번 · {f(m.dur / 60, 0)}분</span></h3>
					<p class="text-body-3 text-ink-3"><code>--weight {m.weight}</code></p>
					<div class="strip" role="img" aria-label="{m.name} 실행 순서">
						{#each m.tl as x, i (i)}
							<div
								style="flex:{x.d} 0 0;background:{col(x.g)}"
								onmousemove={(e) => (tip = { x: e.clientX, y: e.clientY, it: x })}
								onmouseleave={() => (tip = null)}
								role="presentation"
							></div>
						{/each}
					</div>
					<div class="axis"><span>0분</span><span>{f(total / 120, 0)}분</span><span>{f(total / 60, 0)}분</span></div>
					<div class="prose-ux"><div class="stats">
						<div><b>{f(pct(m.ip, m.io), 1)}%</b><span>구간별 통과 {m.ip}/{m.io} (같은 함수 단독 {f(m.solo, 1)}%, 지금의 함수 단독 결과 기준)</span></div>
						<div><b>{m.tp}/{m.to}</b><span>전체 지표 통과</span></div>
						<div><b>{m.late}</b><span>늦은 request (&gt;5ms){m.req ? `, ${m.req.toLocaleString()}개 중` : ''}</span></div>
						<div><b>{m.warms ?? '없음'}</b><span>DB warm-up 횟수</span></div>
							<div><b>{m.errs}</b><span>재생 오류 수</span></div>
					</div></div>
					<div class="mixgrid">
						<CopyTable title="{m.name} 유형 비중과 유형별 판정" note="실제 비중은 함수 실행 시간 기준이에요(쉬는 20초 제외). 판정은 그 유형 구간을 모두 합쳐 낸 통과 지표 수예요.">
							<table>
								<thead><tr><th>유형</th><th class="num">목표 %</th><th class="num">실제 %</th><th class="num">판정</th></tr></thead>
								<tbody>
									{#each Object.keys(m.target).sort((a, b) => m.target[b] - m.target[a]) as g (g)}
										<tr><td class="whitespace-nowrap"><i class="sw" style="background:{col(g)}"></i>{doc!.groupKo[g]}</td><td class="num">{m.target[g]}</td><td class="num">{m.actual[g]}</td><td class="num">{m.cats[g] ? `${m.cats[g][0]}/${m.cats[g][1]}` : '–'}</td></tr>
									{/each}
								</tbody>
							</table>
						</CopyTable>
						<CopyTable title="{m.name} 전체 지표" note="TC 2시간 전체를 TC에 쓴 원본 회차의 합과 비교했어요.">
							<table>
								<thead><tr><th>지표</th><th class="num">원본</th><th class="num">TC</th><th>판정</th></tr></thead>
								<tbody>
									{#each m.total.filter((x) => x.ok != null) as x (x.k)}
										<tr><td class="whitespace-nowrap">{x.k}</td><td class="num">{x.o}</td><td class="num">{x.t}</td><td>{#if x.ok}<Badge variant="secondary">통과</Badge>{:else}<Badge variant="destructive">미달</Badge>{/if}</td></tr>
									{/each}
								</tbody>
							</table>
						</CopyTable>
					</div>
					<details class="mt-2">
						<summary class="cursor-pointer text-body-3 text-primary">들어간 함수 (실행 횟수, 분)</summary>
						<CopyTable title="{m.name} 구성" note="함수마다 원본 3회차 중 하나를 골라 실행해요.">
							<table>
								<thead><tr><th>함수</th><th class="num">횟수</th><th class="num">분</th></tr></thead>
								<tbody>
									{#each Object.entries(m.comp).sort((a, b) => (m.target[b[0]] ?? 0) - (m.target[a[0]] ?? 0)) as [g, fs] (g)}
										<tr class="grp"><td colspan="3">{doc!.groupKo[g]}</td></tr>
										{#each fs as [nm, n, mins] (nm)}<tr><td class="whitespace-nowrap">{nm}</td><td class="num">{n}</td><td class="num">{mins}</td></tr>{/each}
									{/each}
								</tbody>
							</table>
						</CopyTable>
					</details>
				</div>
		{/snippet}
	<div class="tcf">
		<header class="mb-8">
			<p class="text-label-s font-semibold text-primary">UFS workload TC · 검증 중 · 2026-11-08</p>
			<h1 class="mt-2 text-h1 font-bold">시나리오 함수 TC</h1>
			<p class="mt-3 max-w-[760px] text-body-2 text-muted-foreground">
				측정한 시나리오 하나를 함수 하나로 두고, 함수를 유형으로 묶고, 실행할 때 유형 가중치를 줘서 TC 하나 안에서 돌리는 구조예요. 함수 61개를 하나씩 원본과 비교하고,
				2시간 가중치 TC 두 벌(m1, m2)을 고칠 때마다 같은 seed로 다시 돌렸어요. 원본 61개는 2026-11-07에 고친 수집 도구로 모두 다시 쟀어요. <a href={resolve('/tc')} class="text-primary">TC 검증</a>의 하루 TC와 달리 사용 로그 데이터셋을 쓰지 않아요.
			</p>
			<div class="mt-3 flex flex-wrap gap-2">
				<Badge variant="secondary">함수 61개 · 유형 13개</Badge>
				<Badge variant="secondary">DB는 실제 SQLite</Badge>
				<Badge variant="secondary">f2fs Checkpoint는 f2fs에 맡김</Badge>
				<Badge variant="secondary">배터리 · 무선 adb</Badge>
			</div>
		</header>

		<section class="mb-12 space-y-4">
			<h2 id="summary" class="text-h2 font-bold">Summary</h2>
			<div class="prose-ux summary">
				<div class="stats">
					<div><b>{f(pct(doc.allp, doc.alln), 0)}%</b><span>함수 단독 판정 통과 ({doc.allp}/{doc.alln})</span></div>
					{#if m1h}<div><b>{f(pct(m1h.ip, m1h.io), 1)}%</b><span>가중치 TC m1h 구간별 통과 ({m1h.ip}/{m1h.io}), 전체 {m1h.tp}/{m1h.to}</span></div>{/if}
						{#if m2i}<div><b>{f(pct(m2i.ip, m2i.io), 1)}%</b><span>가중치 TC m2i 구간별 통과 ({m2i.ip}/{m2i.io}), 전체 {m2i.tp}/{m2i.to}</span></div>{/if}
						<div><b>±{f(shareErr, 1)}%p</b><span>유형 비중 오차 (가중치 TC {doc.mixes.length}번 중 최대)</span></div>
				</div>
				<ul class="points">
					<li><b>함수 하나씩 돌리면 판정 항목의 {f(pct(doc.allp, doc.alln), 0)}%를 통과해요.</b> {sortedGroups[0].gk}·{sortedGroups[1].gk}·{sortedGroups[2].gk}는 {f(pct(sortedGroups[2].p, sortedGroups[2].n), 0)}~{f(pct(sortedGroups[0].p, sortedGroups[0].n), 0)}%, 대기·홈은 가장 낮아요.</li>
					{#if late.length}
							{@const gaps = late.map((m) => m.solo - pct(m.ip, m.io))}
							<li><b>가중치 TC는 유형 비중이 목표의 ±{f(shareErr, 1)}%p 안에 들어와요.</b> 최근 구간별 통과({late.map((m) => m.name).join(', ')})는 같은 함수를 혼자 돌릴 때보다 {f(Math.min(...gaps), 1)}~{f(Math.max(...gaps), 1)}%p 낮아요.</li>
						{/if}
						{#if m1w && m1f && m1h && m2i}
							<li><b>fdatasync도 fsync flag로 잡게 수집 도구를 고치고 원본을 다시 쟀어요.</b> m1 구간별 통과가 {f(pct(m1w.ip, m1w.io), 1)} → {f(pct(m1f.ip, m1f.io), 1)}%, 전체 지표가 {m1w.tp}/{m1w.to} → {m1f.tp}/{m1f.to}로 올랐어요. 그 뒤 direct Write와 Read 재생을 고쳐 전체 지표가 m1h {m1h.tp}/{m1h.to}, m2i {m2i.tp}/{m2i.to}예요.</li>
						{/if}
					{#if m1 && m1w && m2 && m2w}
						<li><b>가중치 TC에서 DB page cache가 식어 Read가 원본보다 많던 문제를 고쳤어요.</b> 구간별 통과가 m1 {f(pct(m1.ip, m1.io), 1)} → {f(pct(m1w.ip, m1w.io), 1)}%, m2 {f(pct(m2.ip, m2.io), 1)} → {f(pct(m2w.ip, m2w.io), 1)}%로 올랐어요.</li>
					{/if}
					{#if m2w && m2d}
						<li><b>원본 앱의 폴더 구조와 cold start 시나리오의 sync step을 재생에 넣었어요.</b> m2 구간별 통과가 {f(pct(m2w.ip, m2w.io), 1)} → {f(pct(m2d.ip, m2d.io), 1)}%로 올랐고, 구간 FS Write 실패가 {m2w.fail.fsWriteMB}% → {m2d.fail.fsWriteMB}%로 줄었어요. 대신 2시간 전체의 Sequential Write가 원본보다 낮아졌어요.</li>
					{/if}
					<li><b>DB I/O는 앱 DB와 같은 구조의 SQLite 테이블로 내요.</b> 행 동작만으로는 양이 모자라 WAL frame의 {doc.padPct}%는 채움 테이블로 채웠어요.</li>
					<li><b>남은 차이는 주로 f2fs가 정하는 쪽이에요.</b> FS-induced Write, Checkpoint/s, Flush/s예요. f2fs Checkpoint를 원본 시각에 일으키지 않아서, 대기 함수에서 차이가 가장 커요.</li>
				</ul>
			</div>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="structure" class="text-h2 font-bold">TC 구조</h2>
			<div class="flow">
				<div><b>원본 trace</b>61개 시나리오 × 3회차</div>
				<div><b>함수 61개</b>회차마다 request 단위 동작 목록</div>
				<div><b>유형 13개</b>유형 안 함수 비중</div>
				<div><b>실행 가중치</b><code>--weight sns=0.4,…</code></div>
				<div><b>재생과 비교</b>함수 구간마다 원본과 판정</div>
			</div>
			<div class="prose-ux">
				<ul class="points">
					<li><b>함수:</b> 원본 3회차를 각각 동작 목록(시각, 파일, offset, 크기, fsync, unlink, atomic write, SQL)으로 바꾼 거예요. 요약 파라미터 없이 그대로 재생해요.</li>
					<li><b>순서:</b> 목표 비중보다 가장 모자란 유형에서 다음 함수를 고르고, 함수는 끝까지 돌려요. 함수 사이에 20초 쉬어요. 같은 seed면 순서가 같아요.</li>
					<li><b>DB I/O:</b> DB 파일 Write는 request로 재생하지 않고, 앱 DB와 같은 구조의 테이블에 INSERT·UPDATE·DELETE를 내요. 비율은 앱 DB에서 잰 값이고 행 값은 가짜예요. WAL frame 수를 재며 원본 양에 맞추고, 모자라면 채움 테이블로 채워요. DB Checkpoint는 원본이 DB 본체에 쓴 양만큼일 때만 해요.</li>
					<li><b>f2fs Checkpoint:</b> 하루 TC는 원본 시각에 Checkpoint를 일으켰는데, 이 TC는 f2fs가 정하게 둬요.</li>
					<li><b>개인정보:</b> 앱 DB의 행 내용은 기기 밖으로 나가지 않아요. 테이블 구조와 SQL은 공개하지 않아요.</li>
				</ul>
			</div>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="funcs" class="text-h2 font-bold">시나리오 함수 구조</h2>
			<p class="max-w-[760px] text-body-2 text-muted-foreground">
				함수마다 회차 하나의 평균이에요. W MB는 파일 동작으로 재생하는 Write예요. DB Write는 SQL 묶음으로 바뀌어 빠져 있어요.
			</p>
			<div class="chips" role="group" aria-label="유형 거르기">
				<button type="button" class="chip" aria-pressed={fsel === 'all'} onclick={() => (fsel = 'all')}>전체</button>
				{#each doc.groups as g (g.g)}<button type="button" class="chip" aria-pressed={fsel === g.g} onclick={() => (fsel = g.g)}>{g.gk}</button>{/each}
			</div>
			<CopyTable title="함수 구조 (회차 평균)" note="W = buffered Write, WD = direct Write, AW = atomic write(F2FS atomic commit, Write 후 rename), SQL = DB Write 묶음 수(transaction 몇 개 또는 checkpoint 하나), DB = 앱 DB와 같은 테이블 구조로 만든 DB 수예요.">
				<table>
					<thead><tr><th>함수</th><th class="num">길이 s</th><th class="num">파일</th><th class="num">Read MB</th><th class="num">Write MB</th><th class="num">Read</th><th class="num">W</th><th class="num">WD</th><th class="num">fsync</th><th class="num">unlink</th><th class="num">AW</th><th class="num">SQL</th><th class="num">DB</th><th class="num">회차</th></tr></thead>
					<tbody>
						{#each doc.groups.filter((g) => fsel === 'all' || g.g === fsel) as g (g.g)}
							<tr class="grp"><td colspan="14">{g.gk}</td></tr>
							{#each doc.funcs.filter((x) => x.g === g.g) as x (x.id)}
								{@const s = x.s}
								<tr><td class="whitespace-nowrap"><a href={resolve('/s/[id]', { id: x.id })} class="hover:text-primary">{s.name}</a></td><td class="num">{s.dur}</td><td class="num">{s.files}</td><td class="num">{s.rmb}</td><td class="num">{s.wmb}</td><td class="num">{s.R}</td><td class="num">{s.W}</td><td class="num">{s.WD}</td><td class="num">{s.FS}</td><td class="num">{s.UN}</td><td class="num">{s.AW}</td><td class="num">{s.SQL}</td><td class="num">{s.db}</td><td class="num">{s.reps}</td></tr>
							{/each}
						{/each}
					</tbody>
				</table>
			</CopyTable>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="solo" class="text-h2 font-bold">함수 단독 결과</h2>
			<p class="max-w-[760px] text-body-2 text-muted-foreground">
				함수 하나씩 회차 1을 재생하고, 하루 TC와 같은 기준으로 원본과 판정했어요. 함수마다 판정 항목은 11~16개예요. 원본 값이 아주 작은 항목은 판정하지 않아요. 모두 2026-11-07~08에 다시 잰 원본과 비교한 값이에요.
			</p>
			{#if groupSpec}<Chart spec={groupSpec} height={doc.groups.length * 32 + 70} />{/if}
			<div class="chips" role="group" aria-label="유형 거르기">
				<button type="button" class="chip" aria-pressed={ssel === 'all'} onclick={() => (ssel = 'all')}>전체</button>
				{#each doc.groups as g (g.g)}<button type="button" class="chip" aria-pressed={ssel === g.g} onclick={() => (ssel = g.g)}>{g.gk}</button>{/each}
			</div>
			<CopyTable title="함수별 판정" note="틀린 항목은 '원본 → TC' 값이에요. 분포 항목은 칸별 %예요. 채움 = DB WAL frame 중 채움 테이블 몫. 이전 Run = 같은 함수를 앞 build로 잰 값으로, Run 사이 흔들림(함수마다 1~3개)을 가늠하는 데 써요.">
				<table>
					<thead><tr><th>함수</th><th class="num">통과</th><th class="num">%</th><th class="num">이전 Run</th><th class="num">채움</th><th>틀린 항목 (원본 → TC)</th></tr></thead>
					<tbody>
						{#each doc.groups.filter((g) => ssel === 'all' || g.g === ssel) as g (g.g)}
							<tr class="grp"><td colspan="6">{g.gk} · {g.p}/{g.n}</td></tr>
							{#each doc.funcs.filter((x) => x.g === g.g) as x (x.id)}
								{@const r = x.p / x.n}
								<tr>
									<td class="whitespace-nowrap">{x.s.name}</td>
									<td class="num">{x.p}/{x.n}</td>
									<td class="num"><span class="pill" class:ok={r >= 0.85} class:ng={r < 0.7}>{f(r * 100, 0)}</span></td>
									<td class="num whitespace-nowrap text-ink-3">{x.prev.join(' · ') || '–'}</td>
									<td class="num">{x.pad == null ? '–' : x.pad + '%'}</td>
									<td class="fails">{#each x.fails as k (k.k)}<span>{k.k} <em>{k.o} → {k.t}</em></span>{:else}없음{/each}</td>
								</tr>
							{/each}
						{/each}
					</tbody>
				</table>
			</CopyTable>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="mix" class="text-h2 font-bold">가중치 TC</h2>
			<p class="max-w-[760px] text-body-2 text-muted-foreground">
				2시간 TC 두 벌(m1, m2)을 고칠 때마다 같은 seed로 한 번씩 돌렸어요. 같은 seed면 실행 순서가 같아요. 가장 최근 두 벌을 먼저 보이고, 앞 Run은 아래 기록 표와 접힌 칸에 있어요. 막대에 마우스를 올리면 함수, 회차, 그 구간 판정이 보여요.
			</p>
			<div class="legend">{#each usedGroups as g (g)}<span><i style="background:{col(g)}"></i>{doc.groupKo[g]}</span>{/each}</div>
			{#each doc.mixes.filter((m) => doc!.cmp.includes(m.name)) as m (m.name)}{@render mixCard(m)}{/each}
			<CopyTable title="가중치 TC 기록" note="같은 가중치·seed로 고칠 때마다 다시 돌린 Run이에요. m1f·m2f부터는 다시 잰 원본과 비교했어요. 재생 오류는 대부분 atomic write 중 direct Read 거절이에요.">
				<table>
					<thead><tr><th>TC</th><th>바꾼 것</th><th class="num">구간별 통과</th><th class="num">%</th><th class="num">전체 지표</th><th class="num">늦은 request</th><th class="num">재생 오류</th></tr></thead>
					<tbody>
						{#each doc.mixes as m (m.name)}<tr><td>{m.name}</td><td class="whitespace-nowrap">{m.label}</td><td class="num">{m.ip}/{m.io}</td><td class="num">{f(pct(m.ip, m.io), 1)}</td><td class="num">{m.tp}/{m.to}</td><td class="num">{m.late.toLocaleString()}</td><td class="num">{m.errs}</td></tr>{/each}
					</tbody>
				</table>
			</CopyTable>
			<details>
				<summary class="cursor-pointer text-body-2 text-primary">이전 가중치 TC {doc.mixes.length - doc.cmp.length}개 (최근 것부터)</summary>
				<div class="mt-4 grid gap-4">{#each doc.mixes.filter((m) => !doc!.cmp.includes(m.name)).reverse() as m (m.name)}{@render mixCard(m)}{/each}</div>
			</details>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="cmp" class="text-h2 font-bold">단독과 가중치 비교</h2>
			<p class="max-w-[760px] text-body-2 text-muted-foreground">가장 최근 가중치 TC 두 벌({doc.cmp.join(', ')})의 함수 구간에서 항목마다 틀린 비율이에요. 괄호는 틀린 구간 중 TC가 원본보다 적은 수와 많은 수예요.</p>
			{#if cmpSpec}<Chart spec={cmpSpec} height={cmpRows.length * 40 + 70} />{/if}
			<div class="prose-ux">
				<ul class="points">
						{#if fl}<li><b>Flush/s</b>는 가중치 TC에서 더 자주 틀리고(단독 {fl.solo}%, 가중치 {fl.mix}%), 틀린 구간은 거의 다 TC가 많아요(적음 {fl.lo}, 많음 {fl.hi}). 원인은 아직 확인하지 않았어요.</li>{/if}
						{#if qd}<li><b>QD p99</b>도 가중치 TC에서 더 자주 틀려요(단독 {qd.solo}%, 가중치 {qd.mix}%). 원본보다 높은 구간과 낮은 구간이 섞여 있어요(적음 {qd.lo}, 많음 {qd.hi}). 같은 시나리오 원본끼리도 많이 흔들리는 항목이에요.</li>{/if}
						{#if fw}<li><b>FS-induced Write</b>는 가장 자주 틀리는 항목이에요(단독 {fw.solo}%, 가중치 {fw.mix}%). 원본보다 많은 구간과 적은 구간이 섞여 있어요(적음 {fw.lo}, 많음 {fw.hi}).</li>{/if}
						{#if ck}<li><b>Checkpoint/s</b>는 단독 {ck.solo}%, 가중치 {ck.mix}%로 비슷하게 틀려요(적음 {ck.lo}, 많음 {ck.hi}).</li>{/if}
				</ul>
			</div>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="fixes" class="text-h2 font-bold">검증하며 고친 것</h2>
			<CopyTable title="고친 것" note="효과는 같은 함수·같은 seed로 고치기 전후를 견준 값이에요.">
				<table>
					<thead><tr><th>문제</th><th>원인</th><th>고친 방법</th><th>효과</th></tr></thead>
					<tbody>
						<tr><td>실제 테이블 행 동작만으로 DB Write 양이 안 맞음</td><td>행 크기와 page 재사용이 앱과 달라요</td><td>WAL frame을 재며 작은 transaction을 반복하고, 모자라면 채움 테이블</td><td>Instagram 홈 피드 DB 본체/WAL 14.6/25.9MB (원본 14.5/22.6)</td></tr>
						<tr><td>DB 본체 Write가 원본의 몇 배</td><td>WAL 전체를 Checkpoint</td><td>원본 본체 page 수만큼일 때만 PASSIVE Checkpoint</td><td>YouTube 영상 3분 4.3 → 0.9MB (원본 0.3)</td></tr>
						<tr><td>캘린더 Write가 원본의 9배</td><td>재생 전 준비 Write, 끝날 때 연결을 닫으며 Checkpoint</td><td>준비 뒤 12초 쉬고, 연결을 닫지 않음</td><td>재발 없음</td></tr>
						<tr><td>카메라 DB SQL 오류</td><td>앱 전용 CHECK 제약</td><td><code>ignore_check_constraints</code></td><td>오류 0, 실제 테이블로 Write</td></tr>
						<tr><td>가중치 TC Read가 원본보다 많음</td><td>DB를 재생 전에 한꺼번에 열어 1~2시간 뒤 page cache가 식음</td><td>함수 시작 10초 전(쉬는 구간)에 그 DB를 한 번 읽음</td><td>Read Volume 실패 39~41% → 상위 목록에서 빠짐</td></tr>
							<tr><td>TC의 fsync/s가 원본보다 많은 함수가 13개</td><td>수집 도구가 fdatasync를 놓쳐 원본 DB Write 상당수에 fsync flag가 없었어요</td><td>수집 도구가 f2fs sync tracepoint로도 fsync를 잡게 고치고, 원본 61개를 모두 다시 쟀어요</td><td>함수 단독 fsync/s 실패 13 → 5개{#if m1w && m1f}, m1 전체 지표 {m1w.tp}/{m1w.to} → {m1f.tp}/{m1f.to}{/if}</td></tr>
							<tr><td>다시 잰 원본으로 늦은 request(&gt;5ms)가 수천 개</td><td>"전면 카메라 사진 5장"이 파일 둘을 동시에 direct Write로 써서 Write가 4KB씩 번갈아 할당돼 있었어요. TC는 offset 사이 빈칸 때문에 4KB Write 수천 개를 하나씩 내다 밀렸어요</td><td>direct Write만 받는 파일은 빈칸 없이 붙이고 이어진 Write를 합침, 원본에서 번갈아 쓰인 파일끼리는 동시에 씀</td><td>{#if m1f && m1h && m2f && m2h}늦은 request m1 {m1f.late.toLocaleString()} → {m1h.late}, m2 {m2f.late.toLocaleString()} → {m2h.late}{/if}</td></tr>
							<tr><td>가중치 TC Read가 원본의 81%</td><td>처음 접근이 Write인 파일을 새 파일로 만들어, 아직 쓰지 않은 곳을 읽는 Read가 UFS에 닿지 않았어요("뷰어 빠른 넘기기 300장" 2·3회차가 대부분)</td><td>아직 쓰지 않은 곳을 Read하는 파일은 준비 단계에서 미리 채움</td><td>{#if m2h && m2i}{@const a = tot(m2h, 'Read Volume')}{@const b = tot(m2i, 'Read Volume')}m2 Read {a?.t} → {b?.t} MB (원본 {b?.o}, {a && b ? `${f((+a.t / +a.o) * 100, 0)} → ${f((+b.t / +b.o) * 100, 0)}%` : ''}), 갤러리 {m2h.cats.gallery?.join('/')} → {m2i.cats.gallery?.join('/')}{/if}</td></tr>
							<tr><td>atomic write 중인 파일의 Read 오류</td><td>f2fs가 atomic write 중(commit 전)인 파일의 direct Read를 <code>EOPNOTSUPP</code>로 거절해요</td><td>그 Read는 buffered로 다시 읽음 (원본 앱도 그 DB는 buffered로 읽어요)</td><td>{#if m2h && m2i}m2 재생 오류 {m2h.errs} → {m2i.errs}번{/if}</td></tr>
					</tbody>
				</table>
			</CopyTable>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="known" class="text-h2 font-bold">남은 차이</h2>
			<div class="prose-ux">
				<ul class="points">
					<li><b>채움 테이블 비중 {doc.padPct}%:</b> 양과 시각은 원본을 따르지만, page가 어느 테이블의 것인지는 앱과 달라요. 함수에 따라 절반 가까운 곳도 있어요.</li>
						<li><b>f2fs Checkpoint:</b> 원본 시각에 일으키지 않아 함수 단독에서 FS-induced Write와 Checkpoint/s가 모자라요. 대기 함수에서 커요{#if s3}(화면 끈 직후 5분 FS Write 원본 {s3.o}MB, TC {s3.t}MB){/if}.</li>
						<li><b>fsync/s:</b> 수집 도구를 고친 뒤에도 함수 단독에서 {doc.funcs.filter((x) => x.fails.some((k) => k.k === 'fsync/s')).length}개 함수가 틀려요. 대부분 TC가 많아요.</li>
					<li><b>Run 한 번씩:</b> 같은 build로 다시 재도 함수마다 1~3개 항목이 오르내려요. 이보다 작은 차이는 고친 효과로 보지 않았어요.</li>
				</ul>
			</div>
		</section>
	</div>

	{#if tip}
		<div class="tiptip" style="left:{Math.min(tip.x + 12, (typeof window !== 'undefined' ? window.innerWidth : 1200) - 270)}px;top:{tip.y + 14}px">
			<b>{tip.it.nm}</b> ({tip.it.rep}회차)<br />{doc.groupKo[tip.it.g]} · {f(tip.it.t / 60, 1)}분부터 {tip.it.d}초<br />{tip.it.n ? `판정 ${tip.it.p}/${tip.it.n}` : '판정 없음'}
		</div>
	{/if}
{/if}

<style>
	.tcf {
		--tg0: #3182f6; --tg1: #e69f00; --tg2: #009e73; --tg3: #8b95a1; --tg4: #cc79a7; --tg5: #d55e00; --tg6: #56b4e9; --tg7: #7b61ff;
	}
	:global(.dark) .tcf {
		--tg0: #4c95f7; --tg1: #f0b429; --tg2: #2bbf94; --tg3: #8b95a1; --tg4: #e08fc0; --tg5: #f07a3a; --tg6: #6cc3f0; --tg7: #9a86ff;
	}
	.flow { display: flex; flex-wrap: wrap; gap: 8px; }
	.flow > div { flex: 1 1 150px; min-width: 0; background: var(--muted); border-radius: 12px; padding: 12px 14px; font-size: 13px; color: var(--muted-foreground); }
	.flow b { display: block; color: var(--foreground); font-size: 14px; }
	.chips { display: flex; flex-wrap: wrap; gap: 6px; }
	.chip { border: 1px solid var(--border); border-radius: 999px; padding: 4px 12px; font-size: 13px; color: var(--muted-foreground); background: var(--background); }
	.chip[aria-pressed='true'] { background: var(--foreground); color: var(--background); border-color: var(--foreground); }
	.chip:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
	:global(.tcf tr.grp td) { background: var(--muted); color: var(--muted-foreground); font-weight: 600; }
	.pill { display: inline-block; min-width: 2.4em; padding: 0 6px; border-radius: 999px; font-weight: 600; text-align: center; }
	.pill.ok { color: var(--primary); }
	.pill.ng { color: var(--destructive); }
	.fails { min-width: 280px; white-space: normal; color: var(--muted-foreground); }
	.fails span { display: inline-block; margin-right: 10px; }
	.fails em { font-style: normal; color: var(--ink-4); }
	.legend { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12px; color: var(--muted-foreground); }
	.legend i, .sw { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }
	.mixcard { border: 1px solid var(--border); border-radius: 16px; padding: 20px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 8px; }
	.mixcard code { overflow-wrap: anywhere; }
	.strip { display: flex; gap: 2px; height: 34px; border-radius: 6px; overflow: hidden; }
	.strip > div { min-width: 2px; }
	.strip > div:hover { outline: 2px solid var(--foreground); outline-offset: -2px; }
	.axis { display: flex; justify-content: space-between; font-size: 11px; color: var(--ink-4); }
	.mixgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
	.mixgrid > :global(*) { min-width: 0; }
	.tiptip { position: fixed; z-index: 50; pointer-events: none; max-width: 260px; background: var(--foreground); color: var(--background); font-size: 12px; line-height: 1.5; padding: 8px 12px; border-radius: 12px; }
</style>
