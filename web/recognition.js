// 인식 수명주기와 끊김 복구.
// 브라우저 API는 전부 주입받는다. 그래서 브라우저 없이 테스트할 수 있다.
//
// 수치와 절차는 spike/web/index.html에서 실측으로 얻은 것을 옮겼다.

// Web Speech의 error 코드를 우리 사건의 kind로 접는다.
const ERROR_KINDS = {
  'not-allowed': 'permission-denied',
  'service-not-allowed': 'permission-denied',
  'no-speech': 'no-speech',
};

export function createRecognizer({
  SpeechRecognitionCtor,
  onEvent = () => {},
  lang = 'ko-KR',
  restartDelayMs = 5000,
  startRetryDelayMs = 250,
  maxStartRetries = 5,
  stopTimeoutMs = 2000,
  // 브라우저의 setTimeout은 this가 window가 아니면 Illegal invocation으로 거부한다
  // (Chrome 152 실측). 그래서 그대로 담지 않고 호출을 감싼다.
  timers = {
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
  },
} = {}) {
  let rec = null;
  let status = 'idle';
  let running = false;    // 사용자가 시작을 눌러 둔 상태인가
  let generation = 0;     // 버린 인식 객체의 지각 이벤트를 거르는 세대 번호
  let restartTimer = null;
  let stopTimer = null;
  let stopping = false;   // 우리가 정지를 요청해 end를 기다리는 중인가

  function setStatus(next) {
    if (status === next) return;   // 바뀔 때만 알린다
    status = next;
    onEvent({ type: 'status', status });
  }

  // 세대와 객체가 둘 다 현재 것일 때만 핸들러를 통과시킨다.
  function build(activeGeneration) {
    const r = new SpeechRecognitionCtor();
    const current = (handler) => (...args) => {
      if (activeGeneration === generation && r === rec) handler(...args);
    };

    r.lang = lang;
    r.continuous = true;
    r.interimResults = true;
    r.maxAlternatives = 1;

    r.onstart = current(() => setStatus('listening'));

    // 브라우저는 results를 누적해 보내고 resultIndex로 새 것을 가리킨다.
    r.onresult = current((e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const text = e.results[i][0].transcript.trim();
        if (e.results[i].isFinal) {
          if (text) onEvent({ type: 'final', text });
        } else if (text) {
          interim += (interim ? ' ' : '') + text;
        }
      }
      if (interim) onEvent({ type: 'interim', text: interim });
    });

    r.onerror = current((e) => {
      // aborted는 정지·재시작 과정에서 정상적으로 난다. 우리가 의도한 것이면 알리지 않는다.
      if (e.error === 'aborted' && (stopping || !running)) return;

      const kind = ERROR_KINDS[e.error] ?? 'unknown';
      onEvent({ type: 'error', kind, message: e.message ?? '' });

      // 같은 오류가 무한히 반복되므로 자동 재시작을 포기한다.
      // no-speech는 조용한 회의에서 정상적으로 나므로 여기 걸리지 않는다.
      if (kind === 'permission-denied') running = false;
    });

    r.onend = current(() => {
      if (running) scheduleRestart(activeGeneration);
      else finish();
    });

    return r;
  }

  // iOS Safari는 end 직후 이전 캡처 소스를 정리하는 동안 새 소스를 열면
  // audiostart만 오고 실제 오디오가 전달되지 않는다. 그래서 기다렸다 연다.
  function scheduleRestart(activeGeneration) {
    if (!running || activeGeneration !== generation || restartTimer !== null) return;
    setStatus('recovering');
    restartTimer = timers.setTimeout(() => {
      restartTimer = null;
      restart(activeGeneration);
    }, restartDelayMs);
  }

  // Safari는 end 직후 start()에 InvalidStateError를 내기도 한다. 짧게 물러서 재시도한다.
  function restart(activeGeneration, attempt = 0) {
    if (!running || activeGeneration !== generation) return;
    try {
      rec = build(activeGeneration);
      rec.start();
    } catch (e) {
      if (attempt < maxStartRetries) {
        restartTimer = timers.setTimeout(() => {
          restartTimer = null;
          restart(activeGeneration, attempt + 1);
        }, startRetryDelayMs);
        return;
      }
      onEvent({
        type: 'error',
        kind: 'unknown',
        message: `인식을 다시 시작하지 못했습니다: ${e.name}`,
      });
      finish();
    }
  }

  function finish() {
    if (restartTimer !== null) {
      timers.clearTimeout(restartTimer);
      restartTimer = null;
    }
    if (stopTimer !== null) {
      timers.clearTimeout(stopTimer);
      stopTimer = null;
    }
    stopping = false;
    running = false;
    rec = null;
    generation++;   // 이 뒤에 오는 옛 객체의 이벤트는 전부 막힌다
    setStatus('idle');
  }

  function start() {
    if (!SpeechRecognitionCtor) {
      onEvent({
        type: 'error',
        kind: 'not-supported',
        message: '이 브라우저는 음성 인식을 지원하지 않습니다',
      });
      return;
    }
    if (running) return;

    running = true;
    stopping = false;
    // 앞선 정지가 걸어 둔 타임아웃을 버린다. 남겨 두면 다음 정지를 앞당겨 끝낸다.
    if (stopTimer !== null) {
      timers.clearTimeout(stopTimer);
      stopTimer = null;
    }
    generation++;
    rec = build(generation);
    rec.start();
  }

  function stop() {
    if (!running) return;
    running = false;
    stopping = true;
    if (restartTimer !== null) {
      timers.clearTimeout(restartTimer);
      restartTimer = null;
    }
    if (!rec) {
      finish();
      return;
    }
    setStatus('stopping');
    // end가 끝내 오지 않는 브라우저가 있다. 기다리다 스스로 끝낸다.
    stopTimer = timers.setTimeout(() => {
      stopTimer = null;
      if (stopping) finish();
    }, stopTimeoutMs);
    try {
      rec.stop();
    } catch {
      finish();
    }
  }

  return { start, stop, getStatus: () => status };
}
