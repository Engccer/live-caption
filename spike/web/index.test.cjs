const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function loadPage({ failSecondStart = true } = {}) {
  const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const elements = new Map();
  const timers = new Map();
  const recognitionInstances = [];
  let nextTimerId = 1;
  let startAttempts = 0;
  let abortAttempts = 0;
  let clock = 1000;

  function element(id) {
    if (!elements.has(id)) {
      elements.set(id, {
        id,
        textContent: '',
        hidden: false,
        disabled: false,
        checked: id === 'autoRestart' || id === 'continuous',
        listeners: {},
        children: [],
        addEventListener(type, listener) { this.listeners[type] = listener; },
        appendChild(child) { this.children.push(child); },
        click() { return this.listeners.click(); },
        focus() { this.focused = true; },
        removeAttribute(name) { delete this[name]; },
        setAttribute(name, value) { this[name] = value; },
      });
    }
    return elements.get(id);
  }

  class FakeSpeechRecognition {
    constructor() {
      this.started = false;
      recognitionInstances.push(this);
    }

    start() {
      startAttempts++;
      if (failSecondStart && startAttempts === 2) {
        const error = new Error('recognizer is not ready');
        error.name = 'InvalidStateError';
        throw error;
      }
      this.started = true;
      this.onstart?.();
    }

    stop() {
      if (!this.started) {
        const error = new Error('recognizer is not active');
        error.name = 'InvalidStateError';
        throw error;
      }
      this.started = false;
    }

    abort() {
      abortAttempts++;
      if (!this.started) {
        const error = new Error('recognizer is not active');
        error.name = 'InvalidStateError';
        throw error;
      }
      this.started = false;
    }

    emitAbortError() {
      this.onerror?.({ error: 'aborted', message: 'Aborted by test' });
    }

    addFinal(transcript) {
      const result = [{ transcript }];
      result.isFinal = true;
      this.onresult({ resultIndex: 0, results: [result] });
    }

    completeStopWithFinal(transcript) {
      this.addFinal(transcript);
      this.onend();
    }

    endUnexpectedly() {
      this.started = false;
      this.onend();
    }
  }

  const context = {
    clearTimeout(timerId) { timers.delete(timerId); },
    document: {
      visibilityState: 'visible',
      addEventListener() {},
      createElement() { return { textContent: '' }; },
      getElementById: element,
    },
    navigator: {
      clipboard: { async writeText() {} },
      userAgent: 'Fake iPhone Safari',
    },
    performance: { now: () => clock },
    setTimeout(callback, delay = 0) {
      const timerId = nextTimerId++;
      timers.set(timerId, { callback, dueAt: clock + delay });
      return timerId;
    },
    window: { webkitSpeechRecognition: FakeSpeechRecognition },
  };

  vm.runInNewContext(script, context);

  return {
    element,
    get startAttempts() { return startAttempts; },
    get abortAttempts() { return abortAttempts; },
    recognitionInstances,
    runTimers() {
      if (!timers.size) return;
      clock = Math.min(...[...timers.values()].map((timer) => timer.dueAt));
      for (const [timerId, timer] of [...timers]) {
        if (timer.dueAt > clock) continue;
        timers.delete(timerId);
        timer.callback();
      }
    },
    advanceTimersBy(duration) {
      const target = clock + duration;
      while (true) {
        const dueTimers = [...timers.entries()]
          .filter(([, timer]) => timer.dueAt <= target)
          .sort((a, b) => a[1].dueAt - b[1].dueAt);
        if (!dueTimers.length) break;
        const [timerId, timer] = dueTimers[0];
        clock = timer.dueAt;
        timers.delete(timerId);
        timer.callback();
      }
      clock = target;
    },
  };
}

test('재시작 시험은 현재 인식을 중단하고 5초 뒤 새 세션을 시작한다', () => {
  const page = loadPage({ failSecondStart: false });
  page.element('toggle').click();

  page.element('restartTest').click();
  page.recognitionInstances[0].emitAbortError();
  page.recognitionInstances[0].endUnexpectedly();

  assert.equal(page.abortAttempts, 1);
  assert.equal(page.startAttempts, 1);
  assert.equal(page.element('restartTest').disabled, false);
  assert.equal(page.element('restartTest')['aria-disabled'], 'true');
  assert.match(page.element('restartStatus').textContent, /5초/);
  page.advanceTimersBy(4999);
  assert.equal(page.startAttempts, 1);
  page.advanceTimersBy(1);
  assert.equal(page.startAttempts, 2);
  assert.equal(page.element('restartTest').disabled, false);
  assert.equal(page.element('restartTest')['aria-disabled'], undefined);
  assert.match(page.element('restartStatus').textContent, /다시 시작됨/);
});

test('재시작 시험의 aborted 이벤트는 오류 요약에 포함하지 않는다', () => {
  const page = loadPage({ failSecondStart: false });
  page.element('toggle').click();
  page.element('restartTest').click();
  page.recognitionInstances[0].emitAbortError();
  page.recognitionInstances[0].endUnexpectedly();
  page.advanceTimersBy(5000);

  page.element('toggle').click();
  page.recognitionInstances[1].completeStopWithFinal('재시작 뒤 발화');

  assert.match(page.element('summary').textContent, /오류 없음/);
});

