// 숫자 표기
export const mb = (v: number | null | undefined) =>
	v == null ? '–' : v >= 1000 ? `${(v / 1000).toFixed(2)} GB` : `${v.toFixed(v < 10 ? 1 : 0)} MB`;
export const n0 = (v: number | null | undefined) => (v == null ? '–' : Math.round(v).toLocaleString('ko-KR'));
export const f = (v: number | null | undefined, d = 1) => (v == null ? '–' : v.toFixed(d));
export const pct = (v: number | null | undefined, d = 0) => (v == null ? '–' : `${v.toFixed(d)}%`);
export const sec = (v: number) => (v >= 120 ? `${(v / 60).toFixed(v >= 600 ? 0 : 1)}분` : `${v.toFixed(0)}초`);
export const shortName = (name: string) => name.replace(/^\[UX-fsio\]\s*\S+\s*/, '');
export const ratio = (a: number, b: number) => (b > 0 ? a / b : 0);
export const x = (v: number) => (v >= 10 ? `${v.toFixed(0)}배` : `${v.toFixed(1)}배`);
