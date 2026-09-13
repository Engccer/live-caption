# 말동무 웹앱 1차 구현 계획 (병렬 세션)

> **작업 세션에게**: 이 문서와 spec을 둘 다 읽고 시작한다. 단계는 체크박스(`- [ ]`)로 표시돼 있다.
> 자기 절(§5의 자기 세션)만 실행하고 다른 세션의 파일을 만지지 않는다.

**목표**: 청각장애인 교사가 교무회의에서 동료의 말을 눈으로 따라갈 수 있는 한 화면짜리 웹앱을 만든다.

**구조**: 빌드 도구·의존성·서버가 전부 없다. 브라우저 내장 Web Speech API를 쓰는 정적 파일 넷.
순수 로직(`captions.js`)과 브라우저 API 수명주기(`recognition.js`)를 갈라 두어 `node --test`로
브라우저 없이 검증한다.

**기술 스택**: 바닐라 ES 모듈, Web Speech API, `node:test`. 외부 패키지 0개.

**Spec**: `docs/superpowers/specs/2026-09-13-maldongmu-web-v1-design.md`

## 전역 제약 (모든 세션에 적용)

- **언어**: UI 문구·주석·커밋 메시지는 한국어. 변수명·함수명은 영어.
- **이모지 금지**: UI 라벨·버튼·제목에 이모지를 쓰지 않는다. 아이콘도 1차에는 없다.
- **em dash(`—`) 금지**: UI 문구와 사용자에게 보이는 텍스트에 쓰지 않는다. 코드·문서 본문은 무관.
- **의존성 추가 금지**: `npm install`을 실행하지 않는다. 외부 패키지를 쓰지 않는다.
- **테스트 실행은 `web/` 디렉터리에서 `node --test`**. ⚠ `node --test test/`처럼 **디렉터리를
  인자로 주면 Node 26이 그것을 모듈로 해석해 `MODULE_NOT_FOUND`로 죽는다.** 테스트 실패처럼
  보이지만 테스트는 돌지도 않은 것이다. 인자 없이 쓰거나 파일을 직접 지정한다
  (`node --test test/captions.test.js`).
- **`web/package.json`은 코디네이터가 이미 만들어 커밋했다. 고치지 않는다.**
- **접근성**: 페이지 전체에서 live region은 `#status` 하나뿐이다. 자막 영역에 걸지 않는다.
  모든 버튼은 접근 가능한 이름을 갖고 터치 타깃 44px 이상, 보이는 포커스 표시를 둔다.
- **커밋**: `git add -A` 금지. 반드시 경로를 지정해 커밋한다(`git commit -- <경로>`).
  커밋 메시지 끝에 `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`를 붙인다.

---

## §1 마일스톤과 모델 배정

| 세션 | 이름 | 하는 일 | 모델 | 근거 |
|---|---|---|---|---|
| A | `maldongmu-recognition` | 인식 수명주기와 끊김 복구 | `opus` | 절차가 정본. spec에 계약이 박혀 있고 스파이크 코드를 이식한다 |
| B | `maldongmu-screen` | 화면·스타일·자막 규칙 | `fable` | 판단이 정본. 시각 디자인과 대비·여백을 새로 고른다 |
| C | `maldongmu-docs` | 문서 정비와 `doc-audit` | `opus` | 절차가 정본. `doc-audit` 스킬이 판정 기준을 이미 들고 있다 |

### 확정된 판정 (spec §확정된 판정 참조, 다시 묻지 않는다)

1. 사용 상황은 교무회의·연수. 화자 여럿, 세션이 길다.
2. 기록을 남기지 않는다. 정지했을 때만 복사 버튼이 나타난다.
3. 글자 크기 조절 버튼 둘(작게·크게), 고른 값은 `localStorage`에 기억.
4. 앱 이름은 **말동무**.
5. 자막은 문단으로 쌓인다(텔레프롬프터형 기각).
6. 고지 문구는 기기를 가리지 않고 같은 것을 항상 표시한다.

---

## §2 파일 소유권 지도

**관측 기준 SHA**: 아래 §3의 `git log -1` 결과를 각 세션이 자기 보고서 머리에 적는다.

| 세션 | 소유 파일 (이 밖은 만지지 않는다) |
|---|---|
| A | `web/recognition.js`, `web/test/recognition.test.js`, `web/test/helpers/fake-speech.js` |
| B | `web/index.html`, `web/captions.js`, `web/test/captions.test.js`, `web/test/index-contract.test.js` |
| C | `README.md`, `CHANGELOG.md`, `docs/BACKLOG.md`, `PROGRESS.md`, `CLAUDE.md`, `AGENTS.md` |
| 코디네이터 | `web/package.json`, `web/app.js`, 이 계획 문서, spec |

