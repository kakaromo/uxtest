// .private/data/*.json (export_web.py 결과) → static/data/*.json + manifest.json
//   node scripts/copy-data.mjs
import { copyFileSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = join(ROOT, '.private/data');
const OUT = join(ROOT, 'static/data');

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });
const files = readdirSync(SRC).filter((f) => f.endsWith('.json'));
for (const f of files) copyFileSync(join(SRC, f), join(OUT, f));

// 사이드바 뼈대·페이지 목록용 유형 → 시나리오 ID
const idx = JSON.parse(readFileSync(join(SRC, 'index.json'), 'utf8'));
const types = {};
for (const s of idx.scenarios) (types[s.type] ??= []).includes(s.id) || types[s.type].push(s.id);
writeFileSync(join(OUT, 'manifest.json'), JSON.stringify({ v: 2, types }, null, 1));
console.log(`복사 ${files.length}개 → static/data/`);
