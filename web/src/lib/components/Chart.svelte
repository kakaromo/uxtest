<script lang="ts" module>
	import type { Grid } from '#lib/clipboard.js';
	import type { Theme } from '#lib/charts/theme.js';
	export type ChartSpec = {
		title: string;
		/** 순수 함수만 쓴 ECharts option (HTML 소스 복사가 되게) */
		option: (t: Theme) => any;
		/** 차트 데이터 표 (데이터 복사·CSV·소스 보기) */
		data: () => Grid;
		/** 출처 설명 HTML */
		prov?: string;
	};
</script>

<script lang="ts">
	import * as echarts from 'echarts';
	import { mode } from 'mode-watcher';
	import { toast } from 'svelte-sonner';
	import { Button } from '#lib/components/ui/button/index.js';
	import { theme } from '#lib/charts/theme.js';
	import { chartHTML, optionJS } from '#lib/charts/source.js';
	import { copy, copyGrid, download, saveCSV, slug } from '#lib/clipboard.js';
	import { ImageIcon, CodeXml, Table2, FileCode, Download } from '@lucide/svelte';

	let {
		spec,
		height = 300,
		caption = '',
		renderer = 'svg',
		oninit
	}: { spec: ChartSpec; height?: number; caption?: string; renderer?: 'svg' | 'canvas'; oninit?: (c: echarts.ECharts) => void } = $props();

	let el: HTMLDivElement;
	let chart: echarts.ECharts | null = null;
	let opt: any = null;
	let showSrc = $state(false);
	let src = $state<{ grid: Grid; json: string } | null>(null);

	function render() {
		if (!el) return;
		opt = spec.option(theme());
		if (!chart) {
			chart = echarts.init(el, null, { renderer });
			oninit?.(chart);
		}
		chart.setOption(opt, true);
		if (showSrc) fillSrc();
	}

	$effect(() => {
		void mode.current; // 다크 모드 바뀌면 색을 다시 읽어 그린다
		void spec;
		render();
	});
	$effect(() => {
		const ro = new ResizeObserver(() => chart?.resize());
		ro.observe(el);
		return () => {
			ro.disconnect();
			chart?.dispose();
			chart = null;
		};
	});

	function pngURL() {
		const w = el.clientWidth || 800;
		const box = document.createElement('div');
		box.style.cssText = `position:fixed;left:-20000px;top:0;width:${w}px;height:${height}px`;
		document.body.appendChild(box);
		const c = echarts.init(box, null, { renderer: 'canvas', width: w, height });
		c.setOption({ ...opt, animation: false });
		const url = c.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: theme().surface });
		c.dispose();
		box.remove();
		return url;
	}
	async function copyImage() {
		const blob = await (await fetch(pngURL())).blob();
		try {
			await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
			toast.success('차트 이미지를 복사했어요');
		} catch {
			download(`${slug(spec.title)}.png`, blob);
			toast('이 브라우저는 이미지 복사가 막혀 있어 PNG로 저장했어요');
		}
	}
	async function copyHTML() {
		const t = theme();
		const html = chartHTML(opt, { title: spec.title, height, bg: t.surface, fg: t.fg, caption, renderer });
		(await copy(html)) ? toast.success('차트 HTML 소스를 복사했어요. HTML 문서에 붙이면 같은 차트가 떠요') : toast.error('복사하지 못했어요');
	}
	function fillSrc() {
		src = { grid: spec.data(), json: optionJS(opt, 2) };
	}
	function toggleSrc() {
		showSrc = !showSrc;
		if (showSrc) fillSrc();
	}
</script>

<div class="rounded-xl border bg-card p-4">
	<div class="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
		<h4 class="min-w-0 flex-1 text-[14px] font-semibold">{spec.title}</h4>
		<div class="flex flex-wrap gap-1">
			<Button variant="quiet" size="xs" onclick={copyImage} title="차트를 PNG 이미지로 복사"><ImageIcon />Image</Button>
			<Button variant="quiet" size="xs" onclick={copyHTML} title="이 차트만으로 동작하는 HTML 조각(데이터 포함)을 복사"><CodeXml />HTML</Button>
			<Button variant="quiet" size="xs" onclick={() => copyGrid(spec.data(), spec.title, '데이터')} title="차트 데이터를 표로 복사 (엑셀·시트에 붙여넣기)"><Table2 />Data</Button>
			<Button variant="quiet" size="xs" onclick={toggleSrc} aria-pressed={showSrc} title="출처·데이터·설정 보기"><FileCode />Source</Button>
		</div>
	</div>
	<div bind:this={el} style="height:{height}px" class="w-full"></div>
	{#if caption}<p class="mt-2 text-body-3 text-ink-3">{caption}</p>{/if}
	{#if showSrc && src}
		<div class="mt-3 space-y-3 rounded-lg bg-muted p-3 text-body-3">
			{#if spec.prov}<div class="prose-ux text-body-3">{@html spec.prov}</div>{/if}
			<div class="flex flex-wrap items-center gap-2">
				<b>데이터</b><span class="text-ink-3">{src.grid.rows.length}줄 × {src.grid.cols.length}열{src.grid.rows.length > 200 ? ' · 앞 200줄만 표시 (복사·CSV는 전체)' : ''}</span>
				<span class="flex-1"></span>
				<Button variant="secondary" size="xs" onclick={() => saveCSV(src!.grid, spec.title)}><Download />CSV</Button>
				<Button variant="secondary" size="xs" onclick={copyHTML}><CodeXml />Copy HTML</Button>
			</div>
			<div class="max-h-72 overflow-auto rounded-md border bg-card">
				<table class="w-full text-[12px]">
					<thead class="sticky top-0 bg-card"><tr>{#each src.grid.cols as c}<th class="border-b px-2 py-1 text-left font-semibold">{c}</th>{/each}</tr></thead>
					<tbody>
						{#each src.grid.rows.slice(0, 200) as r}
							<tr>{#each r as c}<td class="border-b px-2 py-1 {typeof c === 'number' ? 'num text-right' : ''}">{typeof c === 'number' ? Math.round(c * 1000) / 1000 : c}</td>{/each}</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<details>
				<summary class="cursor-pointer font-semibold">차트 설정 (ECharts option)</summary>
				<pre class="mt-2 max-h-72 overflow-auto rounded-md bg-card p-2 font-mono text-[11px]">{src.json}</pre>
			</details>
		</div>
	{/if}
</div>