**겹침 0.** `web/test/` 디렉터리를 A와 B가 공유하지만 파일 이름이 다르므로 충돌하지 않는다.
git은 디렉터리를 추적하지 않는다.

**주의할 공유 자원**(worktree가 격리해 주지 않는 것):

- `git stash`는 저장소 전역 스택이다. 쓰지 말고 바로 커밋한다.
- TTS 요약 파일(`~/.claude/tts-summary.txt`)은 머신에 한 벌이다. **작업 세션은 쓰지 않는다.**
  런처가 `TTS_SUMMARY=off`를 심는다. 사용자에게 꼭 닿아야 할 것은 코디네이터에게 보고한다.
- `CLAUDE.md`·`AGENTS.md`는 C의 소유다. A·B는 읽기만 한다.
  ⚠ C가 `CLAUDE.md`를 고치면 `python sync_agent_docs.py`로 `AGENTS.md`를 재생성한다
  (워크스페이스 루트에서 실행. `AGENTS.md`를 직접 손으로 고치지 않는다).

---

## §3 git 격리 절차

⚠ **이 저장소에는 `origin`이 없다.** 로컬 `main`이 유일한 정본이다.
따라서 통합은 push가 아니라 **로컬 `main`으로의 fast-forward 병합**이다.

```bash
# 착수 (코디네이터가 미리 만들어 둔다. 세션은 cd만 한다)
cd ~/live-caption-wt/<name>

# 작업: 자기 브랜치에만, 경로 지정 커밋
git commit -- web/recognition.js web/test/recognition.test.js -m "..."

# 통합 (게이트 통과 후)
git rebase main
cd ~/live-caption-wt/<name>/web && node --test   # 게이트 재확인
git -C ~/Mac-Projects/live-caption merge --ff-only feat/<name>
```

- `--force` 금지. ff 병합이 거부되면 다른 세션이 먼저 올린 것이므로 `git rebase main`부터 다시 한다.
- **ff 병합의 조건**: 코디네이터의 메인 트리가 그 파일에 대해 clean해야 한다. 코디네이터는
  `web/package.json`과 계획 문서를 착수 전에 커밋해 두었다.
- rebase 뒤 커밋 전, 공유 문서를 만졌다면 소실 줄을 전수 대조한다.

```bash
base=$(git rev-parse main)
comm -23 <(git show $base:CHANGELOG.md | sort) <(sort CHANGELOG.md)
```

  출력된 줄은 전부 **자기가 의도적으로 지운 것**이어야 한다. (C 세션만 해당)

- 통합이 끝나면 worktree를 정리한다: `git worktree remove ~/live-caption-wt/<name>`

---

## §4 웨이브

**웨이브 1: A·B·C 동시.** 파일이 겹치지 않고 의존성 설치가 0이라 동시 착수가 안전하다.
(이 프로젝트는 `npm install`이 없어 병렬 세션의 대표 위험인 동시 설치 메모리 폭증이 성립하지 않는다.)

**웨이브 2: 코디네이터가 `web/app.js`를 쓴다.** A와 B의 산출물이 둘 다 `main`에 올라온 뒤
시작한다. 이 시점에는 작업 세션이 끝나 있으므로 "코디네이터는 코드를 만지지 않는다"는 계약과
충돌하지 않는다(동시 편집이 아니다). 규모가 작아 세션을 하나 더 띄우는 비용이 이득을 넘는다.

**웨이브 3: 배포.** 자율성 헌장 하드 스톱 2번(외부 배포)에 걸리므로 위원장 승인 뒤에만 한다.

---
## §5 세션별 과제

### 세션 A: `maldongmu-recognition`

**목표**: 인식을 켜고 끄고, 끊기면 스스로 복구하는 모듈. 브라우저 없이 전부 테스트한다.

**참조 원본**: `spike/web/index.html`. 아래 수치와 절차는 전부 그 파일에서 실측으로 얻었다.
새로 설계하지 말고 **옮겨 온 뒤 모듈 경계에 맞게 정리한다.**

**Produces** (세션 B·코디네이터가 의존하는 것):

```js
export function createRecognizer(deps);
//   .start()      인식 시작
//   .stop()       사용자 정지. 이후 자동 재시작하지 않는다
//   .getStatus()  -> 'idle' | 'listening' | 'recovering' | 'stopping'
```

`onEvent`가 받는 사건 넷:

