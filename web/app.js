// 인식 모듈과 자막 저장소를 화면에 잇는 배선.
// 판단은 recognition.js와 captions.js가 하고 여기서는 DOM만 만진다.

import { createRecognizer } from './recognition.js';
import { createDiagnostics, describeEnvironment, checkAvailability } from './diagnostics.js';
import {
  createCaptionStore,
  nextFontSize,
  loadFontSize,
  saveFontSize,
  shouldAutoScroll,
} from './captions.js';

const $ = (id) => document.getElementById(id);
const statusEl = $('status');
const captionsEl = $('captions');
const finalsEl = $('finals');
const interimEl = $('interim');
const toggleEl = $('toggle');
const fontDownEl = $('fontDown');
const fontUpEl = $('fontUp');
const copyEl = $('copy');
const copyDiagnosticsEl = $('copyDiagnostics');
const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;

const STATUS_TEXT = {
  idle: '시작을 누르면 자막이 나옵니다',
  listening: '듣는 중',
  recovering: '연결이 끊겨 복구하는 중입니다',
  stopping: '정지하는 중',
};

// 상태 줄을 바꾸는 오류는 이 둘뿐이다(2026-09-13 판정).
// no-speech와 unknown은 건드리지 않는다. 아이폰은 침묵을 aborted + No speech detected로
// 보내 unknown으로 접히므로, 띄우면 조용한 회의에서 40초마다 오류가 뜬다.
// 그 상황은 status가 주는 recovering이 이미 덮는다.
const ERROR_TEXT = {
  'not-supported': '이 브라우저는 음성 인식을 지원하지 않습니다. 크롬이나 사파리로 열어 주세요',
  'permission-denied': '마이크를 허용해 주세요',
};

// 사파리 비공개 모드에서는 window.localStorage 접근 자체가 던진다.
function getStorage() {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}
const storage = getStorage();

const store = createCaptionStore();
let fontSize = loadFontSize(storage);
let renderedFinals = 0;   // finalsEl에 이미 그린 문단 수
let errorShown = false;   // 오류 문구를 status 갱신이 덮지 않게 한다
let wakeLock = null;
let diagnostics = null;
let availability = '정보 없음';
let copyingDiagnostics = false;

// --- 화면 갱신 ---

// 자막이 늘어나기 전에 "맨 아래에 있었는가"를 재고, 늘린 뒤 그 자리로 다시 붙인다.
// 순서가 중요하다: 늘린 뒤에 재면 항상 위로 밀려난 상태가 나온다.
function keepingScroll(update) {
  const stick = shouldAutoScroll(captionsEl);
  update();
  if (stick) captionsEl.scrollTop = captionsEl.scrollHeight;
}

// 확정 문단은 새로 늘어난 것만 붙인다. 매번 다시 그리면 긴 회의에서 느려지고 스크롤이 튄다.
function renderFinals() {
  const { finals } = store.getState();
  if (finals.length < renderedFinals) {   // clear된 경우
    finalsEl.textContent = '';
    renderedFinals = 0;
  }
  for (let i = renderedFinals; i < finals.length; i++) {
    const p = document.createElement('p');   // CSS가 #finals p에 문단 여백을 건다
    p.textContent = finals[i];
    finalsEl.appendChild(p);
  }
  renderedFinals = finals.length;
}

function renderInterim() {
  interimEl.textContent = store.getState().interim;
}

function setStatusText(text) {
  statusEl.textContent = text;
}

// --- 인식 사건 처리 ---

function onRecognizerEvent(event) {
  diagnostics?.record(event, performance.now());
  switch (event.type) {
    case 'final':
      keepingScroll(() => {
        store.appendFinal(event.text);
        renderFinals();
        renderInterim();
      });
      break;

    case 'interim':
      keepingScroll(() => {
        store.setInterim(event.text);
        renderInterim();
      });
      break;

    case 'status':
      // 듣는 중이 아니면 미확정 문장을 지운다. 안 그러면 복구되는 5초 내내 화면에 남아
      // 확정된 것처럼 보인다. recognition.js는 이 시점에 interim 사건을 내지 않는다.
      if (event.status !== 'listening') {
        keepingScroll(() => {
          store.setInterim('');
          renderInterim();
        });
      }
      if (!errorShown) setStatusText(STATUS_TEXT[event.status]);
      updateToggle(event.status);
      if (event.status === 'idle') finishSession();
      break;

    case 'error':
      if (ERROR_TEXT[event.kind]) {
        errorShown = true;
        setStatusText(ERROR_TEXT[event.kind]);
      }
      // 첫 start 재시도 소진은 idle 사건이 없다. 모듈 자체의 종료 오류만 보완한다.
      // onstart 전 일반 브라우저 오류도 idle에서 오므로 상태만으로 종료하면 안 된다.
      const startFailed = event.kind === 'not-supported' || event.kind === 'permission-denied' ||
        (event.kind === 'unknown' && event.message?.startsWith('인식을 다시 시작하지 못했습니다: '));
      if (recognizer.getStatus() === 'idle' && startFailed) {
        updateToggle('idle');
        finishSession();
      }
      break;
  }
}

const recognizer = createRecognizer({
  SpeechRecognitionCtor,
  onEvent: onRecognizerEvent,
  // timers를 넘기지 않는다. 평범한 객체로 넘기면 브라우저가 Illegal invocation으로
  // 거부하고, 피해가 재시작 예약에서만 나 아이폰 첫 끊김에서 조용히 멈춘다.
});

// --- 컨트롤 ---

