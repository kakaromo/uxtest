// static/data/*.json 읽기 (export_web.py → scripts/copy-data.mjs 가 넣은 것)
import { asset } from '$app/paths';

export type Manifest = { v: number; types: Record<string, string[]> };

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