```js
{ type: 'status', status: 'idle' | 'listening' | 'recovering' | 'stopping' }
{ type: 'final',   text: string }
{ type: 'interim', text: string }
{ type: 'error',   kind: 'not-supported' | 'permission-denied' | 'no-speech' | 'unknown', message: string }
```

**Consumes**: 없다. 이 세션은 누구도 기다리지 않는다.

---

#### Task A1: 테스트 하네스

- [ ] **Step 1: `web/test/helpers/fake-speech.js`를 만든다**

이 파일이 나머지 태스크 전부의 토대다. 가짜 타이머는 실제 시간을 기다리지 않고
`advance(ms)`로 시간을 앞당긴다. 그래서 "5초 뒤 재시작"을 5초 기다리지 않고 검증한다.

```js
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
```

- [ ] **Step 2: 하네스가 도는지 확인하는 테스트를 `web/test/recognition.test.js`에 쓴다**

```js
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
```

- [ ] **Step 3: 실패를 확인한다**

```bash
cd ~/live-caption-wt/recognition/web && node --test test/recognition.test.js
```

기대: `Cannot find module '../recognition.js'`로 실패한다.

- [ ] **Step 4: `web/recognition.js`의 최소 구현을 쓴다**

`createRecognizer(deps)`가 기본값을 채우고(`lang='ko-KR'`, `restartDelayMs=5000`,
`startRetryDelayMs=250`, `maxStartRetries=5`, `stopTimeoutMs=2000`,
`timers={setTimeout,clearTimeout}`), `start()`에서 인식 객체를 만들어 `start()`를 부르고,
`onstart`에서 상태를 `listening`으로 올린다. 상태는 **바뀔 때만** 사건을 낸다.

`SpeechRecognitionCtor`가 없으면(`undefined`) `start()`가
`{ type:'error', kind:'not-supported' }`를 내고 아무것도 하지 않는다.

- [ ] **Step 5: 통과를 확인하고 커밋한다**

