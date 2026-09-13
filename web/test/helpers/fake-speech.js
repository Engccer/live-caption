// 가짜 타이머. 실제 시간을 쓰지 않는다.
export function createFakeTimers() {
  let now = 0;
  let nextId = 1;
  const scheduled = new Map();

  return {
    timers: {
      setTimeout(fn, ms) {
        const id = nextId++;
        scheduled.set(id, { fn, at: now + ms });
        return id;
      },
      clearTimeout(id) {
        scheduled.delete(id);
      },
    },
    // target 시각까지 예약된 콜백을 예약 순서대로 실행한다.
    advance(ms) {
      const target = now + ms;
      let guard = 0;
      for (;;) {
        let pick = null;
        for (const [id, t] of scheduled) {
          if (t.at <= target && (pick === null || t.at < scheduled.get(pick).at)) pick = id;
        }
        if (pick === null) break;
        const t = scheduled.get(pick);
        scheduled.delete(pick);
        now = t.at;
        t.fn();
        if (++guard > 1000) throw new Error('타이머가 무한히 재예약되고 있다');
      }
      now = target;
    },
    get pendingCount() {
      return scheduled.size;
    },
  };
}

// 가짜 SpeechRecognition. 브라우저가 하는 일을 테스트가 직접 시킨다.
// onStart(회차)가 'throw-invalid-state'를 돌려주면 그 회차의 start()가 던진다.
export function createFakeRecognition({ onStart } = {}) {
  const instances = [];

  class FakeSpeechRecognition {
    constructor() {
      this.started = false;
      this.aborted = false;
      instances.push(this);
    }

    start() {
      if (onStart?.(instances.length) === 'throw-invalid-state') {
        const error = new Error('recognizer is not ready');
        error.name = 'InvalidStateError';
        throw error;
      }
      this.started = true;
      this.onstart?.();
    }

    stop() {
      this.started = false;
      this.onend?.();
    }

    abort() {
      this.aborted = true;
      this.started = false;
      this.onend?.();
    }

    // --- 아래는 테스트가 브라우저 대신 사건을 일으키는 손잡이다 ---

    // items: [{ text: '안녕하세요', isFinal: true }, ...]
    emitResult(items, resultIndex = 0) {
      const results = items.map((item) => {
        const alternatives = [{ transcript: item.text }];
        alternatives.isFinal = item.isFinal;
        return alternatives;
      });
      this.onresult?.({ resultIndex, results });
    }

    emitError(code, message = '') {
      this.onerror?.({ error: code, message });
    }

    // 사용자가 정지하지 않았는데 브라우저가 끊는 상황
    emitEnd() {
      this.started = false;
      this.onend?.();
    }
  }

  return { FakeSpeechRecognition, instances };
}
