import man from '../../../../static/data/manifest.json';
import type { EntryGenerator } from './$types';

export const entries: EntryGenerator = () => Object.values(man.types).flat().map((id) => ({ id }));