```bash
node --test test/recognition.test.js
git commit -- web/recognition.js web/test/ -m "$(cat <<'MSG'
feat(web): 인식 모듈 골격과 테스트 하네스

가짜 타이머와 가짜 SpeechRecognition으로 브라우저 없이 검증한다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

#### Task A2: 확정 결과와 중간 결과

- [ ] **Step 1: 실패 테스트를 더한다**

```js
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
```

- [ ] **Step 2: 실패를 확인한다** (`node --test test/recognition.test.js`)

- [ ] **Step 3: `onresult` 처리를 구현한다**

`event.resultIndex`부터 `event.results.length`까지 돌며 `results[i].isFinal`로 가른다.
텍스트는 `results[i][0].transcript`를 `trim()`한 것이다. 빈 문자열이면 사건을 내지 않는다.
중간 결과가 여럿이면 **공백 하나로 이어** 한 번만 낸다.

- [ ] **Step 4: 통과를 확인하고 커밋한다** (`feat(web): 인식 결과를 확정·중간 사건으로 가른다`)

---

#### Task A3: 끊김 자동 복구

실측 근거: iPhone Safari가 약 40.2초 간격으로 인식을 끊는다(487초 동안 12회).
`end` 직후 바로 열면 `audiostart`만 오고 실제 오디오가 오지 않아 **5초를 기다린다.**

- [ ] **Step 1: 실패 테스트를 더한다**

```js
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
```

- [ ] **Step 2: 실패를 확인한다**

- [ ] **Step 3: 재시작 예약을 구현한다**

사용자 정지 여부를 `running` 플래그로 가른다. `onend`에서 `running`이면
상태를 `recovering`으로 바꾸고 `restartDelayMs` 뒤 재시작을 예약한다.
예약이 이미 있으면 새로 잡지 않는다.

- [ ] **Step 4: 통과를 확인하고 커밋한다** (`feat(web): 끊긴 인식을 5초 뒤 자동 복구`)

---

#### Task A4: `start()` 실패 백오프

실측 근거: Safari는 `end` 직후 `start()`에 `InvalidStateError`를 던진다.

- [ ] **Step 1: 실패 테스트를 더한다**

```js
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
```

- [ ] **Step 2: 실패를 확인한다**

- [ ] **Step 3: 백오프를 구현한다**

`start()`를 `try`로 감싸고, 던지면 `startRetryDelayMs` 뒤 재시도한다.
시도 횟수가 `maxStartRetries`를 넘으면 `running`을 내리고 `error` 사건을 낸 뒤 `idle`로 끝낸다.

- [ ] **Step 4: 통과를 확인하고 커밋한다** (`feat(web): start 실패에 백오프 재시도`)

---

#### Task A5: 세대 가드 (죽은 인식의 지각 이벤트)

**이 태스크가 없으면 재현하기 어려운 유령 버그가 생긴다.** 브라우저가 버린 인식 객체가
뒤늦게 이벤트를 쏘면, 이미 새로 시작한 세션의 상태를 엉뚱하게 덮어쓴다.

- [ ] **Step 1: 실패 테스트를 더한다**

```js
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
```

- [ ] **Step 2: 실패를 확인한다**

- [ ] **Step 3: 세대 번호를 구현한다**

세션마다 `generation`을 하나 올리고, 이벤트 핸들러를 만들 때 그 값을 가둔다(클로저).
핸들러가 불릴 때 `가둔 값 !== 현재 generation`이거나 `이 객체 !== 현재 인식 객체`면
아무 일도 하지 않는다. 스파이크의 `current(handler)` 래퍼와 같은 방식이다.

- [ ] **Step 4: 통과를 확인하고 커밋한다** (`feat(web): 세대 가드로 지각 이벤트 차단`)

---

#### Task A6: 오류 매핑과 정지 타임아웃

⚠ **핵심 판정**: `no-speech`는 조용한 회의에서 정상적으로 발생한다. 오류로 취급해
상태 줄을 바꾸면 사용자가 고장으로 오해한다. 사건은 내되 재시작 흐름은 평소와 같다.

- [ ] **Step 1: 실패 테스트를 더한다**

```js
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
```

- [ ] **Step 2: 실패를 확인한다**

- [ ] **Step 3: 매핑과 타임아웃을 구현한다**

```js
const ERROR_KINDS = {
  'not-allowed': 'permission-denied',
  'service-not-allowed': 'permission-denied',
  'no-speech': 'no-speech',
};
```

`aborted`는 우리가 의도한 중단(`stopping`이 켜져 있거나 우리가 `abort()`를 부른 직후)이면
사건을 내지 않고, 그렇지 않으면 `unknown`으로 올린다.
`permission-denied`를 받으면 `running`을 내려 재시작 예약이 잡히지 않게 한다.
`stop()`은 `stopTimeoutMs` 타이머를 걸고, `onend`가 오면 그 타이머를 지운다.

- [ ] **Step 4: 통과를 확인한다**

```bash
node --test        # web/ 디렉터리에서. 이 세션의 모든 테스트가 통과해야 한다
```

- [ ] **Step 5: 커밋하고 통합한다**

```bash
git commit -- web/recognition.js web/test/ -m "feat(web): 오류 매핑과 정지 타임아웃"
git rebase main
cd web && node --test && cd ..
git -C ~/Mac-Projects/live-caption merge --ff-only feat/recognition
```

- [ ] **Step 6: 보고서를 쓴다**

`~/live-caption-wt/recognition-reports/report.md`에 관측 SHA, 변경 파일, 테스트 결과,
미결 사항을 적는다. 그다음 코디네이터에게 `SendMessage`로 알린다.

---
### 세션 B: `maldongmu-screen`

**목표**: 화면과 자막 규칙. 눈으로 읽는 사람이 최종 사용자이므로 **가독성이 기능이다.**

**Produces** (코디네이터가 의존하는 것): `web/captions.js`의 내보내기 전부와
`web/index.html`의 DOM id 계약.

**Consumes**: 없다. 세션 A를 기다리지 않는다.

⚠ **`web/app.js`를 쓰지 않는다.** 코디네이터가 웨이브 2에서 쓴다. 화면이 실제로 도는 것을
보고 싶어도 `app.js`를 만들지 말고, 대신 테스트로 검증한다.

---

#### Task B1: 자막 저장소

- [ ] **Step 1: `web/test/captions.test.js`에 실패 테스트를 쓴다**

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createCaptionStore } from '../captions.js';

test('확정 문단이 넣은 순서대로 쌓인다', () => {
  const store = createCaptionStore();
  store.appendFinal('첫 번째 발언입니다');
  store.appendFinal('두 번째 발언입니다');
  assert.deepEqual(store.getState().finals, ['첫 번째 발언입니다', '두 번째 발언입니다']);
});

test('중간 결과는 누적되지 않고 교체된다', () => {
  const store = createCaptionStore();
  store.setInterim('오늘 회의');
  store.setInterim('오늘 회의는 세 시에');
  assert.equal(store.getState().interim, '오늘 회의는 세 시에');
});

test('확정이 들어오면 중간 결과를 비운다', () => {
  const store = createCaptionStore();
  store.setInterim('말하는 중');
  store.appendFinal('말하는 중이었습니다');
  assert.equal(store.getState().interim, '');
});

test('빈 문자열과 공백뿐인 확정은 무시한다', () => {
  const store = createCaptionStore();
  store.appendFinal('');
  store.appendFinal('   ');
  store.appendFinal('\n\t');
  assert.deepEqual(store.getState().finals, []);
});

test('확정 문단의 앞뒤 공백을 다듬는다', () => {
  const store = createCaptionStore();
  store.appendFinal('  다듬어진 문장  ');
  assert.deepEqual(store.getState().finals, ['다듬어진 문장']);
});

test('toText는 확정 문단만 줄바꿈으로 잇는다', () => {
  const store = createCaptionStore();
  store.appendFinal('첫 줄');
  store.appendFinal('둘째 줄');
  store.setInterim('아직 확정 안 된 말');
  assert.equal(store.toText(), '첫 줄\n둘째 줄');
});

test('clear는 전부 비운다', () => {
  const store = createCaptionStore();
  store.appendFinal('지워질 문장');
  store.setInterim('이것도');
  store.clear();
  assert.deepEqual(store.getState(), { finals: [], interim: '' });
});

test('getState가 돌려준 배열을 바꿔도 저장소가 오염되지 않는다', () => {
  const store = createCaptionStore();
  store.appendFinal('원본');
  store.getState().finals.push('침입자');
  assert.deepEqual(store.getState().finals, ['원본']);
});
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd ~/live-caption-wt/screen/web && node --test test/captions.test.js
```

