import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createCaptionStore } from '../captions.js';

test('확정 문단이 넣은 순서대로 쌓인다', () => {
  const store = createCaptionStore();
  store.appendFinal('첫 번째 발언입니다');
  store.appendFinal('두 번째 발언입니다');
  assert.deepEqual(store.getState().finals, ['첫 번째 발언입니다', '두 번째 발언입니다']);
});

test('중간 결과는 누적되지 않고 교체된다', () => {
  const store = createCaptionStore();
  store.setInterim('오늘 회의');
  store.setInterim('오늘 회의는 세 시에');
  assert.equal(store.getState().interim, '오늘 회의는 세 시에');
});

test('확정이 들어오면 중간 결과를 비운다', () => {
  const store = createCaptionStore();
  store.setInterim('말하는 중');
  store.appendFinal('말하는 중이었습니다');
  assert.equal(store.getState().interim, '');
});

test('빈 문자열과 공백뿐인 확정은 무시한다', () => {
  const store = createCaptionStore();
  store.appendFinal('');
  store.appendFinal('   ');
  store.appendFinal('\n\t');
  assert.deepEqual(store.getState().finals, []);
});

test('확정 문단의 앞뒤 공백을 다듬는다', () => {
  const store = createCaptionStore();
  store.appendFinal('  다듬어진 문장  ');
  assert.deepEqual(store.getState().finals, ['다듬어진 문장']);
});

test('toText는 확정 문단만 줄바꿈으로 잇는다', () => {
  const store = createCaptionStore();
  store.appendFinal('첫 줄');
  store.appendFinal('둘째 줄');
  store.setInterim('아직 확정 안 된 말');
  assert.equal(store.toText(), '첫 줄\n둘째 줄');
});

test('clear는 전부 비운다', () => {
  const store = createCaptionStore();
  store.appendFinal('지워질 문장');
  store.setInterim('이것도');
  store.clear();
  assert.deepEqual(store.getState(), { finals: [], interim: '' });
});

test('getState가 돌려준 배열을 바꿔도 저장소가 오염되지 않는다', () => {
  const store = createCaptionStore();
  store.appendFinal('원본');
  store.getState().finals.push('침입자');
  assert.deepEqual(store.getState().finals, ['원본']);
});

test('빈 확정이 와도 중간 결과는 비운다', () => {
  // 발화가 끝났는데 "말하는 중" 문장이 화면에 남으면
  // 아무도 말하지 않는 회의실에서 누가 말하는 것처럼 보인다.
  const store = createCaptionStore();
  store.setInterim('사라져야 하는 말');
  store.appendFinal('   ');
  assert.equal(store.getState().interim, '');
});
