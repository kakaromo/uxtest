// .private/data/*.json (평문, 커밋 안 함) → static/data/*.enc (암호화, 커밋)
//   UX_SITE_PASSWORD='...' node scripts/encrypt.mjs
// 형식: gzip(JSON) 을 AES-256-GCM 으로 암호화, 파일 = iv(12B) + 암호문.
// 키 = PBKDF2-SHA256(비밀번호, 사이트 salt, 600,000회). salt·반복 수는 공개 manifest.json 에 둔다.
// 비밀번호가 같으면 salt 를 유지해서 브라우저에 저장된 키가 계속 맞게 한다 (--new-salt 로 바꿈).
import { createCipheriv, pbkdf2Sync, randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = join(ROOT, '.private/data');
const OUT = join(ROOT, 'static/data');
const ITER = 600_000;

// 비밀번호: 환경변수가 없으면 터미널에서 화면에 보이지 않게 두 번 묻는다
async function ask(q) {
	process.stdout.write(q);
	process.stdin.setRawMode(true);
	process.stdin.resume();
	let s = '';
	for await (const chunk of process.stdin) {
		for (const ch of chunk.toString('utf8')) {
			if (ch === '\r' || ch === '\n') {
				process.stdin.setRawMode(false);
				process.stdin.pause();
				process.stdout.write('\n');
				return s;
			}
			if (ch === '\u0003') process.exit(130);
			if (ch === '\u007f') s = s.slice(0, -1);
			else s += ch;
		}
	}
	return s;
}
let pw = process.env.UX_SITE_PASSWORD;
if (!pw && process.stdin.isTTY) {
	pw = await ask('사이트 비밀번호: ');
	if ((await ask('한 번 더: ')) !== pw) {
		console.error('두 비밀번호가 달라요.');
		process.exit(1);
	}
}
if (!pw || pw.length < 8) {
	console.error('8자 이상 비밀번호를 넣어 주세요 (UX_SITE_PASSWORD 환경변수 또는 터미널 입력).');
	process.exit(1);
}
mkdirSync(OUT, { recursive: true });
const manPath = join(OUT, 'manifest.json');
const old = existsSync(manPath) ? JSON.parse(readFileSync(manPath, 'utf8')) : null;
const salt = old && !process.argv.includes('--new-salt') ? Buffer.from(old.salt, 'base64') : randomBytes(16);
const key = pbkdf2Sync(pw, salt, ITER, 32, 'sha256');

// 이전 암호문은 지운다 (없어진 시나리오가 남지 않게)
for (const f of readdirSync(OUT)) if (f.endsWith('.enc')) rmSync(join(OUT, f));

let total = 0;
for (const f of readdirSync(SRC).filter((f) => f.endsWith('.json')).sort()) {
	const plain = gzipSync(readFileSync(join(SRC, f)), { level: 9 });
	const iv = randomBytes(12);
	const c = createCipheriv('aes-256-gcm', key, iv);
	const body = Buffer.concat([iv, c.update(plain), c.final(), c.getAuthTag()]);
	writeFileSync(join(OUT, f.replace(/\.json$/, '.enc')), body);
	total += body.length;
}

// 공개 manifest: 사이드바 뼈대용 유형 문자·시나리오 ID 만 (이름·숫자 없음)
const idx = JSON.parse(readFileSync(join(SRC, 'index.json'), 'utf8'));
const types = {};
for (const s of idx.scenarios) (types[s.type] ??= []).includes(s.id) || types[s.type].push(s.id);
writeFileSync(
	manPath,
	JSON.stringify({ v: 1, kdf: 'PBKDF2-SHA256', iter: ITER, salt: salt.toString('base64'), types }, null, 1)
);
console.log(`암호화 ${readdirSync(OUT).filter((f) => f.endsWith('.enc')).length}개, ${(total / 1024 / 1024).toFixed(1)} MB → static/data/`);