- [ ] **Step 3: `web/captions.js`에 저장소를 구현한다**

배열 하나와 문자열 하나를 들고 있는 클로저면 충분하다. `getState()`는 **복사본**을 돌려준다
(마지막 테스트가 이것을 요구한다).

- [ ] **Step 4: 통과를 확인하고 커밋한다**

```bash
git commit -- web/captions.js web/test/captions.test.js -m "$(cat <<'MSG'
feat(web): 자막 저장소

확정 문단은 쌓고 중간 결과는 교체한다. 복사 전문에는 확정만 넣는다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

#### Task B2: 글자 크기

- [ ] **Step 1: 실패 테스트를 더한다**

```js
import {
  FONT_STEPS, DEFAULT_FONT_SIZE, nextFontSize, loadFontSize, saveFontSize,
} from '../captions.js';

// localStorage를 흉내 낸다. 실패하는 경우까지 시험한다.
function fakeStorage({ throwOnGet = false, throwOnSet = false, initial = {} } = {}) {
  const data = { ...initial };
  return {
    getItem(key) {
      if (throwOnGet) throw new Error('SecurityError');
      return key in data ? data[key] : null;
    },
    setItem(key, value) {
      if (throwOnSet) throw new Error('QuotaExceededError');
      data[key] = String(value);
    },
    get data() { return data; },
  };
}

test('기본 크기가 단계 목록 안에 있다', () => {
  assert.ok(FONT_STEPS.includes(DEFAULT_FONT_SIZE));
});

test('단계 목록이 오름차순이다', () => {
  assert.deepEqual(FONT_STEPS, [...FONT_STEPS].sort((a, b) => a - b));
});

test('한 단계씩 오르내린다', () => {
  assert.equal(nextFontSize(28, 1), 34);
  assert.equal(nextFontSize(28, -1), 24);
});

test('목록 양 끝을 넘지 않는다', () => {
  const min = FONT_STEPS[0];
  const max = FONT_STEPS.at(-1);
  assert.equal(nextFontSize(min, -1), min);
  assert.equal(nextFontSize(max, 1), max);
});

test('목록에 없는 크기가 들어와도 가장 가까운 단계에서 움직인다', () => {
  assert.equal(nextFontSize(30, 1), 34);
  assert.equal(nextFontSize(30, -1), 28);
});

test('저장값이 없으면 기본값을 준다', () => {
  assert.equal(loadFontSize(fakeStorage()), DEFAULT_FONT_SIZE);
});

test('저장값이 손상되거나 목록 밖이면 기본값을 준다', () => {
  assert.equal(loadFontSize(fakeStorage({ initial: { 'maldongmu.fontSize': 'abc' } })), DEFAULT_FONT_SIZE);
  assert.equal(loadFontSize(fakeStorage({ initial: { 'maldongmu.fontSize': '999' } })), DEFAULT_FONT_SIZE);
});