test('자동 재시작 옵션이 꺼져도 재시작 시험은 새 세션을 시작한다', () => {
  const page = loadPage({ failSecondStart: false });
  page.element('autoRestart').checked = false;
  page.element('toggle').click();

  page.element('restartTest').click();
  page.recognitionInstances[0].emitAbortError();
  page.recognitionInstances[0].endUnexpectedly();
  page.advanceTimersBy(5000);

  assert.equal(page.startAttempts, 2);
});

test('재시작 시험 버튼은 포커스를 유지한 채 비활성 상태를 전달한다', () => {
  const page = loadPage({ failSecondStart: false });
  page.element('toggle').click();
  page.element('restartTest').focus();

  page.element('restartTest').click();

  assert.equal(page.element('restartTest').focused, true);
  assert.equal(page.element('restartTest').disabled, false);
  assert.equal(page.element('restartTest')['aria-disabled'], 'true');
});

test('재시작 시험에서 end가 누락돼도 2초 뒤 복구 절차로 넘어간다', () => {
  const page = loadPage({ failSecondStart: false });
  page.element('toggle').click();
  page.element('restartTest').click();
  page.recognitionInstances[0].emitAbortError();

  page.advanceTimersBy(1999);
  assert.equal(page.startAttempts, 1);
  page.advanceTimersBy(1);
  page.advanceTimersBy(4999);
  assert.equal(page.startAttempts, 1);
  page.advanceTimersBy(1);
  assert.equal(page.startAttempts, 2);
});

test('재시작 시험 전후의 확정 결과를 모두 보존한다', () => {
  const page = loadPage({ failSecondStart: false });
  page.element('toggle').click();
  page.recognitionInstances[0].addFinal('재시작 전 발화');

  page.element('restartTest').click();
  page.recognitionInstances[0].emitAbortError();
  page.recognitionInstances[0].endUnexpectedly();
  page.advanceTimersBy(5000);
  page.recognitionInstances[1].addFinal('재시작 후 발화');

  assert.equal(page.element('final').textContent, '재시작 전 발화\n재시작 후 발화');
});

function reachRetryWait(page) {
  page.element('toggle').click();
  page.recognitionInstances[0].endUnexpectedly();
  assert.equal(page.startAttempts, 1, '종료 직후에는 재시작하지 않아야 한다');
  page.runTimers();
  assert.equal(page.startAttempts, 2, '첫 자동 재시작이 실패해야 한다');
}

test('예상치 못한 종료 뒤 정리 대기 시간이 지나야 재시작한다', () => {
  const page = loadPage({ failSecondStart: false });
  page.element('toggle').click();

  page.recognitionInstances[0].endUnexpectedly();

  assert.equal(page.startAttempts, 1);
  page.advanceTimersBy(4999);
  assert.equal(page.startAttempts, 1);
  page.advanceTimersBy(1);
  assert.equal(page.startAttempts, 2);
});

test('정리 대기 중 사용자가 정지하면 새 인식 세션을 시작하지 않는다', () => {
  const page = loadPage({ failSecondStart: false });
  page.element('toggle').click();
  page.recognitionInstances[0].endUnexpectedly();

  page.element('toggle').click();
  page.runTimers();

  assert.equal(page.startAttempts, 1);
  assert.equal(page.element('summary').hidden, false);
});

test('재시작 대기 중 정지해도 요약과 로그 복사 버튼을 표시한다', () => {
  const page = loadPage();
  reachRetryWait(page);

  assert.doesNotThrow(() => page.element('toggle').click());
  assert.equal(page.element('summary').hidden, false);
  assert.equal(page.element('copy').hidden, false);
});

test('재시작 대기 중 정지하면 예약된 인식 세션을 시작하지 않는다', () => {
  const page = loadPage();
  reachRetryWait(page);

  try { page.element('toggle').click(); } catch {}
  page.runTimers();

  assert.equal(page.startAttempts, 2);
});

test('정지 뒤 마지막 확정 결과와 end를 받은 다음 요약을 표시한다', () => {
  const page = loadPage();
  page.element('toggle').click();

  page.element('toggle').click();

  assert.equal(page.element('summary').hidden, true);
  assert.equal(page.element('copy').hidden, true);

  page.recognitionInstances[0].completeStopWithFinal('마지막 발화');

  assert.equal(page.element('summary').hidden, false);
  assert.match(page.element('summary').textContent, /확정 결과 1개/);
  assert.equal(page.element('copy').hidden, false);
});

test('정지 뒤 end가 오지 않아도 대기 시간이 지나면 요약을 표시한다', () => {
  const page = loadPage();
  page.element('toggle').click();

  page.element('toggle').click();

  assert.equal(page.element('summary').hidden, true);
  page.runTimers();
  assert.equal(page.element('summary').hidden, false);
  assert.equal(page.element('copy').hidden, false);
});

test('폴백 뒤 새 세션은 이전 인식기의 늦은 이벤트를 무시한다', () => {
  const page = loadPage({ failSecondStart: false });
  page.element('toggle').click();
  const previousRecognition = page.recognitionInstances[0];

  page.element('toggle').click();
  page.runTimers();
  page.element('toggle').click();

  previousRecognition.completeStopWithFinal('이전 세션의 늦은 결과');

  assert.equal(page.element('final').textContent, '');
  assert.equal(page.startAttempts, 2);
});
