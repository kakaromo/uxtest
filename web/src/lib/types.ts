// export_web.py 가 만드는 JSON 모양
export type Range = { med: number; min: number; max: number };
export type RW<T> = { R: T; W: T };

export type Row = {
	id: string;
	key: string;
	type: string;
	typeName: string;
	name: string;
	prio: number;
	cache: 'cold' | 'warm' | null;
	description: string;
	repeats: number;
	success: boolean;
	/** 수집 도구 귀속 수정(2026-10-28) 뒤에 잰 측정 */
	toolFixed?: boolean;
	runFile: string;
	steps: { type: string; label: string }[];
	checks: Record<string, { focus: string | null; captured: string | null; launchMs: number[] }>;
	perRun: { repeat: number; readMB: number; writeMB: number; discardMB: number; durSec: number; traceJobId: string }[];
	readMB: Range;
	writeMB: Range;
	discardMB: Range;
	flushN: Range;
	durSec: Range;
	peakMBs: Range;
	qdP99: Range;
	metaPct: Range;
	idlePct: Range;
	rereadPct: Range;
	readN: Range;
	writeN: Range;
	wakesPerMin?: Range;
	h8PerMin?: Range;
	h8Pct?: Range;
	h8ExitMs?: Range;
	queryPerMin?: Range;
	bkopsPerMin?: Range;
	wbCheckPerMin?: Range;
	mgmtN?: Record<string, number>;
	maxGapSec?: Range;
	flushPerSec?: Range;
	seq: RW<Range>;
	dtocP50: RW<Range>;
	dtocP99: RW<Range>;
	size: RW<number[]>;
	dtoc: RW<number[]>;
	gap: number[];
	ctod?: number[];
	flow: number[];
	cv: number;
	rep: { repeat: number; streams?: Stream[] };
	tl?: { readMBs: number[]; writeMBs: number[] };
};
export type Stream = { dir: 'R' | 'W'; size: string; seq: 'SEQ' | 'RND'; pct: number };

export type Jank = {
	scenario: string;
	repeat: number;
	cache: string;
	total: number;
	jank?: { frames: number; readsPerFrame: number; withReadPct: number };
	normal?: { readsPerFrame: number; withReadPct: number };
	frameDurP50?: number;
	frameDurP99?: number;
	gfx?: Record<string, number> | null;
	sec?: [number, number, number][];
};

export type Index = {
	meta: {
		device: string;
		trace: string;
		lbaMaxGB: number;
		buckets: { size: string[]; dtoc: string[]; gap: string[]; ctod?: string[]; flow: string[] };
		qdBuckets: string[];
		generated: string;
	};
	types: Record<string, string>;
	scenarios: Row[];
	jank: Jank[];
};

export type Content = {
	lede: string;
	byline: string;
	takes: string;
	glance: string;
	mgmt?: string;
	mgmtTable?: string;
	method: string;
	limits: string;
	types: Record<string, { tag: string; title: string; body: string }>;
};

export type Step = { i: number; type: string; label: string; s: number; e: number; readMB: number; writeMB: number; n: number; p99: number };
export type Run = {
	repeat: number;
	traceJobId: string;
	cache: string | null;
	durSec: number;
	readMB: number;
	writeMB: number;
	discardMB: number;
	flushN: number;
	readN: number;
	writeN: number;
	peakMBs: number;
	qdP99: number;
	metaPct: number;
	rereadPct: number;
	idlePct: number;
	wakesPerMin: number;
	maxGapSec: number;
	flushPerSec: number;
	seq: RW<number>;
	dtocP50: RW<number>;
	dtocP99: RW<number>;
	size: RW<number[]>;
	dtoc: RW<number[]>;
	gap: number[];
	ctod?: number[];
	flow: number[];
	streams: Stream[];
	procs: { pid: number; name: string; threads: string; readMB: number; writeMB: number }[];
	comms: { comm: string; readMB: number; writeMB: number }[];
	files: { name: string; kind: string; readMB: number; writeMB: number; n: number; lbaSpan: number }[];
	lba: [number, number, 'R' | 'W', number][];
	tl1: { r: number[]; w: number[]; disc: number[]; flush: number[]; qdMax: number[]; qdAvg: number[]; p99R: number[]; p99W: number[] };
	tl100: { r: number[]; w: number[] } | null;
	steps: Step[];
	latSize: RW<([number, number, number, number] | null)[]>;
	latQd: RW<([number, number, number, number] | null)[]>;
	slow: { t: number; dir: 'R' | 'W'; kb: number; lba: number; lun: number; qd: number; dtoc: number; comm: string; file: string }[];
	kinds: { kind: string; readMB: number; writeMB: number }[];
	h8PerMin?: number;
	h8Pct?: number;
	h8ExitMs?: number;
	h8EnterMs?: number;
	queryPerMin?: number;
	bkopsPerMin?: number;
	wbCheckPerMin?: number;
	suspendN?: number;
	exceptionN?: number;
	queryMsP50?: number;
	queryMsP99?: number;
	mgmtN?: Record<string, number>;
};
export type ScenarioDoc = {
	id: string;
	rows: Row[];
	steps: { type: string; label: string }[];
	runFile: string;
	runs: Run[];
	jank: Jank[];
};

/** p-<ID>-<회차>.json: 요청 하나하나 (t 는 앞 점과의 차이 ms, lat 은 µs) */
export type Points = {
	n: number;
	t: number[];
	lba: number[];
	d: string;
	kb: number[];
	qd: number[];
	lat: number[];
	lun?: number[];
	/** UFS 관리 명령: h8 = Hibern8 구간 [시작 초, 끝 초|null], ev = [초, names 번호] */
	mg?: { h8: [number, number | null][]; ev: [number, number][]; names: string[] };
};
