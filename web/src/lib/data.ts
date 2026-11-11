// static/data/*.json 읽기 (export_web.py → scripts/copy-data.mjs 가 넣은 것)
import { asset } from '$app/paths';

/** variants: 변형 ID → 원래 시나리오 ID (참고용 항목, 유형 집계에 넣지 않음) */
export type Manifest = { v: number; types: Record<string, string[]>; variants?: Record<string, string>; tcseq?: string[] };

const cache = new Map<string, Promise<unknown>>();

export async function manifest(): Promise<Manifest> {
	return load<Manifest>('manifest');
}

export function load<T = any>(name: string): Promise<T> {
	if (!cache.has(name)) {
		cache.set(
			name,
			fetch(asset(`data/${name}.json` as 'data/manifest.json')).then((r) => {
				if (!r.ok) throw new Error(`${name}: ${r.status}`);
				return r.json();
			})
		);
	}
	return cache.get(name) as Promise<T>;
}
