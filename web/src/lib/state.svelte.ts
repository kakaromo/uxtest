// 사이트 전역 상태: manifest, index·해설
import { manifest, load, type Manifest } from './data.js';
import type { Index, Content } from './types.js';

export const app = $state({
	ready: false,
	error: '',
	man: null as Manifest | null,
	index: null as Index | null,
	content: null as Content | null,
	/** 시나리오 ID → 이름 (사이드바·제목용) */
	names: {} as Record<string, string>
});

export const TYPE_ORDER = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'S'];

export async function init() {
	try {
		[app.man, app.index, app.content] = await Promise.all([manifest(), load<Index>('index'), load<Content>('content')]);
		const names: Record<string, string> = {};
		for (const s of app.index.scenarios) names[s.id] ??= s.name.replace(/^\[UX-fsio\]\s*\S+\s*/, '');
		app.names = names;
	} catch {
		app.error = '데이터를 불러오지 못했어요. 새로고침해 주세요.';
	}
	app.ready = true;
}
