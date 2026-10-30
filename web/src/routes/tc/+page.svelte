<script lang="ts">
	// TC 검증: UFS workload TC(wl/)가 원본 UX workload 패턴을 얼마나 재현하는지 (tc.json, wl/export_site.py)
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import Chart from '#lib/components/Chart.svelte';
	import CopyTable from '#lib/components/CopyTable.svelte';
	import { groupBarSpec } from '#lib/charts/build.js';
	import { load } from '#lib/data.js';
	import { mb, f } from '#lib/fmt.js';
	import type { TcDoc, TcCheck } from '#lib/types.js';

	let doc = $state<TcDoc | null>(null);
	let err = $state('');
	onMount(() => {
		load<TcDoc>('tc')
			.then((d) => (doc = d))
			.catch(() => (err = 'TC 검증 데이터를 불러오지 못했어요.'));
	});

	// 지표 이름·단위 (wl/metrics.py 의 CHECKS 키)
	const META: Record<string, { name: string; unit: 'MB' | '/s' | '/min' | '%' | 'qd' | 'dist'; desc: string }> = {
		readMB: { name: 'Read Volume', unit: 'MB', desc: 'GC Read 는 뺌' },
		writeMB: { name: 'Write Volume', unit: 'MB', desc: 'GC Write 는 뺌' },
		dataWriteMB: { name: 'App data Write', unit: 'MB', desc: 'Write 중 FS 유발 Write 를 뺀 것' },
		fsWriteMB: { name: 'FS-induced Write', unit: 'MB', desc: 'journal·Checkpoint·f2fs meta, fsync 밖 node Write' },
		fsPct: { name: 'FS-induced Write share', unit: '%', desc: 'Write 바이트 중' },
		flushPerSec: { name: 'Flush', unit: '/s', desc: '' },
		fsyncPerSec: { name: 'fsync', unit: '/s', desc: 'fsync 안 node Write 수' },
		discardMB: { name: 'Discard', unit: 'MB', desc: '' },
		gcMB: { name: 'GC Read·Write', unit: 'MB', desc: 'f2fs GC' },
		ckptPerSec: { name: 'Checkpoint', unit: '/s', desc: 'f2fs_ckpt Write 묶음 수' },
		sizeR: { name: 'Request size · Read', unit: 'dist', desc: '건수 %' },
		sizeW: { name: 'Request size · Write', unit: 'dist', desc: '건수 %' },
		seqR: { name: 'Sequential Read', unit: '%', desc: '바이트 %' },
		seqW: { name: 'Sequential Write', unit: '%', desc: '바이트 %' },
		gap: { name: 'DtoD distribution', unit: 'dist', desc: '건수 %' },
		idlePct: { name: 'Idle', unit: '%', desc: 'request 없는 100ms 칸' },
		wakesPerMin: { name: 'Wakeups', unit: '/min', desc: '1초 넘게 쉬다 오는 request' },
		qdP99: { name: 'QD p99', unit: 'qd', desc: '' },
		h8PerMin: { name: 'Hibern8', unit: '/min', desc: 'UFS mgmt command' },
		h8Pct: { name: 'Hibern8 time', unit: '%', desc: '시간 %' }
	};
	const CAT: Record<string, string> = {
		launch: '앱 실행',
		browser: '웹 브라우저',
		sns: 'SNS',
		video: '동영상',
		music: '음악',
		maps: '지도',
		camera: '카메라',
		gallery: '갤러리',
		mail_store: '메일·스토어',
		productivity: '업무·문서',
		commerce: '쇼핑',
		home: '홈 화면',
		call: '통화',
		daily: '하루 이벤트',
		standby: '대기 (화면 꺼짐)'
	};
	const mname = (k: string) => META[k]?.name ?? k;

	function val(k: string, v: number | number[]): string {
		const u = META[k]?.unit;
		if (Array.isArray(v)) return v.map((x) => x.toFixed(1)).join(' / ');
		if (u === 'MB') return mb(v);
		if (u === '/s') return f(v, 2) + '/s';
		if (u === '/min') return f(v, 1) + '/min';
		if (u === '%') return f(v, 1) + '%';
		return f(v, 0);
	}
	function diff(kind: string, c: TcCheck): string {
		if (c.d == null) return '–';
		if (kind === 'ratio') return '×' + c.d.toFixed(2);
		if (kind === 'diff') return (c.d > 0 ? '+' : '') + c.d.toFixed(1) + '%p';
		return c.d.toFixed(1) + '%p';
	}
	function rule(m: TcDoc['metrics'][number]): string {
		if (m.info) return '값만 (판정 안 함)';
		if (m.kind === 'ratio') return `TC/원본 ×${(1 - m.th).toFixed(2)}~${(1 + m.th).toFixed(2)}`;
		if (m.kind === 'diff') return `차이 ±${m.th}%p`;
		return `분포 차이 ≤${m.th}%p`;
	}
	const span = (xs: number[], d = 0, unit = '') => {
		const lo = Math.min(...xs),
			hi = Math.max(...xs);
		return lo.toFixed(d) === hi.toFixed(d) ? lo.toFixed(d) + unit : `${lo.toFixed(d)}~${hi.toFixed(d)}${unit}`;
	};
	const runName = (i: number) => {
		const r = doc!.runs[i];
		return `Run ${i + 1} (${r.version === 'pre-v1' ? 'v1 이전' : r.version})`;
	};

	const last = $derived(doc ? doc.runs[doc.runs.length - 1] : null);
	const judged = $derived(doc ? doc.metrics.filter((m) => !m.info) : []);
	const infoKeys = $derived(doc ? doc.metrics.filter((m) => m.info).map((m) => m.key) : []);
	const pre = $derived(doc?.runs.find((r) => r.version === 'pre-v1'));
	const v1 = $derived(doc?.runs.filter((r) => r.version !== 'pre-v1') ?? []);
	const allPass = $derived(doc ? doc.runs.every((r) => r.totalPass === r.totalOf) : false);
	// 카테고리 ratio 범위 (세 Run)
	const catRatio = (cats: string[], k: string) =>
		doc!.runs.flatMap((r) => cats.map((c) => r.cats[c]?.ratio[k]).filter((v): v is number => v != null));
	const tot = (k: string) => doc!.runs.map((r) => r.total[k]);
	const worst = $derived(
		last ? judged.map((m) => ({ k: m.key, v: last.itemPct[m.key] ?? 100 })).sort((a, b) => a.v - b.v) : []
	);

	const itemSpec = $derived(
		doc
			? groupBarSpec(
					'지표별 구간 통과율 (%)',
					judged.map((m) => mname(m.key)),
					doc.runs.map((r, i) => ({ name: runName(i), vals: judged.map((m) => r.itemPct[m.key]) })),
					'TC 결과(compare.json)를 <code>wl/export_site.py</code> 가 걸러 내요. 구간마다 원본 조각과 TC trace 의 같은 시간을 재고 <code>wl/metrics.py</code> 의 <code>judge</code> 로 판정해요. 원본·TC 값이 너무 작아 판정하지 않은 구간은 분모에서 뺐어요.',
					(t) => [t.mute, t.ramp[1], t.ramp[3]]
				)
			: null
	);
