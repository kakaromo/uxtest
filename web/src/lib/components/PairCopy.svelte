<script lang="ts">
	// 나란히 놓인 차트 여러 개를 HTML 조각 하나로 복사 (Confluence HTML macro 하나에 붙이기)
	import { toast } from 'svelte-sonner';
	import { Button } from '#lib/components/ui/button/index.js';
	import type { ChartSpec } from '#lib/components/Chart.svelte';
	import { theme } from '#lib/charts/theme.js';
	import { chartsHTML } from '#lib/charts/source.js';
	import { copy } from '#lib/clipboard.js';
	import { CodeXml } from '@lucide/svelte';

	let { items, title, label, class: cls = '' }: { items: { spec: ChartSpec; height: number }[]; title: string; label: string; class?: string } = $props();

	async function run() {
		const th = theme();
		const html = chartsHTML(
			items.map((c) => ({ o: c.spec.option(th), title: c.spec.title, height: c.height })),
			{ title, bg: th.surface, fg: th.fg }
		);
		(await copy(html)) ? toast.success(`차트 ${items.length}개를 HTML 하나로 복사했어요. Confluence HTML macro에 붙이면 돼요`) : toast.error('복사하지 못했어요');
	}
</script>

<div class="flex flex-wrap items-center gap-1 text-body-3 text-ink-3 {cls}">
	<span class="mr-1">HTML 복사 (차트 {items.length}개를 하나로):</span>
	<Button variant="secondary" size="xs" onclick={run}><CodeXml />{label}</Button>
</div>
