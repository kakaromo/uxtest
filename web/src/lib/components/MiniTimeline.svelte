<script lang="ts">
	import * as echarts from 'echarts';
	import { mode } from 'mode-watcher';
	import { theme } from '#lib/charts/theme.js';
	import { miniOption } from '#lib/charts/build.js';

	let { r, w, height = 96 }: { r: number[]; w: number[]; height?: number } = $props();
	let el: HTMLDivElement;
	let c: echarts.ECharts | null = null;
	$effect(() => {
		void mode.current;
		c ??= echarts.init(el, null, { renderer: 'svg' });
		c.setOption(miniOption(theme(), r, w), true);
	});
	$effect(() => {
		const ro = new ResizeObserver(() => c?.resize());
		ro.observe(el);
		return () => {
			ro.disconnect();
			c?.dispose();
			c = null;
		};
	});
</script>

<div bind:this={el} style="height:{height}px" class="w-full"></div>