test('저장한 값을 그대로 돌려준다', () => {
  const storage = fakeStorage();
  saveFontSize(storage, 40);
  assert.equal(loadFontSize(storage), 40);
});

test('저장소가 막혀 있어도 앱이 죽지 않는다', () => {
  // 사파리 비공개 모드에서 실제로 일어난다.
  assert.equal(loadFontSize(fakeStorage({ throwOnGet: true })), DEFAULT_FONT_SIZE);
  assert.doesNotThrow(() => saveFontSize(fakeStorage({ throwOnSet: true }), 40));
});

test('storage가 아예 없어도 죽지 않는다', () => {
  assert.equal(loadFontSize(undefined), DEFAULT_FONT_SIZE);
  assert.doesNotThrow(() => saveFontSize(undefined, 40));
});
```

- [ ] **Step 2: 실패를 확인한다**

- [ ] **Step 3: 구현한다**

`FONT_STEPS = [20, 24, 28, 34, 40, 48]`, `DEFAULT_FONT_SIZE = 28`,
저장 키는 `'maldongmu.fontSize'`.

`nextFontSize`의 규칙은 한 문장이다: **위로는 지금보다 큰 첫 단계, 아래로는 지금보다 작은
첫 단계.** 그런 단계가 없으면 지금 값을 그대로 둔다.

이 한 문장이 세 경우를 모두 덮는다. 목록에 있는 값(28 → 34 / 24), 목록에 없는 값
(30 → 34 / 28), 양 끝(48 → 48, 20 → 20). "가장 가까운 단계를 찾아 거기서 움직인다"로
쓰면 30에서 내릴 때 24가 나와 테스트와 어긋난다.

저장소 접근은 전부 `try`로 감싼다.

- [ ] **Step 4: 통과를 확인하고 커밋한다** (`feat(web): 글자 크기 단계와 저장`)

---

#### Task B3: 자동 스크롤 판정

**이 함수가 화면의 핵심이다.** 새 자막이 와도 사용자가 놓친 대목을 읽고 있으면
화면을 채가면 안 된다.

- [ ] **Step 1: 실패 테스트를 더한다**

```js
import { shouldAutoScroll } from '../captions.js';

test('맨 아래에 있으면 따라간다', () => {
  assert.equal(shouldAutoScroll({ scrollTop: 800, scrollHeight: 1000, clientHeight: 200 }), true);
});

test('위로 올려 읽고 있으면 따라가지 않는다', () => {
  assert.equal(shouldAutoScroll({ scrollTop: 100, scrollHeight: 1000, clientHeight: 200 }), false);
});

test('바닥에서 임계값 안이면 따라간다', () => {
  // 바닥까지 남은 거리 = 1000 - 200 - 770 = 30
  assert.equal(shouldAutoScroll({ scrollTop: 770, scrollHeight: 1000, clientHeight: 200 }), true);
});

test('임계값을 넘으면 따라가지 않는다', () => {
  // 남은 거리 = 100
  assert.equal(shouldAutoScroll({ scrollTop: 700, scrollHeight: 1000, clientHeight: 200 }), false);
});

test('임계값을 직접 줄 수 있다', () => {
  assert.equal(shouldAutoScroll({ scrollTop: 700, scrollHeight: 1000, clientHeight: 200 }, 150), true);
});

test('내용이 화면보다 짧으면 따라간다', () => {
  assert.equal(shouldAutoScroll({ scrollTop: 0, scrollHeight: 150, clientHeight: 200 }), true);
});
```

- [ ] **Step 2: 실패를 확인한다**

- [ ] **Step 3: 구현한다**

`scrollHeight - clientHeight - scrollTop <= threshold`. 기본 `threshold`는 48이다.

- [ ] **Step 4: 통과를 확인하고 커밋한다** (`feat(web): 자동 스크롤 판정`)

---

#### Task B4: 화면

**이 태스크에는 디자인 판단이 들어간다.** spec의 제약 안에서 고르되, 고른 이유를
보고서에 한 줄씩 남긴다.

지켜야 할 것:

- **DOM id 계약**: `#status` `#captions` `#finals` `#interim` `#toggle` `#fontDown` `#fontUp`
  `#copy` `#notice`. `app.js`가 이 이름으로 찾는다. **바꾸면 통합이 깨진다.**
- `#copy`는 `hidden` 상태로 시작한다.
- **live region은 `#status` 하나뿐**이다(`role="status"`). 자막 영역에 걸지 않는다.
- **중간 결과를 `opacity`로 흐리게 하지 않는다.** 대비가 깎인다. 대비 4.5:1 이상을 지키는
  별도 색을 쓴다.
