// 표·차트 복사. 표는 text/html(서식 있는 표) + text/plain(TSV)을 함께 넣어
// Excel·Google Sheets·Confluence·Docs 에 붙이면 셀이 그대로 나뉜다.
import { toast } from 'svelte-sonner';

export type Grid = { cols: string[]; rows: (string | number | null)[][] };

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
const cell = (v: unknown) =>
	v == null ? '' : typeof v === 'number' ? String(Math.round(v * 1000) / 1000) : String(v).replace(/\s+/g, ' ').trim();

export const toTSV = (g: Grid) => [g.cols, ...g.rows].map((r) => r.map((c) => cell(c).replace(/\t/g, ' ')).join('\t')).join('\n');
export const toCSV = (g: Grid) =>
	'﻿' +
	[g.cols, ...g.rows]
		.map((r) =>
			r
				.map((c) => {
					const s = cell(c);
					return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
				})
				.join(',')
		)
		.join('\n');

/** 붙여넣기용 서식 표: 테두리·정렬을 인라인 스타일로 */
export function toHTML(g: Grid, title?: string) {
	const th = 'border:1px solid #D1D6DB;padding:6px 10px;background:#F2F4F6;text-align:left;font-weight:600';
	const td = 'border:1px solid #D1D6DB;padding:6px 10px';
	const isNum = (v: unknown) => typeof v === 'number' || (typeof v === 'string' && /^-?[\d,.]+$/.test(v.trim()));
	return (
		(title ? `<p style="font-weight:600">${esc(title)}</p>` : '') +
		`<table style="border-collapse:collapse;font-family:Pretendard,-apple-system,sans-serif;font-size:13px">` +
		`<thead><tr>${g.cols.map((c) => `<th style="${th}">${esc(cell(c))}</th>`).join('')}</tr></thead><tbody>` +
		g.rows
			.map(
				(r) =>
					`<tr>${r.map((c) => `<td style="${td}${isNum(c) ? ';text-align:right' : ''}">${esc(cell(c))}</td>`).join('')}</tr>`
			)
			.join('') +
		'</tbody></table>'
	);
}

function legacy(text: string) {
	const ta = document.createElement('textarea');
	ta.value = text;
	ta.style.cssText = 'position:fixed;left:-9999px;top:0';
	document.body.appendChild(ta);
	ta.select();
	let ok = false;
	try {
		ok = document.execCommand('copy');
	} catch {
		ok = false;
	}
	ta.remove();
	return ok;
}

export async function copy(text: string, html?: string) {
	try {
		if (html && 'ClipboardItem' in window && navigator.clipboard?.write) {
			await navigator.clipboard.write([
				new ClipboardItem({
					'text/plain': new Blob([text], { type: 'text/plain' }),
					'text/html': new Blob([html], { type: 'text/html' })
				})
			]);
			return true;
		}
		await navigator.clipboard.writeText(text);
		return true;
	} catch {
		return legacy(text);
	}
}

export function download(name: string, blob: Blob) {
	const a = document.createElement('a');
	a.href = URL.createObjectURL(blob);
	a.download = name;
	document.body.appendChild(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

export const slug = (s: string) =>
	s.replace(/[^\w가-힣.-]+/g, '_').replace(/^_|_$/g, '').slice(0, 60) || 'data';

/** DOM 표 → Grid. 셀에 data-v 가 있으면 단위 없는 원값을 쓴다. */
export function tableGrid(t: HTMLTableElement): Grid {
	const rows = [...t.querySelectorAll('tr')].map((tr) =>
		[...tr.querySelectorAll('th,td')].map((c) => {
			const v = (c as HTMLElement).dataset.v;
			return v != null ? (isNaN(+v) ? v : +v) : (c as HTMLElement).innerText.replace(/\s+/g, ' ').trim();
		})
	);
	const head = t.tHead ? t.tHead.rows.length : 1;
	return { cols: (rows[head - 1] || []) as string[], rows: rows.slice(head) };
}

export async function copyGrid(g: Grid, title?: string, what = '표') {
	const ok = await copy(toTSV(g), toHTML(g, title));
	if (ok) toast.success(`${what} ${g.rows.length}줄을 복사했어요`);
	else toast.error('복사하지 못했어요. CSV로 받아 주세요');
}

export function saveCSV(g: Grid, name: string) {
	download(`${slug(name)}.csv`, new Blob([toCSV(g)], { type: 'text/csv' }));
}
