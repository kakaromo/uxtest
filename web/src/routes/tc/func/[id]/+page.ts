import man from '../../../../../static/data/manifest.json';
import type { EntryGenerator } from './$types';

// 공개 manifest 의 tcseq 목록(copy-data.mjs 가 tcseq-<id>.json 에서 만든 것)으로 함수 페이지 틀을 미리 만든다
export const entries: EntryGenerator = () => ((man as { tcseq?: string[] }).tcseq ?? []).map((id) => ({ id }));
