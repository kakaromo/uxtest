<script lang="ts">
	// 대기 3시간(S5) 배터리 ↔ USB 전원 비교. 데이터: standby-power.json (report/export_standby_power.py)
	import { resolve } from '$app/paths';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import Chart from '#lib/components/Chart.svelte';
	import CopyTable from '#lib/components/CopyTable.svelte';
	import { app } from '#lib/state.svelte.js';
	import { load } from '#lib/data.js';
	import { stbyStripSpec, stbyWindowSpec } from '#lib/charts/build.js';
	import { STANDBY_POWER } from '#lib/view.js';
	import { f, n0 } from '#lib/fmt.js';
	import type { StandbyPower, StbyRun } from '#lib/types.js';

	let D = $state<StandbyPower | null>(null);
	let err = $state('');
	$effect(() => {
		load<StandbyPower>('standby-power')
			.then((d) => (D = d))
			.catch(() => (err = '비교 데이터를 불러오지 못했어요.'));
	});

	const runs = $derived(D?.runs ?? []);
	const bat = $derived(runs.filter((r) => r.power === 'battery'));
	const usb = $derived(runs.filter((r) => r.power === 'usb'));
	const withB = $derived(runs.filter((r) => r.burst));
	const min = (r: StbyRun) => r.durSec / 60;
	const flushPerMin = (r: StbyRun) => r.flushN / min(r);
	const h8All = (r: StbyRun) => (r.ah8 + r.swh8) / min(r);
	const ufsPerHour = (r: StbyRun) => r.ufsSuspend / (r.durSec / 3600);
	/** 측정 회차의 최솟값~최댓값 (같으면 하나) */
	const rng = (rs: StbyRun[], get: (r: StbyRun) => number, d = 0, unit = '') => {
		const v = rs.map(get);
		if (!v.length) return '–';
		const a = Math.min(...v).toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d });
		const b = Math.max(...v).toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d });
		return (a === b ? a : `${a}~${b}`) + unit;
	};
	const batS = $derived(bat.filter((r) => r.suspend));
	const usbS = $derived(usb.filter((r) => r.suspend));
	// 30초 그림과 burst 설명에 쓰는 측정 (export 에서 고른 것)
	const wb = $derived(runs.find((r) => r.label === D?.window.battery?.label));
	const wu = $derived(runs.find((r) => r.label === D?.window.usb?.label));
	const failPct = $derived(batS[0]?.suspend ? (100 * batS[0].suspend.fail) / batS[0].suspend.attempt : 0);
	const tryEvery = $derived(batS[0]?.suspend?.attempt ? batS[0].durSec / batS[0].suspend.attempt : 0);
	const noRead = $derived(!D?.window.battery?.kinds.R && !D?.window.usb?.kinds.R);
	const who = (l: [string, number][] | undefined, n = 3) => (l ?? []).slice(0, n).map((x) => x[0]);
	const code = (s: string) => (s.includes('_') ? `<code>${s}</code>` : s);
	const ratio = $derived({
		ck: [Math.min(...usb.map((r) => r.ckptMB)) / Math.max(...bat.map((r) => r.ckptMB)), Math.max(...usb.map((r) => r.ckptMB)) / Math.min(...bat.map((r) => r.ckptMB))]
	});
	const winSpec = $derived(
		D?.window.battery && D.window.usb
			? stbyWindowSpec(
					[
						{ name: `배터리 (${D.window.battery.label.split(' ')[1]})`, ev: D.window.battery.ev },
						{ name: `USB 연결 (${D.window.usb.label.split(' ')[1]})`, ev: D.window.usb.ev }
					],
					D.window.battery.len
				)
			: null
	);
	const STRIPS: { k: string; get: (r: StbyRun) => number; unit: string; d: number }[] = [
		{ k: '드라이버 Hibern8 진입', get: (r) => r.h8PerMin, unit: '/분', d: 1 },
		{ k: '드라이버 Hibern8 한 번 머문 시간 중앙값', get: (r) => r.dwellP50, unit: '초', d: 1 },
		{ k: 'Wakeups (1초 이상 쉬다 깸)', get: (r) => r.wakesPerMin, unit: '/분', d: 1 },
		{ k: 'Flush', get: flushPerMin, unit: '/분', d: 1 },
		{ k: 'UFS suspend', get: ufsPerHour, unit: '/시간', d: 0 },
		{ k: 'f2fs Checkpoint Write', get: (r) => r.ckptMB, unit: 'MB', d: 0 }
	];
	const strips = $derived(
		STRIPS.map((m) => ({
			...m,
			spec: stbyStripSpec(m.k, runs.map((r) => ({ label: r.label, usb: r.power === 'usb', v: m.get(r) })), m.unit, m.d)
		}))
	);

	type Line = [string, (r: StbyRun) => string];
	const T_SUSP: Line[] = [
		['system suspend 시도', (r) => (r.suspend ? n0(r.suspend.attempt) : '')],
		['성공', (r) => (r.suspend ? n0(r.suspend.success) : '')],
		['실패: freeze 단계', (r) => (r.suspend ? n0(r.suspend.failed_freeze) : '')],
		['실패: 장치 suspend 단계', (r) => (r.suspend ? n0(r.suspend.failed_suspend) : '')],
		['UFS suspend', (r) => n0(r.ufsSuspend)],
		['SSU 명령', (r) => n0(r.ssu)],
		['드라이버 Hibern8 진입', (r) => n0(r.swh8)],
		['드라이버 Hibern8 진입 /분', (r) => f(r.h8PerMin, 1)],
		['드라이버 Hibern8 시간', (r) => f(r.h8Pct, 1) + '%'],
		['드라이버 Hibern8 한 번 머문 시간 중앙값', (r) => f(r.dwellP50, 1) + '초'],
		['Hibern8 진입 / 해제 Latency', (r) => `${f(r.h8EnterMs, 2)} / ${f(r.h8ExitMs, 2)}ms`],
		['Wakeups /분', (r) => f(r.wakesPerMin, 1)],
		['Flush', (r) => n0(r.flushN)]
	];
	const T_AH8: Line[] = [
		['Auto-Hibern8 진입 /분 (추정)', (r) => f(r.ah8 / min(r), 1)],
		['Auto-Hibern8 시간 (추정)', (r) => f((100 * r.ah8Sec) / r.durSec, 1) + '%'],
		['그중 100ms 이상', (r) => n0(r.ah8Long) + '번'],
		['드라이버 Hibern8 진입 /분', (r) => f(r.swh8 / min(r), 1)],
		['드라이버 Hibern8 시간', (r) => f((100 * r.swh8Sec) / r.durSec, 1) + '%'],
		['Hibern8 진입 합 /분', (r) => f(h8All(r), 0)],
		['link 가 Hibern8 에 있던 시간 (합)', (r) => f((100 * (r.ah8Sec + r.swh8Sec)) / r.durSec, 1) + '%']
	];
	const T_BURST: Line[] = [
		['burst /분', (r) => f(r.burst!.perMin, 1)],
		['burst 간격 중앙값', (r) => f(r.burst!.ibiP50, 2) + '초'],
		['주기 burst 비율', (r) => f(r.burst!.periodPct, 0) + '%'],
		['가장 강한 주기 (FFT)', (r) => f(r.burst!.period, 1) + '초'],
		['burst 당 request 중앙값', (r) => n0(r.burst!.reqP50)],
		['burst 길이 중앙값', (r) => f(r.burst!.durP50, 2) + '초'],
		['구성: Flush', (r) => f(r.burst!.comp.F, 1)],
		['구성: Checkpoint Write', (r) => f(r.burst!.comp.CK, 1)],
		['구성: node·meta Write', (r) => f(r.burst!.comp.NM, 1)],
		['구성: Discard', (r) => f(r.burst!.comp.D, 1)],
		['구성: 일반 Write', (r) => f(r.burst!.comp.W, 1)],
		['구성: Read', (r) => f(r.burst!.comp.R, 1)],
		['주기 burst 안 request 주체', (r) => who(r.burst!.who).join(', ')],
		['burst 를 연 request 주체', (r) => who(r.burst!.opener).join(', ')]
	];
	const T_VOL: Line[] = [
		['측정 길이', (r) => f(min(r), 0) + '분'],
		['Read', (r) => n0(r.readMB) + 'MB'],
		['Write', (r) => n0(r.writeMB) + 'MB'],
		['Discard', (r) => n0(r.discardMB) + 'MB'],
		['Read / Write request', (r) => `${n0(r.readN)} / ${n0(r.writeN)}`],
		['dexopt Write', (r) => (r.dexMB >= 0.5 ? n0(r.dexMB) + 'MB' : '없음')],
		['f2fs Checkpoint Write', (r) => n0(r.ckptMB) + 'MB'],
		['f2fs GC Write', (r) => (r.gcMB >= 0.5 ? n0(r.gcMB) + 'MB' : '없음')],
		['4KB 이하 Read / Write', (r) => `${f(r.size4k.R, 0)} / ${f(r.size4k.W, 0)}%`],
		['Sequential Read / Write', (r) => `${f(r.seq.R, 0)} / ${f(r.seq.W, 0)}%`],
		['DtoD 1ms 미만', (r) => f(r.gap1ms, 0) + '%'],
		['CtoD 0 (overlap)', (r) => f(r.ctod0, 0) + '%'],
		['CtoD 200ms 이상', (r) => f(r.ctod200, 1) + '%'],
		['Read Latency P50 / P99', (r) => `${f(r.dtocP50.R, 2)} / ${f(r.dtocP99.R, 2)}ms`],
		['Write Latency P50 / P99', (r) => `${f(r.dtocP50.W, 2)} / ${f(r.dtocP99.W, 2)}ms`],
		['QD P99', (r) => n0(r.qdP99)],
		['sync Write 비율', (r) => f(r.syncPct, 0) + '%']
	];
	const head = (r: StbyRun) => r.label.split(' ');
	const href = (r: StbyRun) => (r.link ? resolve('/s/[id]', { id: r.link.id }) : '');
