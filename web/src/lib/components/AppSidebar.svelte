<script lang="ts">
	// 왼쪽 사이드 목차: 위는 사이트 목차(유형 → 시나리오), 아래는 이 페이지 목차(h2·h3, 스크롤 위치 강조)
	import { page } from '$app/state';
	import { afterNavigate } from '$app/navigation';
	import { tick } from 'svelte';
	import { resolve } from '$app/paths';
	import * as Sidebar from '#lib/components/ui/sidebar/index.js';
	import * as Collapsible from '#lib/components/ui/collapsible/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { app, TYPE_ORDER } from '#lib/state.svelte.js';
	import { toggleMode } from 'mode-watcher';
	import { ChevronRight, House, Moon, Sun, HardDrive, FlaskConical } from '@lucide/svelte';

	const sidebar = Sidebar.useSidebar();
	let heads = $state<{ id: string; text: string; level: number }[]>([]);
	let active = $state('');

	const curType = $derived(
		page.params.t ?? (page.params.id ? TYPE_ORDER.find((t) => app.man?.types[t]?.includes(page.params.id!)) : undefined)
	);
	const types = $derived(TYPE_ORDER.filter((t) => app.man?.types[t]));

	let io: IntersectionObserver | null = null;
	async function scan() {
		await tick();
		await new Promise((r) => setTimeout(r, 60));
		const els = [...document.querySelectorAll<HTMLElement>('main h2[id], main h3[id]')];
		heads = els.map((e) => ({ id: e.id, text: e.dataset.toc || e.innerText, level: e.tagName === 'H2' ? 2 : 3 }));
		io?.disconnect();
		io = new IntersectionObserver(
			(es) => {
				const vis = es.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
				if (vis[0]) active = vis[0].target.id;
			},
			{ rootMargin: '0px 0px -70% 0px' }
		);
		els.forEach((e) => io!.observe(e));
	}
	afterNavigate(scan);
	// 데이터가 늦게 그려지는 페이지(복호화 뒤)도 다시 읽는다
	$effect(() => {
		void app.ready;
		void page.url.pathname;
		const mo = new MutationObserver(() => {
			const n = document.querySelectorAll('main h2[id], main h3[id]').length;
			if (n !== heads.length) scan();
		});
		const main = document.querySelector('main');
		if (main) mo.observe(main, { childList: true, subtree: true });
		return () => mo.disconnect();
	});

	function go(id: string) {
		document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
		history.replaceState(history.state, '', '#' + id);
		if (sidebar.isMobile) sidebar.setOpenMobile(false);
	}
	const close = () => sidebar.isMobile && sidebar.setOpenMobile(false);
</script>

<Sidebar.Root>
	<Sidebar.Header class="gap-1 px-3 pt-4">
		<a href={resolve('/')} onclick={close} class="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-sidebar-accent">
			<span class="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground"><HardDrive class="size-4" /></span>
			<span class="leading-tight">
				<b class="block text-[15px]">UX I/O 분석</b>
				<span class="text-caption text-ink-3">CPH2749 · UFS · fsiotrace</span>
			</span>
		</a>
	</Sidebar.Header>

	<Sidebar.Content>
		<Sidebar.Group>
			<Sidebar.GroupLabel>보고서</Sidebar.GroupLabel>
			<Sidebar.Menu>
				<Sidebar.MenuItem>
					<Sidebar.MenuButton isActive={page.route.id === '/'}>
						{#snippet child({ props })}
							<a href={resolve('/')} onclick={close} {...props}><House />홈 · 핵심 결론</a>
						{/snippet}
					</Sidebar.MenuButton>
				</Sidebar.MenuItem>
				<Sidebar.MenuItem>
					<Sidebar.MenuButton isActive={page.route.id === '/tc'}>
						{#snippet child({ props })}
							<a href={resolve('/tc')} onclick={close} {...props}><FlaskConical />TC 검증</a>
						{/snippet}
					</Sidebar.MenuButton>
				</Sidebar.MenuItem>
				{#each types as t (t)}
					<Collapsible.Root open={curType === t} class="group/collapsible">
						<Sidebar.MenuItem>
							<Sidebar.MenuButton isActive={page.route.id === '/type/[t]' && page.params.t === t}>
								{#snippet child({ props })}
									<a href={resolve('/type/[t]', { t })} onclick={close} {...props}>
										<span class="grid size-5 place-items-center rounded-xs bg-accent text-[11px] font-bold text-accent-foreground">{t}</span>
										<span class="truncate">{app.index?.types[t] ?? '유형 ' + t}</span>
									</a>
								{/snippet}
							</Sidebar.MenuButton>
							<Collapsible.Trigger>
								{#snippet child({ props })}
									<Sidebar.MenuAction {...props} class="transition-transform data-[state=open]:rotate-90" aria-label="{t} 시나리오 펼치기">
										<ChevronRight />
									</Sidebar.MenuAction>
								{/snippet}
							</Collapsible.Trigger>
							<Collapsible.Content>
								<Sidebar.MenuSub>
									{#each app.man?.types[t] ?? [] as id (id)}
										<Sidebar.MenuSubItem>
											<Sidebar.MenuSubButton isActive={page.params.id === id}>
												{#snippet child({ props })}
													<a href={resolve('/s/[id]', { id })} onclick={close} {...props}>
														<span class="w-8 shrink-0 font-semibold tabular-nums">{id}</span>
														<span class="truncate text-ink-3">{app.names[id] ?? ''}</span>
													</a>
												{/snippet}
											</Sidebar.MenuSubButton>
										</Sidebar.MenuSubItem>
									{/each}
								</Sidebar.MenuSub>
							</Collapsible.Content>
						</Sidebar.MenuItem>
					</Collapsible.Root>
				{/each}
			</Sidebar.Menu>
		</Sidebar.Group>

		{#if heads.length}
			<Sidebar.Group>
				<Sidebar.GroupLabel>이 페이지</Sidebar.GroupLabel>
				<nav class="flex flex-col border-l border-sidebar-border pl-1 ml-2" aria-label="이 페이지 목차">
					{#each heads as h (h.id)}
						<a
							href={'#' + h.id}
							onclick={(e) => {
								e.preventDefault();
								go(h.id);
							}}
							class="-ml-[5px] truncate border-l-2 py-1 text-[13px] transition-colors {h.level === 3 ? 'pl-6' : 'pl-3'} {active === h.id
								? 'border-primary font-semibold text-primary'
								: 'border-transparent text-sidebar-foreground/80 hover:text-sidebar-foreground'}">{h.text}</a
						>
					{/each}
				</nav>
			</Sidebar.Group>
		{/if}
	</Sidebar.Content>

	<Sidebar.Footer class="flex-row gap-1 px-3 pb-3">
		<Button variant="quiet" size="sm" onclick={toggleMode} title="밝게·어둡게">
			<Sun class="dark:hidden" /><Moon class="hidden dark:block" />화면 모드
		</Button>
	</Sidebar.Footer>
	<Sidebar.Rail />
</Sidebar.Root>
