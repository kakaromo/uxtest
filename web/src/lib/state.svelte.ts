// 사이트 전역 상태: 잠금 해제 여부, 공개 manifest, 복호화한 index·해설
import { manifest, unlock as doUnlock, restore, lock as doLock, load, type Manifest } from './crypto.js';
import type { Index, Content } from './types.js';

export const app = $state({
	ready: false,
	unlocked: false,
	man: null as Manifest | null,
	index: null as Index | null,
	content: null as Content | null,
	/** 시나리오 ID → 이름 (사이드바·제목용) */
	names: {} as Record<string, string>
});

export const TYPE_ORDER = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'S'];

async function opened() {
	app.index = await load<Index>('index');
	app.content = await load<Content>('content');
	const names: Record<string, string> = {};
	for (const s of app.index.scenarios) names[s.id] ??= s.name.replace(/^\[UX-fsio\]\s*\S+\s*/, '');
	app.names = names;
	app.unlocked = true;
}

export async function init() {
	app.man = await manifest();
	if (await restore(app.man)) await opened();
	app.ready = true;
}

export async function unlock(pw: string) {
	if (!app.man) return false;
	if (!(await doUnlock(pw, app.man))) return false;
	await opened();
	return true;
}

export function lock() {
	doLock();
	app.unlocked = false;
	app.index = null;
	app.content = null;
	app.names = {};
}
