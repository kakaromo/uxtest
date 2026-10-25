// static/data/*.enc 복호화. 형식은 scripts/encrypt.mjs 참고 (iv 12B + AES-GCM 암호문, 안은 gzip JSON).
import { asset } from '$app/paths';

export type Manifest = { v: number; iter: number; salt: string; types: Record<string, string[]> };

const KEY_STORE = 'ux-key';
let key: CryptoKey | null = null;
const cache = new Map<string, Promise<unknown>>();

const b64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const toB64 = (b: ArrayBuffer) => btoa(String.fromCharCode(...new Uint8Array(b)));

export async function manifest(): Promise<Manifest> {
	const r = await fetch(asset('data/manifest.json'));
	return r.json();
}

async function derive(pw: string, m: Manifest) {
	const raw = await crypto.subtle.importKey('raw', new TextEncoder().encode(pw), 'PBKDF2', false, ['deriveKey']);
	return crypto.subtle.deriveKey(
		{ name: 'PBKDF2', hash: 'SHA-256', salt: b64(m.salt), iterations: m.iter },
		raw,
		{ name: 'AES-GCM', length: 256 },
		true,
		['decrypt']
	);
}

async function decryptFile(name: string, k: CryptoKey) {
	const buf = new Uint8Array(await (await fetch(asset(`data/${name}.enc` as 'data/manifest.json'))).arrayBuffer());
	const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: buf.slice(0, 12) }, k, buf.slice(12));
	const stream = new Blob([plain]).stream().pipeThrough(new DecompressionStream('gzip'));
	return JSON.parse(await new Response(stream).text());
}

/** 비밀번호로 열기. 맞으면 키를 이 탭(sessionStorage)에 기억한다. */
export async function unlock(pw: string, m: Manifest): Promise<boolean> {
	const k = await derive(pw, m);
	try {
		cache.set('index', Promise.resolve(await decryptFile('index', k)));
	} catch {
		return false;
	}
	key = k;
	try {
		sessionStorage.setItem(KEY_STORE, JSON.stringify({ salt: m.salt, k: toB64(await crypto.subtle.exportKey('raw', k)) }));
	} catch {
		/* 저장이 막힌 브라우저면 새로고침 때 다시 묻는다 */
	}
	return true;
}

/** 이 탭에 저장된 키가 있으면 복원 */
export async function restore(m: Manifest): Promise<boolean> {
	try {
		const s = JSON.parse(sessionStorage.getItem(KEY_STORE) || 'null');
		if (!s || s.salt !== m.salt) return false;
		key = await crypto.subtle.importKey('raw', b64(s.k), 'AES-GCM', false, ['decrypt']);
		await load('index');
		return true;
	} catch {
		key = null;
		cache.clear();
		return false;
	}
}

export function lock() {
	key = null;
	cache.clear();
	try {
		sessionStorage.removeItem(KEY_STORE);
	} catch {
		/* 무시 */
	}
}

export function load<T = any>(name: string): Promise<T> {
	if (!key) return Promise.reject(new Error('locked'));
	if (!cache.has(name)) cache.set(name, decryptFile(name, key));
	return cache.get(name) as Promise<T>;
}
