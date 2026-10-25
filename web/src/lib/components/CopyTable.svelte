<script lang="ts">
	// 표를 감싸 [표 복사][CSV] 도구를 붙인다. 안의 <table> 을 그대로 읽어 html+TSV 로 복사한다.
	import type { Snippet } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { copyGrid, saveCSV, tableGrid } from '#lib/clipboard.js';
	import { Copy, Download } from '@lucide/svelte';

	let { title, note = '', children }: { title: string; note?: string; children: Snippet } = $props();
	let box: HTMLDivElement;
	const grid = () => tableGrid(box.querySelector('table')!);
</script>

<div class="rounded-xl border bg-card">
	<div class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-2.5">
		<h4 class="min-w-0 flex-1 text-[14px] font-semibold">{title}</h4>
		<div class="flex gap-1">
			<Button variant="quiet" size="xs" onclick={() => copyGrid(grid(), title)} title="엑셀·시트·Confluence 에 붙여넣을 수 있게 복사"><Copy />Copy table</Button>
			<Button variant="quiet" size="xs" onclick={() => saveCSV(grid(), title)} title="UTF-8 CSV 로 저장"><Download />CSV</Button>
		</div>
	</div>
	<div bind:this={box} class="ux-table overflow-x-auto">
		{@render children()}
	</div>
	{#if note}<p class="border-t px-4 py-2 text-body-3 text-ink-3">{note}</p>{/if}
</div>

<style>
	.ux-table :global(table) {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}
	.ux-table :global(th) {
		text-align: left;
		font-weight: 600;
		color: var(--muted-foreground);
		background: var(--card);
		padding: 8px 12px;
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
	}
	.ux-table :global(td) {
		padding: 8px 12px;
		border-bottom: 1px solid var(--border);
		vertical-align: top;
	}
	.ux-table :global(tbody tr:last-child td) {
		border-bottom: 0;
	}
	.ux-table :global(tbody tr:hover td) {
		background: var(--background);
	}
	.ux-table :global(.num),
	.ux-table :global(th.num) {
		text-align: right;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.ux-table :global(tr.grp th) {
		background: var(--muted);
		color: var(--foreground);
	}
	.ux-table :global(.rg) {
		color: var(--ink-3);
		font-size: 12px;
		margin-left: 4px;
	}
	.ux-table :global(a) {
		color: var(--primary);
		font-weight: 600;
	}
</style>