</script>

<svelte:head><title>UX I/O 분석 · TC 검증</title></svelte:head>

<nav class="mb-4 text-body-3 text-ink-3"><a href={resolve('/')} class="hover:text-foreground">홈</a> › TC 검증</nav>

{#if err}
	<p class="text-destructive">{err}</p>
{:else if !doc || !last}
	<Skeleton class="h-10 w-2/3" />
	<Skeleton class="mt-4 h-40 w-full" />
	<Skeleton class="mt-4 h-80 w-full" />
{:else}
	<header class="mb-8">
		<p class="text-label-s font-semibold text-primary">UFS workload TC · {doc.version} · {doc.tc}</p>
		<h1 class="mt-2 text-h1 font-bold">TC 검증</h1>
		<p class="mt-3 max-w-[760px] text-body-2 text-muted-foreground">
			UFS workload TC(<code>wl/</code>)가 원본 UX workload 패턴을 얼마나 재현하는지 봐요. TC는 측정한 trace를 block request가 아니라 파일 동작(pwrite, fsync,
			O_DIRECT, unlink 등)으로 바꿔 기기 <code>/data</code>에서 재생해요. Metadata·Checkpoint·Flush·Discard는 f2fs가 직접 만들게 두고, 재생 trace를 원본과 같은 지표로 비교해요.
		</p>
		<div class="mt-3 flex flex-wrap gap-2">
			<Badge variant="secondary">하루 사용을 2시간으로 압축</Badge>
			<Badge variant="secondary">같은 TC {doc.runs.length}번 실행</Badge>
			{#if doc.tcSha}<Badge variant="secondary">tcSha {doc.tcSha}</Badge>{/if}
			<Badge variant="secondary">배터리 · 무선 adb</Badge>
		</div>
	</header>

	<section class="mb-12 space-y-4">
		<h2 id="summary" class="text-h2 font-bold">Summary</h2>
		<div class="prose-ux summary">
			<div class="stats">
				<div><b>{span(doc.runs.map((r) => r.totalPass))}/{last.totalOf}</b><span>전체로 합친 지표 통과 ({doc.runs.length} Run)</span></div>
				<div><b>{span(doc.runs.map((r) => r.itemPassPct))}%</b><span>구간별 통과</span></div>
				<div><b>{span(doc.runs.map((r) => r.latePct), 2)}%</b><span>늦은 request (예정보다 5ms 넘게)</span></div>
			</div>
			<ul class="points">
				<li>
					<b>하루 TC를 같은 내용으로 {doc.runs.length}번 돌렸어요.</b> 하루 사용을 2시간으로 압축한 TC예요. tc.bin이 세 번 모두 같고, 첫 Run만 v1 이전 재생기(uxwl)로
					돌렸어요. 나머지 두 Run은 v1과 같은 코드예요.
				</li>
				<li>
					<b>전체로 합치면 판정하는 {last.totalOf}개 지표가 {allPass ? '세 Run 모두' : ''} 통과했어요.</b> 구간으로 잘라 보면 {span(doc.runs.map((r) => r.itemPassPct), 0)}%가
					통과해요. 구간은 TC 타임라인의 조각 하나(시나리오 조각, 앱 실행, 대기, 하루 이벤트)예요. Run 사이 차이 {f(Math.max(...doc.runs.map((r) => r.itemPassPct)) - Math.min(...doc.runs.map((r) => r.itemPassPct)), 1)}%p는 아래 흔들림 기준(5%p) 안이에요.
				</li>
				<li>
					<b>가장 덜 맞는 지표는 {mname(worst[0].k)}({f(worst[0].v, 0)}%), {mname(worst[1].k)}({f(worst[1].v, 0)}%), {mname(worst[2].k)}({f(worst[2].v, 0)}%)예요.</b> 원인과 남은 차이는
					<a href="#known">알려진 차이</a>에 정리했어요.
				</li>
				<li>
					<b>늦은 request는 {span(doc.runs.map((r) => r.latePct), 2)}%예요.</b> 재생기가 예정 시각보다 5ms 넘게 늦게 낸 request 비율이에요. 기기 Latency가 아니라 재생 시각이
					얼마나 정확한지 보는 값이에요.
				</li>
			</ul>
		</div>
		<CopyTable title="Run 요약" note="같은 tc.bin을 같은 기기에서 배터리·무선 adb 상태로 돌렸어요. 구간별 통과 = 모든 구간·지표 판정 중 통과한 비율이에요.">
			<table>
				<thead><tr><th>Run</th><th>uxwl</th><th class="num">구간별 통과 %</th><th class="num">전체 지표 통과</th><th class="num">늦은 request %</th><th>결과 폴더</th></tr></thead>
				<tbody>
					{#each doc.runs as r, i (r.id)}
						<tr>
							<td class="whitespace-nowrap">Run {i + 1}</td>
							<td class="whitespace-nowrap">{r.version === 'pre-v1' ? 'v1 이전' : r.version}</td>
							<td class="num">{f(r.itemPassPct, 1)}</td>
							<td class="num">{r.totalPass}/{r.totalOf}</td>
							<td class="num">{f(r.latePct, 2)}</td>
							<td class="text-ink-3">{r.id}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</CopyTable>
	</section>

	<section class="mb-12 space-y-4">
		<h2 id="total" class="text-h2 font-bold">전체 지표</h2>
		<p class="text-body-2 text-muted-foreground">
			2시간 TC 전체를 합친 값이에요(Run {doc.runs.length}, {last.version}). 원본은 TC에 쓴 원본 조각을 같은 길이만큼 잘라 더한 값이에요. TC 쪽은 재생기(uxwl)와 커널
			문맥(kworker·f2fs·jbd2) request만 세요. 화면 꺼진 TC 동안 폰의 다른 앱이 낸 I/O를 빼려는 거예요. 원본 조각에는 그때 다른 앱 I/O도 들어 있고 uxwl이 그것까지 재생해요.
		</p>
		<CopyTable
			title="전체 지표 · 원본 vs TC"
			note="ratio 지표는 TC/원본 비율이 기준 안이거나, 배경 I/O 몫으로 보는 작은 절대 차이 안이면 통과예요(wl/metrics.py의 SLACK). 분포 지표(Request size, DtoD)는 칸별 %를 / 로 이었고, 차이는 옮겨야 하는 비율(%p)이에요. GC Read·Write는 Volume에서 빼고 따로 셌어요."
		>
			<table>
				<thead><tr><th>지표</th><th class="num">원본</th><th class="num">TC</th><th class="num">차이</th><th>판정 기준</th><th>통과</th></tr></thead>
				<tbody>
					{#each doc.metrics as m (m.key)}
						{@const c = last.total[m.key]}
						{#if c}
							<tr>
								<td>
									{mname(m.key)}
									{#if m.buckets}<span class="rg">{m.buckets.join(' / ')}</span>{:else if META[m.key]?.desc}<span class="rg">{META[m.key].desc}</span>{/if}
								</td>
								<td class="num">{val(m.key, c.orig)}</td>
								<td class="num">{val(m.key, c.tc)}</td>
								<td class="num">{diff(m.kind, c)}</td>
								<td class="whitespace-nowrap">{rule(m)}</td>
								<td>
									{#if m.info || c.ok == null}<Badge variant="outline">값만</Badge>
									{:else if c.ok}<Badge variant="secondary">통과</Badge>
									{:else}<Badge variant="destructive">미달</Badge>{/if}
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</CopyTable>
	</section>

	<section class="mb-12 space-y-4">
		<h2 id="items" class="text-h2 font-bold">지표별 구간 통과율</h2>
		<p class="text-body-2 text-muted-foreground">
			전체로 합치면 넘치는 구간과 모자라는 구간이 서로 지워져요. 그래서 구간마다 따로 판정해 통과한 구간 비율을 봐요. 판정하지 않는 {infoKeys.map(mname).join(', ')}는
			뺐어요.
		</p>
		{#if itemSpec}<Chart spec={itemSpec} height={judged.length * 40 + 70} />{/if}
		{#if pre && v1.length}
			<div class="prose-ux">
				<p class="sowhat">
					<b>Sequential Read</b>v1 이전 Run은 {f(pre.itemPct.seqR, 0)}%, v1 Run은 {span(v1.map((r) => r.itemPct.seqR ?? 0), 0)}%예요. v1 재생기는 Read를 goroutine 하나가 시각
					순서대로 io_submit 하고 완료만 따로 기다려요. 같은 파일에서 앞 Read에 바로 붙은 Read는 한 묶음에 넣지 않아요. 묶음마다 goroutine을 띄우던 때는 준비에 0.5ms 쯤 걸려 뒤
					Read가 먼저 나가 순서가 섞였어요.
				</p>
			</div>
		{/if}
	</section>

	<section class="mb-12 space-y-4">
		<h2 id="cats" class="text-h2 font-bold">카테고리별 통과</h2>
		<p class="text-body-2 text-muted-foreground">
			카테고리마다 그 카테고리 구간을 모두 합쳐 판정했어요. 값은 통과 지표 수/판정한 지표 수예요. 값이 너무 작아 판정하지 않은 지표는 분모에서 빠져서 카테고리마다 분모가 달라요.
		</p>
		<CopyTable title="카테고리별 통과 지표 수" note="카테고리 통과 수는 2개 안의 차이를 Run 사이 흔들림으로 봐요 (아래 Run 사이 흔들림).">
			<table>
				<thead>
					<tr>
						<th>카테고리</th>
						{#each doc.runs as _, i (i)}<th class="num">{runName(i)}</th>{/each}
						<th>Run {doc.runs.length} 미달 지표</th>
					</tr>
				</thead>
				<tbody>
					{#each doc.cats as c (c)}
						<tr>
							<td class="whitespace-nowrap">{CAT[c] ?? c}</td>
							{#each doc.runs as r (r.id)}
								{@const x = r.cats[c]}
								<td class="num">{x ? `${x.pass}/${x.of}` : '–'}</td>
							{/each}
							<td>{last.cats[c]?.fail.map(mname).join(', ') || '없음'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</CopyTable>
	</section>

	<section class="mb-12 space-y-4">
		<h2 id="known" class="text-h2 font-bold">알려진 차이</h2>
		<p class="text-body-2 text-muted-foreground">v1에서 아직 맞추지 못한 차이와, 판정하지 않고 값만 보여 주는 지표예요. 값은 {doc.runs.length} Run 범위예요.</p>
		<div class="prose-ux">
			<ul class="points">
				<li>
					<b>대기 구간 Flush/s는 원본의 {span(catRatio(['standby'], 'flushPerSec'), 2)}배예요.</b> 원본 대기 Checkpoint는 Flush 5개(앞에 파일 동기화 2개 + Checkpoint 3개)인데
					TC는 3개예요. syncfs로 재생해 보면 쌓인 Discard가 다 나가 Flush·Discard가 몇 배가 됐어요. Flush 개수는 커널 flush_merge와 그때 dirty 양에 따라 4~7개로 흔들려
					맞추지 못했어요. 마지막 Run에서 Flush/s는 {doc.cats.length}개 카테고리 중 {doc.cats.filter((c) => last.cats[c]?.fail.includes('flushPerSec')).length}개에서 미달이고, 구간 통과율도 {span(doc.runs.map((r) => r.itemPct.flushPerSec ?? 0), 0)}%로 가장 낮아요.
				</li>
				<li>
					<b>I/O가 적은 구간(홈·통화·대기)은 FS-induced Write가 원본의 {span(catRatio(['home', 'call', 'standby'], 'fsWriteMB'), 2)}배예요.</b> 지금 폰에서 도는 배경 앱이
					node·quota를 더럽히고, TC가 원본 간격으로 일으키는 Checkpoint가 그것까지 같이 써요. 앱 데이터 Write는 comm으로 거르지만 Checkpoint 안의 FS Write는 누구 몫인지
					나눌 수 없어요. 반대로 I/O가 많은 웹 브라우저·SNS·음악·지도 구간은 원본의 {span(catRatio(['browser', 'sns', 'music', 'maps'], 'fsWriteMB'), 2)}배로 적어요. 두 쪽이
					서로 지워져 전체로는 ×{span(tot('fsWriteMB').map((c) => c.d ?? 0), 2)}로 맞아 보여요.
				</li>
				<li>
					<b>readahead 체인의 QD는 아직 못 맞춰요.</b> 전체 QD p99가 원본 {span(tot('qdP99').map((c) => +c.orig), 0)}, TC {span(tot('qdP99').map((c) => +c.tc), 0)}예요.
					기준(±50%) 안이지만 가장자리예요. 원본은 커널 readahead가 128KB Read를 35µs 간격으로 이어 내 QD가 50 넘게 오르는데, 재생기의 io_submit은 한 번에 80µs 쯤 걸려요.
					readahead(2)로 커널에 맡겨 보면 request size와 양이 어긋났어요.
				</li>
				<li>
					<b>Discard는 값만 보여 줘요 (원본의 {span(tot('discardMB').map((c) => c.d ?? 0), 2)}배).</b> f2fs가 idle 때 알아서 내므로 언제 나올지 TC가 정할 수 없어요. 원본
					Discard는 재생하지 않고, TC가 지우는 파일에서 f2fs가 내는 Discard만 세요.
				</li>
				<li>
					<b>GC Read·Write는 값만 보여 줘요 (원본의 {span(tot('gcMB').map((c) => c.d ?? 0), 2)}배).</b> 얼마나 할지는 파일 시스템이 얼마나 차고 조각났는지에 달려요. 같은 TC인데도
					Run마다 이만큼 달라요.
				</li>
				<li>
					<b>Hibern8은 값만 보여 줘요 (Hibern8/min 원본의 {span(tot('h8PerMin').map((c) => c.d ?? 0), 2)}배, Hibern8 time 원본보다 {span(tot('h8Pct').map((c) => -(c.d ?? 0)), 1)}%p 짧음).</b> UFS mgmt
					command라 재생기 몫만 거를 수 없어요. 화면 꺼진 TC 동안 다른 앱 request가 링크를 깨우는 몫이 섞여요.
				</li>
			</ul>
		</div>

		<h3 id="noise" class="pt-4 text-h4 font-bold">Run 사이 흔들림</h3>
		<p class="text-body-2 text-muted-foreground">
			같은 TC·같은 uxwl로 두 번 돌린 결과를 구간별로 견줘 흔들림 크기를 정했어요. 이보다 작은 차이로 TC가 좋아졌다 나빠졌다 하지 않아요.
		</p>
		<CopyTable title="Run 사이 흔들림 기준" note="p90 = 두 Run의 같은 구간 값 차이(비율 또는 %p)를 모은 분포의 90 percentile이에요. 2026-10-30 day6 v1 두 Run으로 쟀어요.">
			<table>
				<thead><tr><th>구분</th><th>지표</th><th>판단</th></tr></thead>
				<tbody>
					<tr>
						<td class="whitespace-nowrap">거의 안 흔들림</td>
						<td>Read Volume(두 Run이 같음), Sequential Read(p90 0.4%p), Request size, DtoD distribution, Idle(p90 2.7%p), fsync/s(p90 ×1.14)</td>
						<td>작은 차이도 의미가 있어요</td>
					</tr>
					<tr>
						<td class="whitespace-nowrap">많이 흔들림</td>
						<td>FS-induced Write(p90 ×2.1), Checkpoint/s(p90 ×3.0), Flush/s(p90 ×1.6), Wakeups/min(p90 ×2.0), QD p99(p90 ×1.9), Sequential Write(p90 13%p)</td>
						<td>구간 판정이 Run마다 10~25% 뒤집혀요</td>
					</tr>
					<tr>
						<td class="whitespace-nowrap">고친 효과로 보는 기준</td>
						<td>지표별 구간 통과율 5%p 넘게, 카테고리 통과 수 2개 넘게</td>
						<td>또는 여러 카테고리에서 같은 쪽으로 움직일 때</td>
					</tr>
				</tbody>
			</table>
		</CopyTable>
	</section>

	<section class="mb-12">
		<h2 id="method" class="mb-3 text-h2 font-bold">비교 방법</h2>
		<div class="prose-ux">
			<ul class="points">
				<li>판정 기준은 <code>wl/metrics.py</code>의 <code>CHECKS</code>예요. ratio는 TC/원본 비율, diff는 차이(%p), dist는 분포 차이(%p)로 봐요. 기준과 재생 방식은 git 태그 <code>wl-v1</code>로 고정했어요.</li>
				<li>원본이나 TC 값이 아주 작으면(<code>FLOOR</code> 미만) 그 구간은 판정하지 않아요. request가 20개보다 적은 구간은 Request size를 판정하지 않아요.</li>
				<li>화면 켜진 구간 바로 뒤 대기 구간은 처음 10초를 판정에서 빼요. 앞 구간이 남긴 writeback·Checkpoint·Discard가 몰리는데, 원본 대기는 쉰 뒤에 쟀기 때문이에요.</li>
				<li>측정 전에 앞 TC 파일을 지우고 <code>pending_discard</code>가 0이 될 때까지 기다린 뒤 trace를 시작해요.</li>
				<li>TC 구성(카테고리 비중, 구간 순서·길이)은 라이선스가 불명인 사용 로그 데이터셋에서 나와서 이 페이지에 싣지 않아요.</li>
			</ul>
		</div>
	</section>
{/if}
