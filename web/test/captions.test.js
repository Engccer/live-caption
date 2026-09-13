import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  createCaptionStore,
  FONT_STEPS, DEFAULT_FONT_SIZE, nextFontSize, loadFontSize, saveFontSize,
} from '../captions.js';

// localStorage를 흉내 낸다. 실패하는 경우까지 시험한다.
function fakeStorage({ throwOnGet = false, throwOnSet = false, initial = {} } = {}) {
  const data = { ...initial };
  return {
    getItem(key) {
      if (throwOnGet) throw new Error('SecurityError');
      return key in data ? data[key] : null;
    },
    setItem(key, value) {
      if (throwOnSet) throw new Error('QuotaExceededError');
      data[key] = String(value);
    },
    get data() { return data; },
  };
}

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

test('기본 크기가 단계 목록 안에 있다', () => {
  assert.ok(FONT_STEPS.includes(DEFAULT_FONT_SIZE));
});

test('단계 목록이 오름차순이다', () => {
  assert.deepEqual(FONT_STEPS, [...FONT_STEPS].sort((a, b) => a - b));
});

test('한 단계씩 오르내린다', () => {
  assert.equal(nextFontSize(28, 1), 34);
  assert.equal(nextFontSize(28, -1), 24);
});

test('목록 양 끝을 넘지 않는다', () => {
  const min = FONT_STEPS[0];
  const max = FONT_STEPS.at(-1);
  assert.equal(nextFontSize(min, -1), min);
  assert.equal(nextFontSize(max, 1), max);
});

test('목록에 없는 크기가 들어와도 가장 가까운 단계에서 움직인다', () => {
  assert.equal(nextFontSize(30, 1), 34);
  assert.equal(nextFontSize(30, -1), 28);
});

test('저장값이 없으면 기본값을 준다', () => {
  assert.equal(loadFontSize(fakeStorage()), DEFAULT_FONT_SIZE);
});

test('저장값이 손상되거나 목록 밖이면 기본값을 준다', () => {
  assert.equal(loadFontSize(fakeStorage({ initial: { 'maldongmu.fontSize': 'abc' } })), DEFAULT_FONT_SIZE);
  assert.equal(loadFontSize(fakeStorage({ initial: { 'maldongmu.fontSize': '999' } })), DEFAULT_FONT_SIZE);
});

test('저장한 값을 그대로 돌려준다', () => {
  const storage = fakeStorage();
  saveFontSize(storage, 40);
  assert.equal(loadFontSize(storage), 40);
});

test('저장소가 막혀 있어도 앱이 죽지 않는다', () => {
  // 사파리 비공개 모드에서 실제로 일어난다.
  assert.equal(loadFontSize(fakeStorage({ throwOnGet: true })), DEFAULT_FONT_SIZE);
  assert.doesNotThrow(() => saveFontSize(fakeStorage({ throwOnSet: true }), 40));
});

test('storage가 아예 없어도 죽지 않는다', () => {
  assert.equal(loadFontSize(undefined), DEFAULT_FONT_SIZE);
  assert.doesNotThrow(() => saveFontSize(undefined, 40));
});
