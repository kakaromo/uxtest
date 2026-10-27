// 페이지 공용 도우미
import type { Row } from './types.js';
import { app } from './state.svelte.js';

export const label = (r: Row) => r.id + (r.cache && (r.id === 'G1' || r.id === 'G2' || r.id === 'G3') ? ` ${r.cache}` : '');
export const rows = () => app.index?.scenarios ?? [];
export const rowsOf = (t: string) => rows().filter((r) => r.type === t);
export const rowOf = (id: string) => rows().find((r) => r.id === id);
export const nameOf = (r: Row) => r.name.replace(/^\[UX-fsio\]\s*\S+\s*/, '');
/** 차트 축·점 라벨: ID 대신 시나리오 이름 (갤러리 cold·warm 은 뒤에 붙임) */
export const cname = (r: Row) => nameOf(r) + (r.cache && (r.id === 'G1' || r.id === 'G2' || r.id === 'G3') ? ` ${r.cache}` : '');

/** 같은 조건만 바꾼 비교 쌍 (유형 페이지·시나리오 페이지에서 씀) */
export const PAIRS: { a: string; b: string; what: string }[] = [
	{ a: 'A1', b: 'A6', what: 'Chrome 강제 종료 뒤 실행 ↔ 날씨 앱 데이터 지운 뒤 첫 실행' },
	{ a: 'A2', b: 'A4', what: '가벼운 앱 cold start ↔ 무거운 앱(지도·Facebook·Instagram)' },
	{ a: 'A3', b: 'A7', what: '세 앱 warm 전환 ↔ 한 앱 홈 왕복' },
	{ a: 'B1', b: 'B1i', what: '일반 탭 ↔ 시크릿 탭 (같은 위키 문서)' },
	{ a: 'B1', b: 'B5', what: '글 위주 문서 ↔ 이미지 200여 개 문서' },
	{ a: 'C1', b: 'C3', what: '스트리밍 재생 ↔ 로컬 영상 재생' },
	{ a: 'C4a', b: 'C4b', what: 'YouTube 360p ↔ 1080p' },
	{ a: 'C3', b: 'C7', what: '로컬 영상 처음부터 재생 ↔ 진행 막대로 건너뛰기' },
	{ a: 'D1', b: 'D7', what: '후면 사진 ↔ 전면 사진' },
	{ a: 'D3', b: 'D5', what: '동영상 1080p ↔ 4K (30초)' },
	{ a: 'D3', b: 'D4', what: '동영상 30초 ↔ 2분' },
	{ a: 'E2', b: 'E7', what: '셸 복사 ↔ 파일 관리자 복사' },
	{ a: 'E2', b: 'E8', what: '파일 복사 ↔ Chrome 다운로드' },
	{ a: 'G2', b: 'G4', what: '뷰어 0.5초 간격 ↔ 0.15초 간격' },
	{ a: 'S1', b: 'S2', what: '화면 꺼짐 자연 대기 ↔ 강제 deep doze' },
	{ a: 'S4', b: 'S1', what: '화면 켜진 홈 ↔ 화면 꺼짐' }
];
