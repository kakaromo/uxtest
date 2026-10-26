<script lang="ts">
	// 전체 시나리오 값을 한 줄 점으로 찍고, 이 시나리오만 진하게. "얼마나 큰가"를 한눈에.
	let { vals, v, log = false, fmt }: { vals: number[]; v: number; log?: boolean; fmt: (z: number) => string } = $props();

	const t = (z: number) => (log ? Math.log10(Math.max(z, 0.1)) : z);
	const lo = $derived(Math.min(...vals.map(t)));
	const hi = $derived(Math.max(...vals.map(t)));
	const pos = (z: number) => (hi > lo ? (100 * (t(z) - lo)) / (hi - lo) : 50);
	const minV = $derived(Math.min(...vals));
	const maxV = $derived(Math.max(...vals));
</script>

<div class="relative h-6 w-full" aria-hidden="true">
	<div class="absolute top-1/2 right-0 left-0 h-px bg-border"></div>
	{#each vals as z, i (i)}
		<span class="absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink-4/40" style="left:{pos(z)}%"></span>
	{/each}
	<span class="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary ring-2 ring-card" style="left:{pos(v)}%"></span>
</div>
<div class="flex justify-between text-[11px] text-ink-4 tabular-nums"><span>{fmt(minV)}</span><span>{fmt(maxV)}</span></div>
