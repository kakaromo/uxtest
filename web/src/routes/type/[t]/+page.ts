import man from '../../../../static/data/manifest.json';
import type { EntryGenerator } from './$types';

// 공개 manifest 의 유형 문자로 페이지 틀을 미리 만든다
export const entries: EntryGenerator = () => Object.keys(man.types).map((t) => ({ t }));
