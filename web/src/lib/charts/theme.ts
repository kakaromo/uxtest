// 차트 색·글꼴은 CSS 변수(layout.css 의 TDS 값)에서 읽어 구체 값으로 option 에 넣는다.
// 그래서 HTML 소스로 복사한 차트도 같은 색으로 그려진다.
const css = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

export type Theme = ReturnType<typeof theme>;

export function theme() {
	const font = "'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', sans-serif";
	const mute = css('--ink-3');
	const ink = css('--muted-foreground');
	const fg = css('--foreground');
	const surface = css('--card');
	return {
		font,
		fg,
		ink,
		mute,
		surface,
		line: css('--border'),
		heat0: css('--heat-0'),
		primary: css('--primary'),
		read: css('--read'),
		write: css('--write'),
		ramp: ['--r1', '--r2', '--r3', '--r4', '--r5'].map(css),
		axisLabel: { color: mute, fontFamily: font, fontSize: 11 },
		split: { lineStyle: { color: css('--muted') } },
		tip: {
			backgroundColor: fg,
			borderWidth: 0,
			padding: [8, 12],
			confine: true,
			extraCssText: 'border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,.12)',
			textStyle: { color: surface, fontSize: 12, fontFamily: font }
		},
		legend: { textStyle: { color: ink, fontFamily: font, fontSize: 12 }, itemWidth: 10, itemHeight: 10, icon: 'roundRect' }
	};
}

/** 누적 막대 양 끝만 둥글게 (4px) */
export const ends = (i: number, n: number): number | number[] => (i === 0 ? [4, 0, 0, 4] : i === n - 1 ? [0, 4, 4, 0] : 0);
