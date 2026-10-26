// 페이지 맨 위 요약: 데이터에서 바로 뽑는 결론 문장, 전체 중 순위, 본문 숫자 강조
import type { Row, Run } from './types.js';
import { mb, f } from './fmt.js';

export type Finding = { stat: string; text: string; tone?: 'warn' };

const med = (v: number[]) => {
	const s = [...v].sort((a, b) => a - b);
	return s.length ? s[Math.floor(s.length / 2)] : 0;
};

/** 큰 값이 1위 */
export function rank(all: Row[], get: (r: Row) => number, r: Row) {
	const v = get(r);
	return { k: all.filter((o) => get(o) > v).length + 1, n: all.length };
}

export function findings(row: Row, run: Run | undefined, all: Row[]): Finding[] {
	const out: Finding[] = [];
	const R = row.readMB.med,
		W = row.writeMB.med,
		tot = R + W;
	const wp = tot ? (100 * W) / tot : 0;

	// 1. 방향과 규모
	const big = W >= R ? { k: 'Write', v: W, get: (o: Row) => o.writeMB.med } : { k: 'Read', v: R, get: (o: Row) => o.readMB.med };
	const rk = rank(all, big.get, row);
	const dir = wp >= 80 ? '거의 Write예요' : wp <= 20 ? '거의 Read예요' : 'Read와 Write가 섞여 있어요';
	out.push({ stat: mb(big.v), text: `${big.k}가 전체 ${rk.n}개 중 ${rk.k}번째로 많아요. ${dir} (Write ${f(wp, 0)}%).` });

	// 2. 어느 Step에 몰렸나
	if (run?.steps.length) {
		const st = run.steps.filter((s) => !/^trace_/.test(s.type));
		const sum = st.reduce((p, s) => p + s.readMB + s.writeMB, 0);
		const top = [...st].sort((a, b) => b.readMB + b.writeMB - (a.readMB + a.writeMB))[0];
		if (top && sum > 1 && st.length > 1) {
			const sh = (100 * (top.readMB + top.writeMB)) / sum;
			out.push({ stat: `${f(sh, 0)}%`, text: `'${top.label}' Step에 I/O가 몰려요 (${f(top.s, 0)}~${f(top.e, 0)}초).` });
		}
	}

	// 3. 몰림과 쉼
	out.push({ stat: `${f(row.peakMBs.med, 0)} MB/s`, text: `몰릴 때 Peak throughput이에요. 시간의 ${f(row.idlePct.med, 0)}%는 요청이 없어요.` });

	// 4. 가장 많은 요청 형태
	const s0 = (run?.streams ?? row.rep.streams ?? [])[0];
	if (s0) out.push({ stat: `${f(s0.pct, 0)}%`, text: `가장 많은 형태는 ${s0.seq === 'SEQ' ? 'Sequential' : 'Random'} ${s0.size} ${s0.dir === 'R' ? 'Read' : 'Write'}예요 (바이트 기준).` });

	// 5. Latency: 주된 방향의 p99 를 전체 median 과 비교
	const d = wp >= 50 ? 'W' : 'R';
	const p = row.dtocP99[d].med,
		m = med(all.map((o) => o.dtocP99[d].med).filter((v) => v > 0));
	if (p > 0 && m > 0) {
		const q = p / m;
		const word = q >= 1.5 ? '느린 편이에요' : q <= 0.67 ? '빠른 편이에요' : '보통이에요';
		out.push({ stat: `${f(p, 2)} ms`, text: `${d === 'W' ? 'Write' : 'Read'} Latency p99예요. 전체 median ${f(m, 2)} ms의 ${f(q, 1)}배로 ${word}.`, tone: q >= 1.5 ? 'warn' : undefined });
	}

	// 6. 대기 유형: 깨어남
	if (row.wakesPerMin) out.push({ stat: `${f(row.wakesPerMin.med, 0)}번/분`, text: `UFS가 깨어나는 횟수예요. 가장 긴 Idle은 ${f(row.maxGapSec?.med, 1)}초예요.` });

	// 7. Discard
	if (row.discardMB.med >= 1) out.push({ stat: mb(row.discardMB.med), text: 'Discard가 나갔어요.' });

	// 8. Run 차이
	out.push(
		row.cv > 0.5
			? { stat: `CV ${f(row.cv, 2)}`, text: `Run마다 Volume 차이가 커요. 숫자 하나로 보지 말고 Run comparison을 같이 보세요.`, tone: 'warn' }
			: { stat: `CV ${f(row.cv, 2)}`, text: `Run ${row.repeats}번의 Volume 차이는 작아요. 재현이 잘 돼요.` }
	);
	return out;
}

/** 본문 글자 속 숫자+단위를 굵게. 태그 안(속성)과 <code> 안은 건드리지 않는다. */
const NUM = /(약\s)?(\d[\d,.]*(?:~\d[\d,.]*)?\s?(?:GB|MB\/s|MB|KB|ms|배|%|번\/분|초|분|장|건|개))/g;
export function emph(html: string) {
	let inCode = 0;
	return html
		.split(/(<[^>]+>)/)
		.map((part) => {
			if (part.startsWith('<')) {
				if (/^<code/i.test(part)) inCode++;
				else if (/^<\/code/i.test(part)) inCode--;
				return part;
			}
			return inCode ? part : part.replace(NUM, '<strong class="hl">$1$2</strong>');
		})
		.join('');
}

/** <li> 가 <b> 로 시작하지 않으면 첫 문장을 머리글로 굵게 */
export function headlines(html: string) {
	return html.replace(/<li>(?!\s*<b>)((?:(?!<\/li>)[\s\S])*?요(?:\([^)<]*\))?\.)(?=\s|<\/li>)/g, '<li><b>$1</b>');
}

/** 표 칸 배경 농도 (같은 열 안에서 비교). log=true 면 로그 눈금 */
export function tint(v: number, vals: number[], log = false) {
	const t = (z: number) => (log ? Math.log10(Math.max(z, 0.1)) : z);
	const lo = Math.min(...vals.map(t)),
		hi = Math.max(...vals.map(t));
	const a = hi > lo ? (t(v) - lo) / (hi - lo) : 0;
	return `background: color-mix(in oklab, var(--primary) ${Math.round(a * 30)}%, transparent)`;
}
