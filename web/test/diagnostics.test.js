import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDiagnostics, describeEnvironment, checkAvailability } from '../diagnostics.js';

const status = (value) => ({ type: 'status', status: value });
const environment = { browser: 'Safari 26.6', os: 'iOS 26.6', device: 'iPhone', width: 390, height: 844, standalone: true };
const report = (d) => d.toText({ environment, fontSize: 34, availability: '미지원' });

test('끊김 간격, 재연결 공백, 결과 재수신을 서로 구분한다', () => {
  const d = createDiagnostics({ startedAt: 1000, date: '2026-09-13' });
  d.record(status('listening'), 1200);
  d.record({ type: 'final', text: '가상 발화' }, 3000);
  d.record(status('recovering'), 41100);
  d.record(status('listening'), 46300);
  d.record({ type: 'interim', text: '가상 중간 결과' }, 47000);
  d.record(status('recovering'), 81400);
  d.record(status('listening'), 86400);
  d.record(status('stopping'), 90000);
  d.record(status('idle'), 91000);
  const text = report(d);
  assert.match(text, /세션 1분 30초, 확정 1건/);
  assert.match(text, /끊김 2회 \(간격 40.1s 40.3s\)/);
  assert.match(text, /재연결 성공 2 \/ 실패 0 \/ 중단 0/);
  assert.match(text, /최대 재연결 공백 5.2초/);
  assert.match(text, /재연결 후 결과 수신 1 \/ 미확인 1/);
});

test('사용자 정지는 끊김이나 재연결 실패로 세지 않는다', () => {
  const d = createDiagnostics({ startedAt: 0, date: '2026-09-13' });
  d.record(status('listening'), 10);
  d.record(status('recovering'), 40000);
  d.requestStop();
  d.record(status('idle'), 42000);
  assert.match(report(d), /재연결 성공 0 \/ 실패 0 \/ 중단 1/);
  assert.match(report(d), /최대 재연결 공백 해당 없음/);
});

test('복구 포기로 끝나면 실패, 같은 recovering 중복 통지는 한 번만 센다', () => {
  const d = createDiagnostics({ startedAt: 0, date: '2026-09-13' });
  d.record(status('recovering'), 40000);
  d.record(status('recovering'), 40100);
  d.record({ type: 'error', kind: 'unknown', message: '시작 실패' }, 46250);
  d.record(status('idle'), 46250);
  assert.match(report(d), /끊김 1회/);
  assert.match(report(d), /재연결 성공 0 \/ 실패 1 \/ 중단 0/);
});

test('정지 중 마지막 확정은 포함하고 종료 뒤 지각 사건은 무시한다', () => {
  const d = createDiagnostics({ startedAt: 0, date: '2026-09-13' });
  d.record(status('stopping'), 1000);
  d.record({ type: 'final', text: '마지막 발화' }, 1200);
  d.record(status('idle'), 2000);
  const before = report(d);
  d.record({ type: 'final', text: '버린 발화' }, 5000);
  d.record(status('idle'), 6000);
  assert.equal(report(d), before);
  assert.match(before, /세션 0분 2초, 확정 1건/);
});

test('발화와 오류 메시지를 읽거나 보관하지 않고 오류 kind는 허용 목록만 센다', () => {
  const d = createDiagnostics({ startedAt: 0, date: '2026-09-13' });
  const forbidden = () => { throw new Error('발화 내용 접근 금지'); };
  d.record({ type: 'final', get text() { return forbidden(); } }, 10);
  d.record({ type: 'interim', get text() { return forbidden(); } }, 20);
  for (const kind of ['unknown', 'no-speech', 'unknown', '비밀 발화']) {
    d.record({ type: 'error', kind, get message() { return forbidden(); } }, 30);
  }
  d.record(status('idle'), 40);
  assert.match(report(d), /오류\(kind\): no-speech 1, unknown 3/);
  assert.doesNotMatch(report(d), /비밀|발화/);
});

test('새 세션은 이전 확정 건수와 끊김을 물려받지 않는다', () => {
  const first = createDiagnostics({ startedAt: 0, date: '2026-09-13' });
  first.record({ type: 'final' }, 100);
  const next = createDiagnostics({ startedAt: 10000, date: '2026-09-13' });
  next.record(status('idle'), 11000);
  assert.match(report(next), /확정 0건/);
  assert.match(report(next), /끊김 0회 \(간격 없음\)/);
  assert.match(report(next), /오류\(kind\): 없음/);
});

test('환경과 설정을 복사하되 알 수 없는 UA 원문을 내보내지 않는다', () => {
  const d = createDiagnostics({ startedAt: 0, date: '2026-09-13' });
  d.record(status('idle'), 0);
  assert.match(report(d), /Safari 26.6, iOS 26.6, iPhone, 화면 390x844, 홈화면앱 예/);
  assert.match(report(d), /글자 크기 34px, 온디바이스 가능 여부\(ko-KR\): 미지원/);
  assert.equal(describeEnvironment({ userAgent: '비밀 원문' }).browser, '정보 없음');
  assert.doesNotMatch(JSON.stringify(describeEnvironment({ userAgent: '비밀 원문' })), /비밀/);
});

test('Safari와 iOS Chrome, Android, 데스크톱을 UA 표기 범위에서 구분한다', () => {
  const cases = [
    ['Mozilla/5.0 (iPhone; CPU iPhone OS 26_6 like Mac OS X) Version/26.6 Mobile/15E148 Safari/604.1', 'Safari 26.6', 'iOS 26.6', 'iPhone'],
    ['Mozilla/5.0 (iPhone; CPU iPhone OS 26_6 like Mac OS X) CriOS/152.0.0.0 Mobile/15E148 Safari/604.1', 'Chrome 152.0.0.0', 'iOS 26.6', 'iPhone'],
    ['Mozilla/5.0 (Linux; Android 16; Pixel 9) Chrome/152.0.0.0 Mobile Safari/537.36', 'Chrome 152.0.0.0', 'Android 16', 'Android'],
    ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Version/26.6 Safari/605.1.15', 'Safari 26.6', 'macOS 10.15.7', 'Mac'],
    ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152.0 Safari/537.36 Edg/152.0', 'Edge 152.0', 'Windows NT 10.0', 'PC'],
  ];
  for (const [userAgent, browser, os, device] of cases) {
    const actual = describeEnvironment({ userAgent });
    assert.deepEqual([actual.browser, actual.os, actual.device], [browser, os, device]);
  }
});

test('온디바이스 조회는 한국어 로컬 가용성만 확인하며 미지원과 조회 실패를 구분한다', async () => {
  assert.equal(await checkAvailability(undefined), '미지원');
  assert.equal(await checkAvailability({}), '미지원');
  assert.equal(await checkAvailability({ available() { throw new Error('민감 메시지'); } }), '조회 실패');
  assert.equal(await checkAvailability({ available: async () => '임의 응답' }), '정보 없음');
  for (const value of ['available', 'unavailable', 'downloadable', 'downloading']) {
    const ctor = { available(options) {
      assert.equal(this, ctor);
      assert.deepEqual(options, { langs: ['ko-KR'], processLocally: true });
      return Promise.resolve(value);
    } };
    assert.equal(await checkAvailability(ctor), value);
  }
});
