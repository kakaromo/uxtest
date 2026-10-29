<script lang="ts">
	import { resolve } from '$app/paths';
	import Chart from '#lib/components/Chart.svelte';
	import CopyTable from '#lib/components/CopyTable.svelte';
	import { app, TYPE_ORDER } from '#lib/state.svelte.js';
	import { volSpec, mapSpec } from '#lib/charts/build.js';
	import { label, rows, rowsOf, rowOf, nameOf, cname } from '#lib/view.js';
	import { mb, f } from '#lib/fmt.js';
	import { emph } from '#lib/insight.js';
	import { ArrowRight } from '@lucide/svelte';

	const c = $derived(app.content!);
	const all = $derived(rows());
	const types = $derived(TYPE_ORDER.filter((t) => app.index?.types[t]));

	const DEVICE: [string, string][] = [
		['기기', 'OnePlus 15 (CPH2749)'],
		['SoC', 'Snapdragon SM8850'],
		['RAM', '16GB'],
		['Storage', 'Samsung UFS 512GB'],
		['OS', 'Android 16 (OxygenOS), Linux kernel 6.12.23'],
		['File system', '/data f2fs, 4KB block']
	];
	const COND: [string, string][] = [
		['평가 모드', 'USB를 뺀 배터리 상태, 무선 adb. 실제 사용처럼 충전하지 않는 상태예요. USB 전원이면 deviceidle이 깨어 있어 Discard 같은 background 동작이 달라져요.'],
		['조작', '자동화 도구(agent)가 앱 실행, 탭, 스크롤을 재생해요. 기기 설정은 기본값 그대로, 계정은 평소 쓰는 개인 계정이에요. 권한 요청 창은 "허용 안 함"으로 닫아요.'],
		['수집', 'fsiotrace(eBPF)로 UFS driver에 들어간 request 하나하나를 기록해요(크기, LBA, Latency, QD, 원인 flag). 측정할 동작 동안에만 기록을 켜요.'],
		['시작 상태', '"cold"는 측정 전에 memory cache를 비운 상태예요. 갤러리 cold는 사진 1000장을 새로 넣어 thumbnail이 없는 상태로 시작해요.'],
		['반복 횟수', '시나리오마다 3번. Run 사이 60초 휴식(대기 시나리오는 120초). 3시간 대기만 1번. 값은 3번의 median이에요.'],
		['측정 시점', '화면 켜진 57개: 2026-10-28 14:08~19:45 (배터리 59%→23%). 화면 꺼진 대기 4개: 10-28 21:52~10-29 04:22 (100%→94%).']
	];
	// 유형별 대표 시나리오, UFS 관점 특성, 고른 이유
	const PICK: { t: string; ids: string[]; ufs: string; why: string }[] = [
		{ t: 'A', ids: ['A1', 'A4', 'A3'], ufs: '처음 열 때 앱당 약 190MB Read. 중간 크기 Random Read를 한꺼번에 여러 개 보내 QD가 높아요.', why: '사용자가 가장 자주 체감하는 반응 속도예요. Read throughput과 높은 QD 처리 능력이 실행 시간에 바로 걸려요. cold와 warm 전환을 같이 봐요.' },
		{ t: 'B', ids: ['B1', 'B7', 'B7t'], ufs: '40~60초에 Write 4~29MB. 작은 Write가 띄엄띄엄 나오고 대부분 Idle이에요.', why: '화면을 켜고 가장 오래 하는 동작이에요. 작은 Write의 Latency와 Idle에서 깨어나는 속도, Hibern8 진입·복귀가 중요해요.' },
		{ t: 'C', ids: ['C1', 'C4b', 'C3'], ufs: '스트리밍은 거의 Idle. 로컬 영상은 약 45초마다 구간을 몰아 Read해요.', why: '오래 켜 두는 동작이라 Idle과 low-power 구간이 길어요. 스트리밍과 로컬 재생, 화질에 따른 차이를 봐요.' },
		{ t: 'D', ids: ['D1', 'D2', 'D5'], ufs: '큰 Sequential Write가 이어져요. 사진 10장에 Write 1.26GB, 최대 765MB/s. 4K 동영상은 1080p의 약 3배예요.', why: '일상 동작 중 Write가 가장 많아요. Write buffer 크기, sustained Write 성능, endurance를 보는 대표 workload예요.' },
		{ t: 'E', ids: ['E2', 'E3', 'E6'], ufs: '큰 Read·Write를 끊김 없이 이어서 최대 1.1GB/s. 삭제는 Discard로 이어져요.', why: '가끔 일어나지만 무거운 일이에요(복사, 앱 설치·업데이트, 큰 파일 삭제). 기기의 최대 throughput과 Discard·file system 동작을 봐요.' },
		{ t: 'F', ids: ['F1', 'F2', 'F5'], ufs: 'Write 1~11MB. 작은 Write와 fsync 몇 번이고 대부분 Idle이에요.', why: '가벼운 동작의 기준선이에요. 저장 순간의 작은 fsync Latency가 체감에 걸리는지 확인해요.' },
		{ t: 'G', ids: ['G1', 'G2', 'G3'], ufs: '뷰어 11분에 Read 2.63GB·Write 3.13GB. 원본 사진을 매번 다시 읽고 화면용 cache를 계속 써요.', why: '사진이 많이 쌓인 실제 기기 상태를 재현해요. cold(thumbnail 없음)와 warm 차이로 앱 cache 정책이 UFS에 주는 부담을 봐요.' },
		{ t: 'S', ids: ['S1', 'S2', 'S5'], ufs: '30분에 Write 105MB. 작은 Write와 Flush가 약 2초마다 나와요. 앱 업데이트가 끼면 몰아 Read해요.', why: '폰은 하루 대부분 대기 상태예요. 짧은 Idle 사이의 Hibern8 진입·복귀와 background Discard가 전력과 성능에 걸려요.' }
	];
	const sname = (id: string) => {
		const r = rowOf(id);
		return r ? nameOf(r) : id;
	};
