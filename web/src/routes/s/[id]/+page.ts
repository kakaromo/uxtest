import man from '../../../../static/data/manifest.json';
import type { EntryGenerator } from './$types';

// 변형(참고용 항목, 예: S5-usb)도 같은 시나리오 페이지 틀을 쓴다
const variants: Record<string, string> = (man as { variants?: Record<string, string> }).variants ?? {};
export const entries: EntryGenerator = () => [...Object.values(man.types).flat(), ...Object.keys(variants)].map((id) => ({ id }));
