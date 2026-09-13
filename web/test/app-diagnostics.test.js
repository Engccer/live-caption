import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createFakeRecognition, createFakeTimers } from './helpers/fake-speech.js';

let moduleId = 0;
async function setup(t, options = {}) {
  const nodes = new Map();
  const element = () => ({
    hidden: false, textContent: '', style: {}, scrollTop: 0, scrollHeight: 0, clientHeight: 0,
    listeners: {}, attributes: {},
    appendChild() {},
    addEventListener(name, handler) { this.listeners[name] = handler; },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    click() { return this.listeners.click(); },
  });
  for (const id of ['status', 'captions', 'finals', 'interim', 'toggle', 'fontDown', 'fontUp', 'copy', 'copyDiagnostics']) nodes.set(id, element());
  nodes.get('copy').hidden = nodes.get('copyDiagnostics').hidden = true;
  const fake = createFakeRecognition(options);
  if (options.delayFirstStart) {
    const start = fake.FakeSpeechRecognition.prototype.start;
    fake.FakeSpeechRecognition.prototype.start = function () {
      if (fake.instances.length === 1) this.started = true;
      else start.call(this);
    };
  }
  const clock = createFakeTimers();
  const copied = [];
  const replacements = {
    window: { SpeechRecognition: fake.FakeSpeechRecognition, screen: { width: 390, height: 844 }, matchMedia: () => ({ matches: false }) },
    document: { getElementById: (id) => nodes.get(id), createElement: element, addEventListener() {} },
    navigator: { userAgent: '', clipboard: { writeText: options.writeText ?? (async (text) => { copied.push(text); }) } },
    setTimeout: clock.timers.setTimeout,
    clearTimeout: clock.timers.clearTimeout,
  };
  for (const [key, value] of Object.entries(replacements)) {
    const original = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable: true, value });
    t.after(() => original ? Object.defineProperty(globalThis, key, original) : delete globalThis[key]);
  }
  await import(`../app.js?test=${moduleId++}`);
  return { nodes, copied, clock, ...fake };
}

test('무발화 권한 거부 종료에서도 진단을 복사하고 다음 시작에 숨긴다', async (t) => {
  const { nodes, instances, copied } = await setup(t);
  nodes.get('toggle').click();
  instances[0].emitError('not-allowed', '남기면 안 되는 메시지');
  instances[0].emitEnd();
  assert.equal(nodes.get('copyDiagnostics').hidden, false);
  assert.equal(nodes.get('copy').hidden, true);
  await nodes.get('copyDiagnostics').click();
  assert.match(copied[0], /확정 0건/);
  assert.match(copied[0], /permission-denied 1/);
  assert.doesNotMatch(copied[0], /남기면/);
  assert.match(nodes.get('status').textContent, /진단 정보를 복사했습니다/);
  nodes.get('toggle').click();
  assert.equal(nodes.get('copyDiagnostics').hidden, true);
  nodes.get('toggle').click();
  await nodes.get('copyDiagnostics').click();
  assert.match(copied[1], /오류\(kind\): 없음/);
});

test('복구 대기 중 정지는 중단으로 기록하고 뒤늦게 재시작하지 않는다', async (t) => {
  const { nodes, instances, copied, clock } = await setup(t);
  nodes.get('toggle').click();
  instances[0].emitEnd();
  nodes.get('toggle').click();
  clock.advance(10000);
  await nodes.get('copyDiagnostics').click();
  assert.match(copied[0], /재연결 성공 0 \/ 실패 0 \/ 중단 1/);
  assert.equal(instances.length, 1);
});

test('첫 start 재시도가 모두 실패해도 진단 버튼이 나타난다', async (t) => {
  const { nodes, copied, clock } = await setup(t, { onStart: () => 'throw-invalid-state' });
  nodes.get('toggle').click();
  clock.advance(2000);
  assert.equal(nodes.get('copyDiagnostics').hidden, false);
  await nodes.get('copyDiagnostics').click();
  assert.match(copied[0], /unknown 1/);
});

test('onstart 전 일반 오류가 나도 진단을 종료하지 않고 복구 이후 결과까지 센다', async (t) => {
  const { nodes, copied, instances, clock } = await setup(t, { delayFirstStart: true });
  nodes.get('toggle').click();
  instances[0].emitError('network', '네트워크 오류');
  assert.equal(nodes.get('copyDiagnostics').hidden, true);
  instances[0].emitEnd();
  clock.advance(5000);
  instances[1].emitResult([{ text: '가상 복구 결과', isFinal: true }]);
  nodes.get('toggle').click();
  await nodes.get('copyDiagnostics').click();
  assert.match(copied[0], /확정 1건/);
  assert.match(copied[0], /끊김 1회/);
  assert.match(copied[0], /재연결 후 결과 수신 1 \/ 미확인 0/);
});

test('onstart 없이 마이크 권한이 거부돼도 오류 진단을 복사할 수 있다', async (t) => {
  const { nodes, copied, instances } = await setup(t, { delayFirstStart: true });
  nodes.get('toggle').click();
  instances[0].emitError('not-allowed');
  instances[0].emitEnd();
  assert.equal(nodes.get('copyDiagnostics').hidden, false);
  assert.equal(nodes.get('toggle').textContent, '시작');
  await nodes.get('copyDiagnostics').click();
  assert.match(copied[0], /permission-denied 1/);
});

test('클립보드 거부는 실패로 알리고 진단을 유지해 재시도할 수 있다', async (t) => {
  const { nodes } = await setup(t, { writeText: async () => { throw new Error('권한 거부'); } });
  nodes.get('toggle').click();
  nodes.get('toggle').click();
  await nodes.get('copyDiagnostics').click();
  assert.match(nodes.get('status').textContent, /진단 정보를 복사하지 못했습니다/);
  assert.equal(nodes.get('copyDiagnostics').hidden, false);
  assert.equal(nodes.get('copyDiagnostics').attributes['aria-disabled'], undefined);
});

test('복사 중 중복 입력을 막고 완료가 새 세션의 상태를 덮지 않는다', async (t) => {
  let resolve;
  let calls = 0;
  const { nodes } = await setup(t, { writeText: () => { calls++; return new Promise((r) => { resolve = r; }); } });
  nodes.get('toggle').click();
  nodes.get('toggle').click();
  const pending = nodes.get('copyDiagnostics').click();
  await nodes.get('copyDiagnostics').click();
  assert.equal(calls, 1);
  assert.equal(nodes.get('copyDiagnostics').attributes['aria-disabled'], 'true');
  nodes.get('toggle').click();
  const before = nodes.get('status').textContent;
  resolve();
  await pending;
  assert.equal(nodes.get('status').textContent, before);
  nodes.get('toggle').click();
});
