// 인식 수명주기와 끊김 복구.
// 브라우저 API는 전부 주입받는다. 그래서 브라우저 없이 테스트할 수 있다.
//
// 수치와 절차는 spike/web/index.html에서 실측으로 얻은 것을 옮겼다.

export function createRecognizer({
  SpeechRecognitionCtor,
  onEvent = () => {},
  lang = 'ko-KR',
  restartDelayMs = 5000,
  startRetryDelayMs = 250,
  maxStartRetries = 5,
  stopTimeoutMs = 2000,
  timers = { setTimeout, clearTimeout },
} = {}) {
  let rec = null;
  let status = 'idle';
  let running = false;    // 사용자가 시작을 눌러 둔 상태인가
  let generation = 0;     // 버린 인식 객체의 지각 이벤트를 거르는 세대 번호

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

    return r;
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
    generation++;
    rec = build(generation);
    rec.start();
  }

  function stop() {
    running = false;
  }

  return { start, stop, getStatus: () => status };
}
