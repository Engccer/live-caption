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

test('start()가 InvalidStateError를 던지면 250ms 뒤 다시 시도한다', () => {
  // 2회차 start()만 던지게 한다.
  const { recognizer, instances, clock } = setup({
    onStart: (nth) => (nth === 2 ? 'throw-invalid-state' : undefined),
  });
  recognizer.start();
  instances[0].emitEnd();
  clock.advance(5000);          // 2회차 시도 -> 던짐

  assert.equal(recognizer.getStatus(), 'recovering');
  clock.advance(250);           // 3회차 시도 -> 성공
  assert.equal(recognizer.getStatus(), 'listening');
});

test('start()가 계속 실패하면 5회까지 시도하고 오류를 낸다', () => {
  const { recognizer, instances, events, clock } = setup({
    onStart: (nth) => (nth >= 2 ? 'throw-invalid-state' : undefined),
  });
  recognizer.start();
  events.length = 0;
  instances[0].emitEnd();

  clock.advance(5000 + 250 * 6);

  const errors = events.filter((e) => e.type === 'error');
  assert.equal(errors.length, 1);
  assert.equal(errors[0].kind, 'unknown');
  assert.equal(recognizer.getStatus(), 'idle');
});

test('버린 인식 객체의 뒤늦은 결과는 무시한다', () => {
  const { recognizer, instances, events, clock } = setup();
  recognizer.start();
  const dead = instances[0];

  dead.emitEnd();
  clock.advance(5000);          // 새 인식으로 교체됨
  events.length = 0;

  dead.emitResult([{ text: '유령 문장', isFinal: true }]);
  dead.emitEnd();

  assert.deepEqual(events, [], '버린 객체의 사건은 새 세션에 닿지 않는다');
  assert.equal(recognizer.getStatus(), 'listening');
});

test('정지한 뒤 옛 인식이 끊겨도 다시 시작하지 않는다', () => {
  const { recognizer, instances, clock } = setup();
  recognizer.start();
  const dead = instances[0];
  recognizer.stop();

  dead.emitEnd();
  clock.advance(10000);

  assert.equal(instances.length, 1);
  assert.equal(recognizer.getStatus(), 'idle');
});

test('마이크 거부는 permission-denied로 매핑되고 재시작하지 않는다', () => {
  const { recognizer, instances, events, clock } = setup();
  recognizer.start();
  events.length = 0;

  instances[0].emitError('not-allowed');
  instances[0].emitEnd();
  clock.advance(30000);

  const errors = events.filter((e) => e.type === 'error');
  assert.equal(errors[0].kind, 'permission-denied');
  assert.equal(instances.length, 1, '같은 오류가 무한 반복되므로 재시작하지 않는다');
  assert.equal(recognizer.getStatus(), 'idle');
});

test('no-speech는 오류로 내되 복구 흐름을 막지 않는다', () => {
  const { recognizer, instances, events, clock } = setup();
  recognizer.start();
  events.length = 0;

  instances[0].emitError('no-speech');
  instances[0].emitEnd();
  clock.advance(5000);

  assert.equal(events.find((e) => e.type === 'error').kind, 'no-speech');
  assert.equal(instances.length, 2, '조용했을 뿐이므로 계속 듣는다');
});

test('모르는 오류 코드는 unknown이 된다', () => {
  const { recognizer, instances, events } = setup();
  recognizer.start();
  events.length = 0;
  instances[0].emitError('network', '연결 실패');
  assert.deepEqual(events.filter((e) => e.type === 'error'), [
    { type: 'error', kind: 'unknown', message: '연결 실패' },
  ]);
});

test('우리가 정지시켜 생긴 aborted는 오류로 내지 않는다', () => {
  const { recognizer, instances, events } = setup();
  recognizer.start();
  events.length = 0;
  recognizer.stop();
  instances[0].emitError('aborted');
  assert.equal(events.filter((e) => e.type === 'error').length, 0);
});