function updateToggle(status) {
  if (status === 'stopping') {
    toggleEl.textContent = '정지 중';
    toggleEl.setAttribute('aria-disabled', 'true');   // disabled는 포커스를 떨어뜨린다
    return;
  }
  toggleEl.removeAttribute('aria-disabled');
  toggleEl.textContent = status === 'idle' ? '시작' : '정지';
}

function startSession() {
  const date = new Date();
  const localDate = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  diagnostics = createDiagnostics({ startedAt: performance.now(), date: localDate });
  const session = diagnostics;
  availability = typeof SpeechRecognitionCtor?.available === 'function' ? '조회 중' : '미지원';
  checkAvailability(SpeechRecognitionCtor).then((value) => {
    if (diagnostics === session) availability = value;
  });
  copyDiagnosticsEl.hidden = true;
  store.clear();
  finalsEl.textContent = '';
  renderedFinals = 0;
  renderInterim();
  copyEl.hidden = true;
  errorShown = false;

  // 마이크 권한 대화상자가 뜨면 listening까지 수 초 걸린다. 그동안 화면이 그대로면
  // 소리 단서가 없는 사용자는 버튼이 눌렸는지 알 수 없다. 여기서 먼저 알리고,
  // listening 사건이 오면 "듣는 중"이 이 문구를 덮는다.
  setStatusText('마이크를 준비하는 중입니다');
  toggleEl.textContent = '정지';

  recognizer.start();
  acquireWakeLock();
}

function finishSession() {
  if (diagnostics) {
    diagnostics.record({ type: 'status', status: 'idle' }, performance.now());
    copyDiagnosticsEl.hidden = false;
  }
  releaseWakeLock();
  // 복사할 것이 있을 때만 버튼을 내놓는다.
  if (store.getState().finals.length > 0) copyEl.hidden = false;
}

toggleEl.addEventListener('click', () => {
  const status = recognizer.getStatus();
  if (status === 'stopping') return;
  if (status === 'idle') startSession();
  else {
    diagnostics?.requestStop();
    recognizer.stop();
  }
});

function changeFont(step) {
  const next = nextFontSize(fontSize, step);
  if (next === fontSize) return;
  keepingScroll(() => {
    fontSize = next;
    captionsEl.style.fontSize = `${fontSize}px`;   // #finals·#interim의 max-width가 따라 움직인다
  });
  saveFontSize(storage, fontSize);
}

fontDownEl.addEventListener('click', () => changeFont(-1));
fontUpEl.addEventListener('click', () => changeFont(1));

copyEl.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(store.toText());
    copyEl.textContent = '복사됨';
  } catch {
    copyEl.textContent = '복사 실패';
  }
  setTimeout(() => {
    copyEl.textContent = '전체 복사';
  }, 1500);
});

copyDiagnosticsEl.addEventListener('click', async () => {
  if (copyingDiagnostics || copyDiagnosticsEl.hidden || !diagnostics) return;
  copyingDiagnostics = true;
  copyDiagnosticsEl.setAttribute('aria-disabled', 'true');
  const session = diagnostics;
  try {
    const environment = describeEnvironment({
      userAgent: navigator.userAgent,
      maxTouchPoints: navigator.maxTouchPoints,
      width: window.screen?.width,
      height: window.screen?.height,
      standalone: window.matchMedia?.('(display-mode: standalone)').matches || navigator.standalone === true,
    });
    // 가용성 조회를 여기서 기다리지 않는다. 사용자 클릭 안에서 바로 복사를 요청한다.
    await navigator.clipboard.writeText(session.toText({ environment, fontSize, availability }));
    if (diagnostics === session) setStatusText('진단 정보를 복사했습니다');
  } catch {
    if (diagnostics === session) setStatusText('진단 정보를 복사하지 못했습니다. 다시 눌러 주세요');
  } finally {
    copyingDiagnostics = false;
    copyDiagnosticsEl.removeAttribute('aria-disabled');
  }
});

// --- 화면 꺼짐 방지 ---
// 한 시간짜리 회의에서 화면이 꺼지면 인식이 함께 죽는다.
// 지원하지 않는 브라우저에서는 조용히 넘어간다. 실패해도 자막은 계속된다.

async function acquireWakeLock() {
  if (!('wakeLock' in navigator)) return;
  try {
    wakeLock = await navigator.wakeLock.request('screen');
  } catch {
    wakeLock = null;
  }
}

async function releaseWakeLock() {
  try {
    await wakeLock?.release();
  } catch {
    // 이미 풀린 경우
  }
  wakeLock = null;
}

// 탭을 벗어났다 돌아오면 잠금이 풀려 있다. 듣는 중이면 다시 잡는다.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && recognizer.getStatus() !== 'idle') {
    acquireWakeLock();
  }
});

// --- 첫 화면 ---

captionsEl.style.fontSize = `${fontSize}px`;

// 서비스워커. 실패해도 앱은 그대로 돈다(캐시가 없을 뿐이다).
// file://이나 지원하지 않는 브라우저에서는 조용히 넘어간다.
// 사용자에게는 알리지 않되 콘솔에는 남긴다. 완전히 삼키면 설치가 안 될 때
// 원인을 찾을 단서가 하나도 없다.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('./sw.js').catch((e) => {
    console.warn('[말동무] 서비스워커 등록 실패:', e.name, e.message);
  });
}

if (!(window.SpeechRecognition || window.webkitSpeechRecognition)) {
  setStatusText(ERROR_TEXT['not-supported']);
  // 페이지 로드 직후라 아직 아무도 포커스를 쥐고 있지 않아 disabled가 안전하다.
  toggleEl.disabled = true;
}