- 버튼 라벨은 "시작" / "정지" / "글자 작게" / "글자 크게" / "전체 복사". 이모지·기호 금지.
- 터치 타깃 44px 이상, 보이는 포커스 표시.
- 라이트·다크 모두에서 읽힌다(`color-scheme`, `prefers-color-scheme`).
- 자막 한 줄이 너무 길지 않게 `max-width`로 읽기 폭을 제한한다.
- 세로 화면(폰)에서 자막 영역이 화면의 대부분을 차지하고, 컨트롤 바가 아래에 고정된다.
- 고지 문구 초안: `음성은 브라우저의 인식 서비스로 전송되어 처리됩니다.`
  (⚠ 이 문구는 **위원장이 직접 확정한다.** 초안 그대로 넣고 보고서에 "문안 확정 필요"라고 적는다.)

- [ ] **Step 1: `web/test/index-contract.test.js`에 계약 테스트를 쓴다**

화면을 눈으로 볼 수 없어도 계약이 지켜졌는지는 기계가 잴 수 있다.

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('app.js가 찾는 id가 모두 있다', () => {
  for (const id of ['status', 'captions', 'finals', 'interim',
                    'toggle', 'fontDown', 'fontUp', 'copy', 'notice']) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `#${id}가 없다`);
  }
});