test('정지 뒤 end가 오지 않아도 2초 뒤 idle로 끝난다', () => {
  const { recognizer, instances, clock } = setup();
  recognizer.start();
  // end를 내지 않는 인식 객체를 흉내 낸다.
  instances[0].stop = () => { instances[0].started = false; };

  recognizer.stop();
  assert.equal(recognizer.getStatus(), 'stopping');

  clock.advance(2000);
  assert.equal(recognizer.getStatus(), 'idle');
});

test('SpeechRecognition이 없으면 not-supported를 낸다', () => {
  const events = [];
  const recognizer = createRecognizer({
    SpeechRecognitionCtor: undefined,
    onEvent: (e) => events.push(e),
  });
  recognizer.start();
  assert.equal(events[0].kind, 'not-supported');
  assert.equal(recognizer.getStatus(), 'idle');
});

test('정지 요청 뒤 브라우저가 aborted를 먼저 보내도 오류로 내지 않는다', () => {
  const { recognizer, instances, events } = setup();
  recognizer.start();
  events.length = 0;

  // 실제 브라우저는 stop() 호출 뒤 aborted를 먼저 보내고 end를 나중에 보낸다.
  const rec = instances[0];
  rec.stop = () => {
    rec.started = false;
    rec.emitError('aborted');
    rec.emitEnd();
  };

  recognizer.stop();

  assert.equal(events.filter((e) => e.type === 'error').length, 0);
  assert.equal(recognizer.getStatus(), 'idle');
});

test('timers를 주입하지 않아도 기본 타이머로 복구한다', async () => {
  // ⚠ 이 테스트는 기본 타이머 경로가 도는지만 본다.
  // 브라우저는 this가 window가 아닌 setTimeout 호출을 Illegal invocation으로 거부하는데
  // (Chrome 152 실측) Node의 setTimeout에는 그 검사가 없어 여기서는 재현되지 않는다.
  // 그래서 기본값은 호출을 감싸 두고, 실제 확인은 브라우저에서 한다.
  const { FakeSpeechRecognition, instances } = createFakeRecognition();
  const recognizer = createRecognizer({
    SpeechRecognitionCtor: FakeSpeechRecognition,
    onEvent: () => {},
    restartDelayMs: 1,
  });

  recognizer.start();
  instances[0].emitEnd();
  assert.equal(recognizer.getStatus(), 'recovering');

  await new Promise((resolve) => setTimeout(resolve, 20));

  assert.equal(instances.length, 2, '기본 타이머로 재시작이 예약되고 실행된다');
  assert.equal(recognizer.getStatus(), 'listening');
  recognizer.stop();
});

test('정지 중에 다시 시작했다 정지하면 앞선 타임아웃이 끼어들지 않는다', () => {
  const { recognizer, instances, clock } = setup();
  // end를 내지 않는 인식 객체를 흉내 내 정지 타임아웃 경로를 태운다.
  const swallowEnd = (r) => { r.stop = () => { r.started = false; }; };

  recognizer.start();
  swallowEnd(instances[0]);
  recognizer.stop();            // t=0. 이때 잡힌 타임아웃은 t=2000에 불린다

  clock.advance(500);
  recognizer.start();           // t=500. 사용자가 마음을 바꿔 다시 시작
  swallowEnd(instances[1]);

  clock.advance(500);
  recognizer.stop();            // t=1000. 이때 잡힌 타임아웃은 t=3000

  clock.advance(1000);          // t=2000. 버려졌어야 할 옛 타임아웃 자리
  assert.equal(recognizer.getStatus(), 'stopping', '옛 타임아웃이 정지를 앞당기지 않는다');

  clock.advance(1000);          // t=3000
  assert.equal(recognizer.getStatus(), 'idle');
});

test('첫 start()가 InvalidStateError를 던져도 호출자에게 새지 않는다', () => {
  const { recognizer, instances, events, clock } = setup({
    onStart: (nth) => (nth === 1 ? 'throw-invalid-state' : undefined),
  });

  recognizer.start();   // 여기서 던지면 app.js의 클릭 핸들러로 예외가 올라간다
  assert.equal(events.filter((e) => e.type === 'error').length, 0, '아직 포기하지 않는다');

  clock.advance(250);
  assert.equal(recognizer.getStatus(), 'listening');
  assert.equal(instances.length, 2);
});

