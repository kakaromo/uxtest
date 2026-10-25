<script lang="ts">
	import './layout.css';
	import { onMount } from 'svelte';
	import { ModeWatcher } from 'mode-watcher';
	import { Toaster } from '#lib/components/ui/sonner/index.js';
	import * as Sidebar from '#lib/components/ui/sidebar/index.js';
	import AppSidebar from '#lib/components/AppSidebar.svelte';
	import { app, init } from '#lib/state.svelte.js';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
	onMount(init);
</script>

<svelte:head>
	<title>UX I/O 분석</title>
	<meta name="robots" content="noindex, nofollow" />
</svelte:head>

<ModeWatcher />
<Toaster position="bottom-center" />

<Sidebar.Provider style="--sidebar-width: 17rem;">
	<AppSidebar />
	<Sidebar.Inset class="bg-background">
		<header class="sticky top-0 z-20 flex h-12 items-center gap-2 border-b bg-background/90 px-4 backdrop-blur md:hidden">
			<Sidebar.Trigger aria-label="목차 열기" />
			<span class="text-[15px] font-semibold">UX I/O 분석</span>
		</header>
		<main class="mx-auto w-full max-w-[1200px] px-4 pt-8 pb-24 sm:px-8">
			{#if !app.ready}
				<p class="py-20 text-center text-ink-3">불러오는 중…</p>
			{:else if app.error}
				<p class="py-20 text-center text-destructive">{app.error}</p>
			{:else}
				{@render children()}
			{/if}
		</main>
	</Sidebar.Inset>
</Sidebar.Provider>