test('live region은 하나뿐이다', () => {
  const liveRegions = html.match(/role=["']status["']|role=["']alert["']|aria-live=/g) ?? [];
  assert.equal(liveRegions.length, 1, '자막 영역에 live region을 걸지 않는다');
});

test('복사 버튼은 숨긴 채로 시작한다', () => {
  assert.match(html, /<button[^>]*id=["']copy["'][^>]*hidden/);
});

test('UI 라벨에 이모지를 쓰지 않는다', () => {
  const emoji = html.match(/\p{Extended_Pictographic}/gu) ?? [];
  assert.deepEqual(emoji, []);
});

test('사용자에게 보이는 문구에 em dash를 쓰지 않는다', () => {
  assert.equal(html.includes('—'), false);
});

test('모듈로 app.js를 불러온다', () => {
  assert.match(html, /<script[^>]+type=["']module["'][^>]+src=["']\.?\/?app\.js["']/);
});

test('한국어 문서로 선언한다', () => {
  assert.match(html, /<html[^>]+lang=["']ko["']/);
});
```

- [ ] **Step 2: 실패를 확인한다** (`node --test test/index-contract.test.js`)

- [ ] **Step 3: `web/index.html`을 쓴다**

스타일은 `<style>`로 문서 안에 둔다(파일 하나 줄이는 편이 포크하는 사람에게 낫다).
`app.js`는 아직 없지만 `<script type="module" src="./app.js"></script>`로 걸어 둔다.
코디네이터가 웨이브 2에서 채운다.

- [ ] **Step 4: 통과를 확인한다**

```bash
node --test        # web/ 에서. 이 세션의 테스트가 전부 통과해야 한다
```

- [ ] **Step 5: 커밋하고 통합한다**

```bash
git commit -- web/index.html web/test/index-contract.test.js -m "feat(web): 말동무 화면"
git rebase main
cd web && node --test && cd ..
git -C ~/Mac-Projects/live-caption merge --ff-only feat/screen
```

- [ ] **Step 6: 보고서를 쓴다**

`~/live-caption-wt/screen-reports/report.md`에 관측 SHA, 변경 파일, 테스트 결과,
**고른 디자인 값과 이유**(기본 글자 크기, 중간 결과 색과 대비비, 최대 읽기 폭),
고지 문안 확정 필요를 적는다. 그다음 코디네이터에게 `SendMessage`로 알린다.

---

### 세션 C: `maldongmu-docs`

**목표**: 이 저장소의 필수 문서를 갖추고 낡은 서술을 정리한다. 앱 코드를 만지지 않는다.

세션 시작 때 `doc-audit` 경고가 떠 있다.

```
[doc-audit] live-caption: 마지막 점검 기록 없음(미점검)
  - 필수 문서 누락: README.md, CHANGELOG.md, docs/BACKLOG.md
  - CLAUDE.md: 코드에 없는 심볼 2(SFSpeechRecognizer, SpeechAnalyzer)
  - PROGRESS.md: 코드에 없는 심볼 3(SFSpeechRecognizer, SpeechAnalyzer, SpeechTranscriber)
```

- [ ] **Step 1: `doc-audit` 스킬을 부른다.** 절차는 그 스킬이 정본이다. 여기 재서술하지 않는다.

- [ ] **Step 2: `README.md`를 새로 쓴다 (얇게)**

무엇·설치·실행·문서 링크만. 규칙·아키텍처·함정은 `CLAUDE.md`에만 둔다.
둘이 같은 문장을 들면 한쪽이 반드시 낡는다. 이 저장소의 실행법은 특히 짧다:
정적 파일이라 `npx serve web`이면 끝이고 의존성이 없다.

- [ ] **Step 3: `CHANGELOG.md`를 만든다**

`git log`에서 날짜별 변경을 뽑아 채운다. 항목당 2~4줄.
2026-09-13 항목에 이번 웹앱 1차 착수와 spec 링크를 넣는다.

- [ ] **Step 4: `docs/BACKLOG.md`를 `PROGRESS.md`에서 분리한다**

`PROGRESS.md`의 「미결 결정」과 「남은 검증 과제」가 백로그다. 옮기고 폐기 근거를 보존한다.
`PROGRESS.md`에는 **지금 참인 상태만** 남긴다.

⚠ 판별 질문: *"이 문장은 지금도 참이라서 여기 있는가, 그때 그랬어서 여기 있는가?"*
후자면 CHANGELOG다.

- [ ] **Step 5: 코드에 없는 심볼 경고를 처리한다**

`SFSpeechRecognizer`·`SpeechAnalyzer`·`SpeechTranscriber`는 **아직 쓰지 않은 iOS API의 이름**이다.
코드에 없는 것이 정상이다. 지우지 말고 **"iOS 단계에서 검토할 후보"라는 맥락이 분명하도록**
문장을 다듬는다. `doc-audit`의 잡음 기록에도 남긴다.

- [ ] **Step 6: `CLAUDE.md`를 고쳤으면 `AGENTS.md`를 재생성한다**

```bash
cd ~/Mac-Projects && python sync_agent_docs.py
```

손으로 `AGENTS.md`를 고치지 않는다. 생성물이다.

- [ ] **Step 7: 커밋하고 통합한다**

```bash
git commit -- README.md CHANGELOG.md docs/BACKLOG.md PROGRESS.md CLAUDE.md AGENTS.md -m "docs: 필수 문서 정비"
git rebase main
base=$(git rev-parse main)
comm -23 <(git show $base:PROGRESS.md | sort) <(sort PROGRESS.md)   # 소실 줄 전수 대조
git -C ~/Mac-Projects/live-caption merge --ff-only feat/docs
```

`comm` 출력은 전부 **자기가 의도적으로 옮기거나 지운 줄**이어야 한다.

- [ ] **Step 8: 보고서를 쓴다**

`~/live-caption-wt/docs-reports/report.md`에 관측 SHA, 만든 문서, `doc-audit` 판정,
잡음으로 분류한 것과 그 이유를 적는다.

---

## §6 웨이브 2: 통합 (코디네이터)

A와 B가 둘 다 `main`에 올라온 뒤 코디네이터가 `web/app.js`를 쓴다. 하는 일은 배선뿐이다.

- 상태별 문구 매핑. spec의 표를 그대로 옮긴다.

```js
const STATUS_TEXT = {
  idle: '시작을 누르면 자막이 나옵니다',
  listening: '듣는 중',
  recovering: '연결이 끊겨 복구하는 중입니다',
  stopping: '정지하는 중',
};
const ERROR_TEXT = {
  'not-supported': '이 브라우저는 음성 인식을 지원하지 않습니다. 크롬이나 사파리로 열어 주세요',
  'permission-denied': '마이크를 허용해 주세요',
};
// no-speech와 unknown은 상태 줄을 건드리지 않는다. 조용한 회의가 고장으로 보이면 안 된다.
```

- 미지원 브라우저 판정 후 시작 버튼 비활성 + 상태 문구
- `createRecognizer`의 사건을 `createCaptionStore`에 넣고 DOM에 반영
- `shouldAutoScroll`로 스크롤 따라가기 판정
- 글자 크기 버튼과 `localStorage` 연결
- 복사 버튼(`navigator.clipboard.writeText`), 다시 시작하면 자막 비우고 버튼 숨김
- Wake Lock 획득·해제 (지원하지 않으면 조용히 넘어간다)

## §7 완료 조건

1. `cd web && node --test`가 전부 통과한다.
2. `npx serve web`으로 열어 실제 브라우저에서 자막이 나온다.
3. 위원장이 아이폰에서 열어 회의 한 대목을 시험한다.
4. 고지 문안을 위원장이 확정한다.
5. 배포는 위원장 승인 뒤에만 한다.
