<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { unlock } from '#lib/state.svelte.js';
	import { LockKeyhole } from '@lucide/svelte';

	let pw = $state('');
	let busy = $state(false);
	let err = $state('');

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		if (!pw || busy) return;
		busy = true;
		err = '';
		try {
			if (!(await unlock(pw))) err = '비밀번호가 맞지 않아요.';
		} catch {
			err = '데이터를 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.';
		}
		busy = false;
	}
</script>

<div class="grid min-h-[70vh] place-items-center px-4">
	<form onsubmit={submit} class="w-full max-w-sm rounded-3xl border bg-card p-8 shadow-2">
		<span class="mb-5 grid size-12 place-items-center rounded-2xl bg-accent text-primary"><LockKeyhole /></span>
		<h1 class="text-h2 font-bold">비밀번호를 입력해 주세요</h1>
		<p class="mt-2 text-body-2 text-muted-foreground">측정 데이터와 해설은 암호화되어 있어요. 비밀번호로 이 브라우저에서 풀어서 보여 드려요.</p>
		<label class="mt-6 block text-label-s font-semibold text-muted-foreground" for="pw">비밀번호</label>
		<Input
			id="pw"
			type="password"
			bind:value={pw}
			autocomplete="current-password"
			aria-invalid={!!err}
			class="mt-2 h-12 rounded-md bg-secondary text-body-1 focus-visible:bg-card"
		/>
		{#if err}<p class="mt-2 text-body-3 text-destructive" role="alert">{err}</p>{/if}
		<Button type="submit" size="lg" class="mt-6 w-full" disabled={!pw || busy}>{busy ? '여는 중…' : '열기'}</Button>
		<p class="mt-4 text-caption text-ink-3">탭을 닫으면 다시 물어봐요.</p>
	</form>
</div>
