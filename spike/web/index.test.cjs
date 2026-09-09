const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function loadPage() {
  const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const elements = new Map();
  const timers = new Map();
  const recognitionInstances = [];
  let nextTimerId = 1;
  let startAttempts = 0;

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
      if (startAttempts === 2) {
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
      this.onend?.();
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
    performance: { now: () => 1000 },
    setTimeout(callback) {
      const timerId = nextTimerId++;
      timers.set(timerId, callback);
      return timerId;
    },
    window: { webkitSpeechRecognition: FakeSpeechRecognition },
  };

  vm.runInNewContext(script, context);

  return {
    element,
    get startAttempts() { return startAttempts; },
    recognitionInstances,
    runTimers() {
      for (const [timerId, callback] of [...timers]) {
        timers.delete(timerId);
        callback();
      }
    },
  };
}

function reachRetryWait(page) {
  page.element('toggle').click();
  page.recognitionInstances[0].endUnexpectedly();
  assert.equal(page.startAttempts, 2, '첫 자동 재시작이 실패해야 한다');
}

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