test('첫 start()가 계속 실패하면 오류를 내고 다시 시작할 수 있는 상태로 남는다', () => {
  const { recognizer, events, clock } = setup({ onStart: () => 'throw-invalid-state' });

  recognizer.start();
  clock.advance(250 * 6);

  const errors = events.filter((e) => e.type === 'error');
  assert.equal(errors.length, 1);
  assert.equal(errors[0].kind, 'unknown');
  assert.equal(recognizer.getStatus(), 'idle', '갇히지 않고 다시 누를 수 있어야 한다');
});

test('복구를 기다리는 중에 정지하면 바로 끝난다', () => {
  const { recognizer, instances, clock } = setup();
  recognizer.start();
  instances[0].emitEnd();                 // 끊김. 5초 복구 대기에 들어간다
  assert.equal(recognizer.getStatus(), 'recovering');

  recognizer.stop();
  // 살아 있는 인식이 없으므로 end를 기다릴 이유가 없다.
  assert.equal(recognizer.getStatus(), 'idle');

  clock.advance(60000);
  assert.equal(instances.length, 1, '정지했으므로 재시작하지 않는다');
});

test('start 재시도를 기다리는 중에 정지하면 바로 끝난다', () => {
  const { recognizer, instances, clock } = setup({
    onStart: (nth) => (nth >= 2 ? 'throw-invalid-state' : undefined),
  });
  recognizer.start();
  instances[0].emitEnd();
  clock.advance(5000);          // 재시작 시도가 던져 250ms 백오프에 들어간다
  assert.equal(recognizer.getStatus(), 'recovering');

  recognizer.stop();
  assert.equal(recognizer.getStatus(), 'idle');

  clock.advance(60000);
  assert.equal(instances.length, 2, '백오프 타이머가 버려졌다');
});

test('정지가 끝나기 전에 다시 시작하면 옛 인식을 끊는다', () => {
  const { recognizer, instances } = setup();
  recognizer.start();
  const first = instances[0];
  // end를 늦게 주는 브라우저를 흉내 낸다. stop() 뒤에도 인식이 살아 있다.
  first.stop = () => {};

  recognizer.stop();
  assert.equal(recognizer.getStatus(), 'stopping');

  recognizer.start();
  assert.equal(recognizer.getStatus(), 'listening');
  assert.equal(instances.length, 2);
  assert.equal(first.aborted, true, '옛 인식을 끊지 않으면 캡처 세션이 겹친다');
});

test('인식 객체에 회의용 설정을 건다', () => {
  const { recognizer, instances } = setup();
  recognizer.start();

  const r = instances[0];
  assert.equal(r.lang, 'ko-KR', '빠지면 브라우저 기본 언어로 인식한다');
  assert.equal(r.continuous, true, 'false면 첫 문장 뒤 멈춘다');
  assert.equal(r.interimResults, true, 'false면 중간 결과가 영영 오지 않는다');
  assert.equal(r.maxAlternatives, 1);
});

test('lang은 주입한 값을 따른다', () => {
  const clock = createFakeTimers();
  const { FakeSpeechRecognition, instances } = createFakeRecognition();
  const recognizer = createRecognizer({
    SpeechRecognitionCtor: FakeSpeechRecognition,
    onEvent: () => {},
    timers: clock.timers,
    lang: 'en-US',
  });
  recognizer.start();
  assert.equal(instances[0].lang, 'en-US');
});

test('start 재시도는 기본값대로 여섯 번까지 시도한다', () => {
  const { recognizer, instances, clock } = setup({
    onStart: (nth) => (nth >= 2 ? 'throw-invalid-state' : undefined),
  });
  recognizer.start();
  instances[0].emitEnd();
  clock.advance(5000 + 250 * 6);

  // 처음 만든 것 1개 + 재시작 시도 6번(attempt 0..5)
  assert.equal(instances.length, 7);
});