</script>

<svelte:head><title>UX I/O 분석 · 대기 USB·배터리 비교</title></svelte:head>

<nav class="mb-4 flex flex-wrap items-center gap-1 text-body-3 text-ink-3">
	<a href={resolve('/')} class="hover:text-foreground">홈</a> ›
	<a href={resolve('/type/[t]', { t: 'S' })} class="hover:text-foreground">S {app.index?.types.S ?? ''}</a> ›
	<span>대기 USB·배터리 비교</span>
</nav>

{#if err}
	<p class="text-destructive">{err}</p>
{:else if !D}
	<Skeleton class="h-10 w-2/3" />
	<Skeleton class="mt-4 h-80 w-full" />
{:else}
	<div class="stby max-w-[880px]">
		<header class="mb-10">
			<p class="text-label-s font-semibold text-primary">{app.index?.meta.device} · Android 16 · f2fs · 홈에서 화면 끄고 3시간 · 배터리 {bat.length}회, USB {usb.length}회</p>
			<h1 class="mt-2 text-h1 font-bold">대기 3시간 USB·배터리 비교</h1>
			<p class="mt-3 text-title-1 text-foreground">
				USB 를 꽂으면 폰이 잠들기(suspend)를 아예 시도하지 않아요. 그래서 배터리일 때 2초마다 생기던 sync I/O 가 사라지고, UFS 가 Hibern8 에 들어가는 횟수가 절반쯤으로 줄어요.
			</p>
			<div class="mt-4 flex flex-col gap-1 rounded-xl border bg-card px-4 py-3 text-body-3">
				<span>배터리 측정(최근 1회)의 전체 pattern: <a class="font-semibold text-primary" href={resolve('/s/[id]', { id: STANDBY_POWER.base })}>{app.names[STANDBY_POWER.base] ?? STANDBY_POWER.base}</a></span>
				<span>USB 측정 {usb.length}회의 전체 pattern: <a class="font-semibold text-primary" href={resolve('/s/[id]', { id: STANDBY_POWER.variant })}>{app.names[STANDBY_POWER.variant] ?? STANDBY_POWER.variant}</a> <span class="text-ink-3">(참고용, 유형 집계·TC 비교에서 빠져요)</span></span>
			</div>
		</header>

		<section class="mb-12 space-y-4">
			<h2 id="glance" class="text-h2 font-bold">한눈에 보기</h2>
			<div class="overflow-hidden rounded-2xl border bg-card">
				<div class="vs-row text-body-3 font-semibold text-muted-foreground"><div>3시간 대기</div><div>배터리</div><div class="usb text-primary">USB 연결</div></div>
				{#each [
					{ k: 'system suspend 시도', s: '커널 suspend_stats', b: `${rng(batS, (r) => r.suspend!.attempt)}번`, bs: `성공 ${rng(batS, (r) => r.suspend!.success)}번`, u: `${rng(usbS, (r) => r.suspend!.attempt)}번`, us: `${usbS.length}회 모두` },
					{ k: 'I/O burst 주기', s: '1초 넘게 쉬다 오는 묶음, 간격 중앙값', b: rng(withB.filter((r) => r.power === 'battery'), (r) => r.burst!.ibiP50, 1, '초'), bs: 'suspend 시도 주기와 같음', u: rng(withB.filter((r) => r.power === 'usb'), (r) => r.burst!.ibiP50, 1, '초'), us: '앱·서비스 Write' },
					{ k: 'burst 하나의 request', s: '중앙값', b: rng(withB.filter((r) => r.power === 'battery'), (r) => r.burst!.reqP50, 0, '개'), bs: 'Flush·Checkpoint 위주', u: rng(withB.filter((r) => r.power === 'usb'), (r) => r.burst!.reqP50, 0, '개'), us: '일반 Write 위주' },
					{ k: 'Flush', s: '', b: rng(bat, flushPerMin, 0, '/분'), bs: '', u: rng(usb, flushPerMin, 0, '/분'), us: '' },
					{ k: 'UFS 가 Hibern8 에 들어간 횟수', s: '드라이버 + Auto-Hibern8', b: rng(bat, h8All, 0, '/분'), bs: '', u: rng(usb, h8All, 0, '/분'), us: '' },
					{ k: 'UFS suspend (장치 SLEEP)', s: '', b: rng(bat, (r) => r.ufsSuspend, 0, '번'), bs: '', u: rng(usb, (r) => r.ufsSuspend, 0, '번'), us: '' },
					{ k: 'f2fs Checkpoint Write', s: '', b: rng(bat, (r) => r.ckptMB, 0, 'MB'), bs: '', u: rng(usb, (r) => r.ckptMB, 0, 'MB'), us: '충전 중 정리 작업' }
				] as v (v.k)}
					<div class="vs-row border-t">
						<div class="text-body-2">{v.k}{#if v.s}<small class="block text-caption text-ink-3">{v.s}</small>{/if}</div>
						<div class="vs-val">{v.b}{#if v.bs}<small>{v.bs}</small>{/if}</div>
						<div class="vs-val usb text-primary">{v.u}{#if v.us}<small>{v.us}</small>{/if}</div>
					</div>
				{/each}
			</div>
			<p class="text-body-3 text-ink-3">범위는 측정 회차의 최솟값~최댓값이에요. suspend 시도는 기록을 넣은 뒤 잰 배터리 {batS.length}회, USB {usbS.length}회 값이에요. burst 는 3시간을 다 잰 측정만 봤어요.</p>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="window" class="text-h2 font-bold">30초 동안 실제로 온 request</h2>
			{#if winSpec}<Chart spec={winSpec} height={190} caption={noRead ? '이 30초에는 Read 가 없었어요.' : ''} />{/if}
			{#if D.window.battery && D.window.usb}
				<p class="text-body-2 text-muted-foreground">
					측정 시작 1시간 뒤 30초를 그대로 그렸어요({D.window.battery.label}, {D.window.usb.label}). 배터리는 2초 남짓마다 sync 계열 request 가 묶음으로 오고({n0(D.window.battery.n)}개), USB 는 5초마다 일반 Write 몇 개만 와요({n0(D.window.usb.n)}개).
				</p>
			{/if}
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="why" class="text-h2 font-bold">왜 이렇게 달라지나</h2>
			<div class="grid gap-3 sm:grid-cols-2">
				<div class="flex flex-col gap-2 rounded-2xl bg-muted p-4">
					<h3 id="why-battery" class="text-title-1 font-semibold text-muted-foreground" data-toc="배터리">배터리</h3>
					<div class="step">잡고 있는 wakelock 이 없으면 커널이 suspend 를 시도해요</div>
					<div class="arrow">↓</div>
					<div class="step">시도할 때마다 파일 시스템 sync → Flush {f(wb?.burst?.comp.F, 0)}개, f2fs Checkpoint Write {f(wb?.burst?.comp.CK, 0)}개</div>
					<div class="arrow">↓</div>
					<div class="step">대부분 프로세스 freeze 에서 실패하고 2초 뒤 다시 시도 (실패 {f(failPct, 0)}%)</div>
					<div class="arrow">↓</div>
					<div class="step">드물게 성공하면 UFS 도 SLEEP(SSU)</div>
				</div>
				<div class="flex flex-col gap-2 rounded-2xl bg-muted p-4">
					<h3 id="why-usb" class="text-title-1 font-semibold text-primary" data-toc="USB 연결">USB 연결</h3>
					<div class="step">USB 연결이 wakelock 을 잡아 suspend 를 시도하지 않아요</div>
					<div class="arrow">↓</div>
					<div class="step">sync burst 가 없어요. 서비스의 작은 Write 만 5초마다 와요</div>
					<div class="arrow">↓</div>
					<div class="step">UFS 는 Hibern8 에 들어가는 횟수가 절반쯤이고 한 번 들어가면 더 오래 머물러요</div>
					<div class="arrow">↓</div>
					<div class="step">대신 충전 중에 f2fs Checkpoint·GC 같은 정리 Write 가 늘어요</div>
				</div>
			</div>
			<p class="text-body-3 text-ink-3">
				suspend 시도 때 sync 가 돈다는 연결은 주기({f(tryEvery, 2)}초 대 {f(wb?.burst?.ibiP50, 2)}초)와 burst 구성이 맞아서 내린 결론이에요. Flush 를 kworker 가 보내서 trace 만으로 직접 확정하지는 못해요.
			</p>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="repeat" class="text-h2 font-bold">측정마다 같은 차이가 나와요</h2>
			<p class="text-body-2 text-muted-foreground">점 하나가 측정 1회예요(회색 배터리, 파랑 USB 연결). 배터리와 USB 의 범위가 겹치지 않아요.</p>
			<div class="grid gap-3 lg:grid-cols-2">
				{#each strips as s (s.k)}
					<Chart spec={s.spec} height={130} caption="배터리 {rng(bat, s.get, s.d, s.unit)} · USB {rng(usb, s.get, s.d, s.unit)}" />
				{/each}
			</div>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="so" class="text-h2 font-bold">그래서</h2>
			<ul class="list-disc space-y-2 pl-5 text-body-2 text-muted-foreground">
				<li><b class="text-foreground">대기 측정은 배터리로 해야 해요.</b> USB 전원이면 suspend, Flush, Hibern8, Write 성격이 모두 실제 사용자와 달라져요.</li>
				<li><b class="text-foreground">대기 TC 는 2.2초 주기 sync 를 담아야 해요.</b> 배터리 대기 I/O 의 대부분은 앱이 아니라 suspend 시도가 만들어요.</li>
				<li><b class="text-foreground">Volume 만으로는 구분이 안 돼요.</b> dexopt(앱 컴파일)가 돈 날은 조건과 상관없이 Read·Write 가 수 배로 커져요.</li>
			</ul>
		</section>

		<section class="mb-12 space-y-4">
			<h2 id="tables" class="text-h2 font-bold">자세한 표</h2>

			<h3 id="t-suspend" class="text-title-1 font-semibold" data-toc="suspend 와 드라이버 Hibern8">suspend 와 드라이버 Hibern8 ({runs.length}회)</h3>
			<CopyTable title="대기 3시간 · suspend 와 드라이버 Hibern8">
				<table>
					<thead>
						<tr><th></th>{#each runs as r (r.label)}<th class="num {r.power}">{#if r.link}<a href={href(r)}>{head(r)[0]}<br />{head(r)[1]}</a>{:else}{head(r)[0]}<br />{head(r)[1]}{/if}</th>{/each}</tr>
					</thead>
					<tbody>
						{#each T_SUSP as [k, fn] (k)}
							<tr><th>{k}</th>{#each runs as r (r.label)}<td class="num {r.power}">{#if fn(r) === ''}<span class="text-caption text-ink-3">기록 없음</span>{:else}{fn(r)}{/if}</td>{/each}</tr>
						{/each}
					</tbody>
				</table>
			</CopyTable>
			<ul class="list-disc space-y-1 pl-5 text-body-3 text-muted-foreground">
				<li>UFS suspend 는 드라이버가 suspend 할 때 보내는 <code>Clear Flag(fBackgroundOpsEn)</code> 를 센 값이에요. {#each batS as r (r.label)}{r.label} 에서 {n0(r.ufsSuspend)}번으로 커널 suspend 성공 {n0(r.suspend?.success)}번과 거의 같아요. {/each}</li>
				<li>드라이버 Hibern8 은 UIC 명령(<code>DME_HIBER_ENTER</code>) 기준이에요. 대부분 runtime suspend 때 나가요.</li>
				<li>suspend 시도 = 측정 전·후 <code>/sys/power/suspend_stats</code> 의 success + fail 차이예요. 실패 단계는 failed_freeze, failed_suspend 의 차이예요.</li>
			</ul>

			<h3 id="t-ah8" class="text-title-1 font-semibold" data-toc="폰 설정과 Auto-Hibern8">폰 설정과 Auto-Hibern8 ({runs.length}회, 추정)</h3>
			<CopyTable title="대기 3시간 · UFS 전원 설정 (sysfs)">
				<table>
					<thead><tr><th>설정</th><th class="num">값</th><th>뜻</th></tr></thead>
					<tbody>{#each D.settings as s (s.k)}<tr><td><code>{s.k}</code></td><td class="num">{s.v}</td><td>{s.note}</td></tr>{/each}</tbody>
				</table>
			</CopyTable>
			<CopyTable title="대기 3시간 · Auto-Hibern8 (추정) 과 드라이버 Hibern8" note="Auto-Hibern8 은 trace 에 명령이 없어서, request 와 mgmt command 가 {f(D.params.ah8IdleMs, 0)}ms 이상 없던 구간(드라이버 Hibern8 구간 제외)으로 셌어요. 시간은 (빈 구간 - {f(D.params.ah8IdleMs, 0)}ms) 의 합이에요.">
				<table>
					<thead>
						<tr><th></th>{#each runs as r (r.label)}<th class="num {r.power}">{head(r)[0]}<br />{head(r)[1]}</th>{/each}</tr>
					</thead>
					<tbody>
						{#each T_AH8 as [k, fn] (k)}
							<tr><th>{k}</th>{#each runs as r (r.label)}<td class="num {r.power}">{fn(r)}</td>{/each}</tr>
						{/each}
					</tbody>
				</table>
			</CopyTable>

			<h3 id="t-burst" class="text-title-1 font-semibold" data-toc="burst 주기">burst 주기 ({withB.length}회)</h3>
			<CopyTable title="대기 3시간 · burst 주기" note="burst = Read·Write·Flush·Discard request 를 시간순으로 놓고 {f(D.params.burstGapSec, 0)}초 이상 빈 곳에서 나눈 묶음. 주기 burst = 시작 간격이 간격 중앙값 ±{f(D.params.periodTolSec, 2)}초인 burst. 구성은 주기 burst 하나에 든 request 평균이에요.">
				<table>
					<thead>
						<tr><th></th>{#each withB as r (r.label)}<th class="num {r.power}">{head(r)[0]}<br />{head(r)[1]}</th>{/each}</tr>
					</thead>
					<tbody>
						{#each T_BURST as [k, fn] (k)}
							<tr><th>{k}</th>{#each withB as r (r.label)}<td class="num {r.power}">{fn(r)}</td>{/each}</tr>
						{/each}
					</tbody>
				</table>
			</CopyTable>
			<ul class="list-disc space-y-1 pl-5 text-body-3 text-muted-foreground">
				{#if wb?.burst}
					{@const c = wb.burst.comp}
					<li>{wb.label}: burst 의 {f(wb.burst.periodPct, 0)}% 가 {f(wb.burst.ibiP50, 1)}초 간격이에요. 하나에 Flush {f(c.F, 1)}, Checkpoint Write {f(c.CK, 1)}, node·meta Write {f(c.NM, 1)}, Discard {f(c.D, 1)}개. burst 안 request 주체는 {@html who(wb.burst.who).map(code).join(', ')} 예요.</li>
				{/if}
				{#if wu?.burst}
					{@const c = wu.burst.comp}
					<li>{wu.label}: burst 의 {f(wu.burst.periodPct, 0)}% 가 {f(wu.burst.ibiP50, 2)}초 간격이에요. 하나에 일반 Write {f(c.W, 1)}, Checkpoint Write {f(c.CK, 1)}, Flush {f(c.F, 1)}개. burst 를 여는 request 는 {@html who(wu.burst.opener).map(code).join(', ')} 가 많아요. {f(wu.burst.ibiP50, 2)}초를 누가 정하는지는 아직 몰라요.</li>
				{/if}
				<li>주체 이름은 kworker, f2fs 스레드, SQL, NetworkService, 제조사 서비스만 보여 줘요. 그 밖의 앱 이름은 이 표에서 뺐어요.</li>
			</ul>

			<h3 id="t-volume" class="text-title-1 font-semibold" data-toc="Volume 과 I/O pattern">Volume 과 I/O pattern ({runs.length}회)</h3>
			<CopyTable title="대기 3시간 · Volume 과 I/O pattern" note="dexopt Write = dex2oat 스레드가 쓴 양. Sequential = 직전 request 끝 LBA 에서 바로 이어진 바이트 비율. DtoD = dispatch 간격, CtoD 0 = 앞 request 가 아직 처리 중일 때 보낸 것.">
				<table>
					<thead>
						<tr><th></th>{#each runs as r (r.label)}<th class="num {r.power}">{#if r.link}<a href={href(r)}>{head(r)[0]}<br />{head(r)[1]}</a>{:else}{head(r)[0]}<br />{head(r)[1]}{/if}</th>{/each}</tr>
					</thead>
					<tbody>
						{#each T_VOL as [k, fn] (k)}
							<tr><th>{k}</th>{#each runs as r (r.label)}<td class="num {r.power}">{fn(r)}</td>{/each}</tr>
						{/each}
					</tbody>
				</table>
			</CopyTable>
			<ul class="list-disc space-y-1 pl-5 text-body-3 text-muted-foreground">
				<li>USB 에서 반복된 것: f2fs Checkpoint Write {f(ratio.ck[0], 0)}~{f(ratio.ck[1], 0)}배, f2fs GC Write 증가({rng(bat, (r) => r.gcMB, 0, 'MB')} → {rng(usb, (r) => r.gcMB, 0, 'MB')}), async Write {rng(usb, (r) => 100 - r.syncPct, 0, '%')}.</li>
				<li>배터리에서 반복된 것: 오래 쉬다 깨서 오는 request(CtoD 200ms 이상) {rng(bat, (r) => r.ctod200, 1, '%')}, Write 는 거의 모두 sync({rng(bat, (r) => r.syncPct, 1, '%')}).</li>
				<li>Read Latency P99 는 USB 가 {rng(usb, (r) => r.dtocP99.R, 2, 'ms')} 로 고르고 배터리는 {rng(bat, (r) => r.dtocP99.R, 2, 'ms')} 로 흔들려요.</li>
			</ul>

			<h3 id="t-method" class="text-title-1 font-semibold" data-toc="측정 방법과 한계">측정 방법과 한계</h3>
			<ul class="list-disc space-y-1 pl-5 text-body-3 text-muted-foreground">
				<li>시나리오: 홈에서 화면을 끄고 3시간. 앞뒤로 폰 대기 상태, 배터리, <code>/sys/power/suspend_stats</code> 를 기록해요.</li>
				<li>수집: fsiotrace(eBPF)가 UFS request 와 mgmt command 를 폰 메모리(<code>/dev</code>)에 쌓고, adb 와 떨어진 session 에서 돌아요. 수집이 UFS 를 깨우거나 잠드는 걸 막지 않아요.</li>
				<li>연결: 모두 무선 adb. USB 측정은 케이블로 전원만 넣었어요. 배터리일 때 폰은 IDLE(deep doze)까지 들어갔고 USB 일 때는 내내 ACTIVE 였어요.</li>
				<li>suspend 기록은 배터리 {batS.length}회, USB {usbS.length}회에만 있어요. 하드웨어가 실제로 잠든 시간(<code>total_hw_sleep</code>)은 이 폰에 없어요.</li>
				<li>USB 측정은 충전 중이라 잔량과 발열도 달라요. Auto-Hibern8 은 추정값이에요. {#each bat.filter((r) => !r.burst) as r (r.label)}{r.label} 는 {f(min(r), 0)}분 측정이라 횟수 대신 분·시간당 값으로 비교하고 burst 분석에서는 뺐어요. {/each}</li>
			</ul>
		</section>

		<footer class="border-t pt-4 text-body-3 text-ink-3">
			측정 {runs.map((r) => r.start).sort()[0]} ~ {runs.map((r) => r.start).sort().at(-1)} · fsiotrace <code>fsio_ufs</code> trace {runs.length}개 · 지표 계산은 분석 사이트와 같은 방식(<code>report/extract.py</code>)이에요.
			<Badge variant="outline" class="ml-1">데이터 {D.generated}</Badge>
		</footer>
	</div>
{/if}

<style>
	.vs-row {
		display: grid;
		grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr) minmax(0, 1fr);
		align-items: stretch;
	}
	.vs-row > div {
		padding: 12px 16px;
		min-width: 0;
		display: flex;
		flex-direction: column;
		justify-content: center;
		overflow-wrap: anywhere;
	}
	.vs-val {
		font-size: 20px;
		font-weight: 700;
		line-height: 1.25;
		font-variant-numeric: tabular-nums;
	}
	.vs-val small {
		display: block;
		font-size: 12.5px;
		font-weight: 500;
		color: var(--ink-3);
	}
	.usb {
		background: color-mix(in oklab, var(--primary) 8%, transparent);
	}
	.step {
		background: var(--card);
		border-radius: 12px;
		padding: 10px 12px;
		font-size: 14.5px;
		line-height: 1.45;
	}
	.arrow {
		text-align: center;
		color: var(--ink-3);
		font-size: 13px;
		line-height: 1;
	}
	.stby :global(td.usb),
	.stby :global(th.usb) {
		background: color-mix(in oklab, var(--primary) 8%, transparent);
	}
	.stby :global(th.usb),
	.stby :global(th.usb a) {
		color: var(--primary);
	}
	.stby :global(tbody th) {
		font-weight: 500;
		color: var(--foreground);
	}
	@media (max-width: 520px) {
		.vs-row > div {
			padding: 10px 8px;
		}
		.vs-val {
			font-size: 15px;
		}
	}
</style>
