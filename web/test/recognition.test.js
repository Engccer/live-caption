import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createFakeTimers, createFakeRecognition } from './helpers/fake-speech.js';
import { createRecognizer } from '../recognition.js';

// 테스트마다 반복되는 배선을 한 곳에 모은다.
function setup({ onStart } = {}) {
  const clock = createFakeTimers();
  const { FakeSpeechRecognition, instances } = createFakeRecognition({ onStart });
  const events = [];
  const recognizer = createRecognizer({
    SpeechRecognitionCtor: FakeSpeechRecognition,
    onEvent: (event) => events.push(event),
    timers: clock.timers,
  });
  return { clock, instances, events, recognizer };
}

test('시작하면 상태가 listening이 된다', () => {
  const { recognizer, events } = setup();
  recognizer.start();
  assert.equal(recognizer.getStatus(), 'listening');
  assert.deepEqual(events, [{ type: 'status', status: 'listening' }]);
});

test('확정 결과는 final, 중간 결과는 interim 사건이 된다', () => {
  const { recognizer, instances, events } = setup();
  recognizer.start();
  events.length = 0;

  instances[0].emitResult([{ text: '안녕하세요', isFinal: true }]);
  instances[0].emitResult([{ text: '오늘 회의는', isFinal: false }]);

  assert.deepEqual(events, [
    { type: 'final', text: '안녕하세요' },
    { type: 'interim', text: '오늘 회의는' },
  ]);
});

test('한 사건에 확정과 중간이 섞여 오면 둘 다 낸다', () => {
  const { recognizer, instances, events } = setup();
  recognizer.start();
  events.length = 0;

  instances[0].emitResult([
    { text: '첫 문장입니다', isFinal: true },
    { text: '두 번째 문장은', isFinal: false },
  ]);

  assert.deepEqual(events, [
    { type: 'final', text: '첫 문장입니다' },
    { type: 'interim', text: '두 번째 문장은' },
  ]);
});

test('resultIndex 앞의 결과는 다시 내지 않는다', () => {
  const { recognizer, instances, events } = setup();
  recognizer.start();
  instances[0].emitResult([{ text: '이미 처리됨', isFinal: true }]);
  events.length = 0;

  // 브라우저는 results 배열을 누적해 보내고 resultIndex로 새 것을 가리킨다.
  instances[0].emitResult(
    [{ text: '이미 처리됨', isFinal: true }, { text: '새 문장', isFinal: true }],
    1,
  );

  assert.deepEqual(events, [{ type: 'final', text: '새 문장' }]);
});

test('사용자가 정지하지 않았는데 끊기면 recovering이 되고 5초 뒤 다시 시작한다', () => {
  const { recognizer, instances, events, clock } = setup();
  recognizer.start();
  events.length = 0;

  instances[0].emitEnd();
  assert.equal(recognizer.getStatus(), 'recovering');
  assert.deepEqual(events, [{ type: 'status', status: 'recovering' }]);

  clock.advance(4999);
  assert.equal(instances.length, 1, '5초 전에는 새 인식을 만들지 않는다');

  clock.advance(1);
  assert.equal(instances.length, 2);
  assert.equal(recognizer.getStatus(), 'listening');
});

test('사용자가 정지하면 다시 시작하지 않는다', () => {
  const { recognizer, instances, clock } = setup();
  recognizer.start();
  recognizer.stop();

  clock.advance(60000);
  assert.equal(instances.length, 1);
  assert.equal(recognizer.getStatus(), 'idle');
});

test('복구를 반복해도 인식이 계속 이어진다', () => {
  const { recognizer, instances, clock } = setup();
  recognizer.start();

  for (let i = 0; i < 3; i++) {
    instances.at(-1).emitEnd();
    clock.advance(5000);
  }

  assert.equal(instances.length, 4);
  assert.equal(recognizer.getStatus(), 'listening');
});
