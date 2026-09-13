// 인식 사건은 보관하지 않는다. 텍스트와 오류 메시지를 읽지 않고 수치만 누적한다.
const ERROR_KINDS = new Set(['permission-denied', 'not-supported', 'no-speech', 'unknown']);
const AVAILABILITY = new Set(['available', 'unavailable', 'downloadable', 'downloading']);
const seconds = (ms) => (ms / 1000).toFixed(1);

export function createDiagnostics({ startedAt, date }) {
  let endedAt = null;
  let finals = 0;
  let stopping = false;
  let lastStatus = 'idle';
  const errors = new Map();
  const breaks = [];

  function record(event, at) {
    if (endedAt !== null) return;
    const latest = breaks.at(-1);
    if (event.type === 'final') finals++;
    if ((event.type === 'final' || event.type === 'interim') &&
        latest?.outcome === 'success' && !stopping) latest.receivedResult = true;
    if (event.type === 'error') {
      const kind = ERROR_KINDS.has(event.kind) ? event.kind : 'unknown';
      errors.set(kind, (errors.get(kind) ?? 0) + 1);
    }
    if (event.type !== 'status') return;
    if (event.status === 'recovering' && lastStatus !== 'recovering' && !stopping) {
      breaks.push({ at, outcome: 'pending', receivedResult: false, gap: null });
    }
    if (event.status === 'listening' && latest?.outcome === 'pending' && !stopping) {
      latest.outcome = 'success';
      latest.gap = at - latest.at;
    }
    if (event.status === 'stopping') stopping = true;
    if (event.status === 'idle') {
      endedAt = at;
      if (latest?.outcome === 'pending') latest.outcome = stopping ? 'cancelled' : 'failed';
    }
    lastStatus = event.status;
  }

  function toText({ environment: env, fontSize, availability }) {
    const duration = Math.max(0, Math.floor(((endedAt ?? startedAt) - startedAt) / 1000));
    const successful = breaks.filter((b) => b.outcome === 'success');
    const confirmed = successful.filter((b) => b.receivedResult).length;
    const intervals = breaks.map((b, i) => `${seconds(b.at - (i ? breaks[i - 1].at : startedAt))}s`);
    const maxGap = successful.length
      ? `${seconds(successful.reduce((max, b) => Math.max(max, b.gap), 0))}초` : '해당 없음';
    return [
      `말동무 진단 ${date}`,
      `세션 ${Math.floor(duration / 60)}분 ${duration % 60}초, 확정 ${finals}건`,
      `끊김 ${breaks.length}회 (간격 ${intervals.join(' ') || '없음'})`,
      `재연결 성공 ${successful.length} / 실패 ${breaks.filter((b) => b.outcome === 'failed').length} / 중단 ${breaks.filter((b) => b.outcome === 'cancelled').length}, 최대 재연결 공백 ${maxGap}`,
      `재연결 후 결과 수신 ${confirmed} / 미확인 ${successful.length - confirmed}`,
      `오류(kind): ${[...errors].sort(([a], [b]) => a.localeCompare(b)).map(([kind, count]) => `${kind} ${count}`).join(', ') || '없음'}`,
      `브라우저(UA 기준): ${env.browser}, ${env.os}, ${env.device}, 화면 ${env.width ?? '정보 없음'}x${env.height ?? '정보 없음'}, 홈화면앱 ${env.standalone ? '예' : '아니오'}`,
      `글자 크기 ${fontSize}px, 온디바이스 가능 여부(ko-KR): ${availability}`,
      '끊김은 복구 상태 진입 기준, 첫 간격은 시작부터입니다. 재연결은 듣는 중 복귀 기준이며 결과 미수신은 침묵일 수도 있습니다.',
      'unknown은 원시 오류 코드가 합쳐진 값입니다. 온디바이스 가능 여부는 현재 처리 방식이 아닙니다.',
    ].join('\n');
  }

  return { record, requestStop() { stopping = true; }, toText };
}

// UA의 고정 토큰과 버전만 추출한다. 기기 모델이나 UA 원문은 내보내지 않는다.
export function describeEnvironment({ userAgent = '', maxTouchPoints = 0, width, height, standalone = false }) {
  let browser = '정보 없음';
  for (const [name, pattern] of [
    ['Edge', /(?:EdgiOS|EdgA|Edg)\/([\d.]+)/],
    ['Opera', /OPR\/([\d.]+)/],
    ['Samsung Internet', /SamsungBrowser\/([\d.]+)/],
    ['Chrome', /(?:CriOS|Chrome)\/([\d.]+)/],
    ['Firefox', /(?:FxiOS|Firefox)\/([\d.]+)/],
    ['Safari', /Version\/([\d.]+).*Safari/],
  ]) {
    const match = userAgent.match(pattern);
    if (match) { browser = `${name} ${match[1]}`; break; }
  }
  let os = '정보 없음';
  let device = '정보 없음';
  const ios = userAgent.match(/(?:iPhone OS|CPU OS) ([\d_]+)/);
  const android = userAgent.match(/Android ([\d.]+)/);
  const mac = userAgent.match(/Mac OS X ([\d_]+)/);
  const windows = userAgent.match(/Windows NT ([\d.]+)/);
  if (/iPhone|iPad|iPod/.test(userAgent)) {
    device = userAgent.match(/iPhone|iPad|iPod/)[0];
    os = ios ? `iOS ${ios[1].replaceAll('_', '.')}` : 'iOS 버전 정보 없음';
  } else if (/Macintosh/.test(userAgent) && maxTouchPoints > 1) {
    device = 'iPad 추정';
    os = 'iPadOS 버전 정보 없음';
  } else if (android) {
    device = 'Android'; os = `Android ${android[1]}`;
  } else if (mac) {
    device = 'Mac'; os = `macOS ${mac[1].replaceAll('_', '.')}`;
  } else if (windows) {
    device = 'PC'; os = `Windows NT ${windows[1]}`;
  } else if (/Linux/.test(userAgent)) {
    device = 'PC'; os = 'Linux';
  }
  return { browser, os, device, width, height, standalone };
}

export async function checkAvailability(SpeechRecognitionCtor) {
  if (typeof SpeechRecognitionCtor?.available !== 'function') return '미지원';
  try {
    const value = await SpeechRecognitionCtor.available({ langs: ['ko-KR'], processLocally: true });
    return AVAILABILITY.has(value) ? value : '정보 없음';
  } catch {
    return '조회 실패';
  }
}