</script>

<svelte:head><title>UX I/O 분석 · 홈</title></svelte:head>

<header class="mb-10">
	<p class="text-label-s font-semibold text-primary">배터리 측정 · 2026-10-28~29</p>
	<h1 class="mt-2 text-display-2 font-bold">UX 워크로드 유형별 UFS I/O 패턴</h1>
	<p class="mt-4 max-w-[720px] text-body-1 text-muted-foreground">{@html c.lede}</p>
	<p class="mt-3 text-body-3 text-ink-3">{@html c.byline}</p>
</header>

<section class="mb-12 space-y-4">
	<h2 id="device" class="text-h2 font-bold">Target device</h2>
	<CopyTable title="Target device">
		<table>
			<tbody>
				{#each DEVICE as [k, v] (k)}<tr><th class="w-32">{k}</th><td>{v}</td></tr>{/each}
			</tbody>
		</table>
	</CopyTable>
</section>

<section class="mb-12 space-y-4">
	<h2 id="conditions" class="text-h2 font-bold">공통 평가 조건</h2>
	<CopyTable title="공통 평가 조건">
		<table>
			<tbody>
				{#each COND as [k, v] (k)}<tr><th class="w-32">{k}</th><td>{v}</td></tr>{/each}
			</tbody>
		</table>
	</CopyTable>
</section>

<section class="mb-12 space-y-4">
	<h2 id="selection" class="text-h2 font-bold">UX 유형·시나리오 선정</h2>
	<p class="text-body-2 text-muted-foreground">유형마다 UFS에 주는 부담이 다른 동작을 골랐어요. 대표 시나리오를 누르면 시나리오 분석 페이지로 가요. 유형별 전체 시나리오는 아래 유형 카드에 있어요.</p>
	<CopyTable title="UX 유형·시나리오 선정">
		<table>
			<thead><tr><th>카테고리</th><th>대표 시나리오</th><th>UFS 관점 주요 특성</th><th>선정 이유</th></tr></thead>
			<tbody>
				{#each PICK as p (p.t)}
					<tr>
						<td class="whitespace-nowrap"><a href={resolve('/type/[t]', { t: p.t })}>{app.index?.types[p.t] ?? p.t}</a></td>
						<td>
							{#each p.ids as id, i (id)}{#if i}<br />{/if}<a href={resolve('/s/[id]', { id })}>{sname(id)}</a>{/each}
						</td>
						<td>{p.ufs}</td>
						<td>{p.why}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</CopyTable>
</section>

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
			<thead><tr><th>ID</th><th>Type</th><th>Scenario</th><th>P</th><th class="num">Duration s</th><th class="num">Read MB</th><th class="num">Write MB</th><th class="num">Peak MB/s</th><th class="num">Idle %</th><th class="num">Run</th></tr></thead>
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
				<thead><tr><th>ID</th><th class="num">Hibern8 /min</th><th class="num">Hibern8 time %</th><th class="num">H8 exit ms</th><th class="num">Query /min</th><th class="num">bBackgroundOpStatus /min</th><th class="num">WB check /min</th><th class="num">suspend</th><th class="num">qTimestamp</th></tr></thead>
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
