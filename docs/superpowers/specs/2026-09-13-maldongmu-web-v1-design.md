# 말동무 웹앱 1차 설계 (2026-09-13)

## 목적

청각장애인 교사가 **교무회의·연수 자리에서** 동료들의 말을 눈으로 따라갈 수 있게 하는
한 화면짜리 웹앱. 주소를 열고 시작 버튼 하나를 누르면 자막이 시작된다. 계정·결제·설정·
서버가 없다.

이 1차본이 검증하려는 것은 **당사자가 이 화면을 쓰고 싶어하는가**이다. 정확도·온디바이스·
비용 구조는 검증 대상이 아니다(`PROGRESS.md` 「프로토타입은 웹앱 먼저」).

## 확정된 판정 (2026-09-13 위원장)

1. **사용 상황은 교무회의·연수**다. 화자 여럿, 세션이 길다(한 시간 이상).
2. **기록은 남기지 않는다.** 탭을 닫거나 새로고침하면 사라진다. 정지했을 때만 전체 복사 버튼이 나타난다.
3. **글자 크기 조절 버튼을 둔다.** 작게·크게 두 개이며 고른 값은 브라우저에 기억된다.
4. **앱 이름은 말동무**다.
5. **자막은 문단으로 쌓인다**(텔레프롬프터형 기각). 되짚어 읽는 것이 교무회의의 핵심 요구이기 때문이다.

## 범위 밖 (1차에 넣지 않는다)

- 화자 라벨·화자 색 구분: Web Speech API가 화자 정보를 주지 않는다(아래 참조).
- 고급 엔진(사용자 본인 키) 설정: 하이브리드 구조는 확정됐으나 1차는 기본 경로만 만든다.
- 번역, 요약, 회의록 내보내기, 계정, 다국어 UI.
- iOS 네이티브 앱.

## 중요한 전제 정정: 화자 전환 신호는 웹에 없다

`PROGRESS.md`의 "화자 전환 신호는 쓸 만하다"는 결론은 Muse·Deepgram이 주던 `speaker`
이벤트를 전제한 것이다. **브라우저 내장 Web Speech API에는 화자 정보가 없다.** 웹앱이
가진 유일한 경계 신호는 엔진이 발화가 끝났다고 판단해 확정 결과(`isFinal`)를 내놓는
순간뿐이다.

따라서 화면에 그리는 단위는 화자가 아니라 **발화 덩어리**다. 회의에서 사람이 바뀌면 대개
사이에 침묵이 생겨 덩어리 경계와 자주 겹치지만 보장되지 않는다. 확정 결과 하나가 문단
하나이고 라벨은 붙이지 않는다(확정된 결정 2번과 같은 방향).

## 화면

세로로 세 덩어리다.

```
+--------------------------------------+
| 상태 한 줄                            |  #status  (단일 live region)
+--------------------------------------+
|                                      |
|  확정 문단 1                          |  #captions (스크롤 컨테이너)
|                                      |    > #finals
|  확정 문단 2                          |    > #interim
|                                      |
|  지금 말하는 중인 문장 (흐림)          |
+--------------------------------------+
| [시작]   [글자 작게] [글자 크게]       |  #controls
| 아이폰 고지 한 줄                      |  #notice
+--------------------------------------+
```

### 상태 줄 (`#status`)

한 자리에서만 바뀌는 문구. 페이지 전체에서 **유일한 live region**이다(`role="status"`).
자막 영역에는 live region을 걸지 않는다(글로벌 접근성 헌장 과잉 live region 금지).

| 상태 | 문구 |
|---|---|
| `idle` | 시작을 누르면 자막이 나옵니다 |
| `listening` | 듣는 중 |
| `recovering` | 연결이 끊겨 복구하는 중입니다 |
| `stopping` | 정지하는 중 |
| 권한 거부 | 마이크를 허용해 주세요 |
| 미지원 브라우저 | 이 브라우저는 음성 인식을 지원하지 않습니다. 크롬이나 사파리로 열어 주세요 |

### 자막 영역 (`#captions`)

- 확정 문단이 위에서 아래로 쌓인다. 문단 사이에 여백을 둔다.
- 맨 아래에 아직 확정되지 않은 문장(`#interim`)이 **다른 색**으로 붙는다.
  `opacity`로 흐리게 하지 않는다. 대비가 깎여 최종 사용자(눈으로 읽는 청각장애인)에게
  불리하다. 대비 4.5:1 이상을 유지하는 별도 색을 쓴다.
- 한 줄이 너무 길면 눈이 줄을 놓치므로 `max-width`로 읽기 폭을 제한한다.

### 자동 스크롤 (이 화면의 핵심)

새 자막이 오면 맨 아래로 따라간다. 그러나 사용자가 놓친 부분을 읽으려고 위로 올리면
그 순간 따라가기를 멈추고, 맨 아래로 돌아오면 다시 따라간다. 버튼도 안내문도 없이
스크롤 위치만으로 판단한다.

판정은 순수 함수 `shouldAutoScroll()`이 하며 테스트 대상이다.

### 컨트롤 (`#controls`)

- `#toggle`: 시작/정지 겸용 버튼 하나. 가장 크다.
- `#fontDown` / `#fontUp`: 라벨은 "글자 작게" / "글자 크게"(이모지·기호 금지).
- `#copy`: 정지했을 때만 나타난다. 확정 자막 전문을 클립보드에 넣는다.
  **다시 시작하면 이전 자막을 지우고 이 버튼을 숨긴다.** 두 회의의 자막이 섞이지 않게
  하려는 것이며, 기록을 남기지 않기로 한 판정과도 맞는다.
- 모든 버튼 터치 타깃 44px 이상, 보이는 포커스 표시.

### 고지 (`#notice`)

**기기를 가리지 않고 같은 문구를 항상 표시한다**(2026-09-13 위원장 판정).

문안 초안:

> 음성은 브라우저의 인식 서비스로 전송되어 처리됩니다.

`"기기 안에서만 처리"`라는 표현을 쓰지 않는다(`PROGRESS.md` 결정).

기기별로 문구를 가르는 안을 기각한 이유는 둘이다. 첫째, 아이폰만 콕 집어 경고하면
노트북으로 여는 사람에게 **잘못된 안심**을 준다. 데스크톱 크롬도 한국어 온디바이스 팩을
따로 내려받기 전까지는 서버로 보낸다. 둘째, `available()` API가 없는 브라우저가 있어
판별 결과가 실제 동작과 어긋날 수 있는데, 어긋났을 때의 대가가 "민감한 대화가 어디로
가는지 잘못 알린 것"이다.

⚠ **문안 확정은 구현 중에 위원장과 직접 왕복해서 한다.** 위 문장은 초안이며, 사용자에게
보이는 문구이므로 렌더된 상태로 확인받는다.

## 끊겨도 이어지게

iPhone Safari는 인식을 제멋대로 끊는다(실측: 약 40.2초 간격으로 487초 동안 12번).
`spike/web/index.html`에서 검증한 복구 절차를 그대로 옮긴다.

- 사용자가 정지하지 않았는데 `end`가 오면 상태를 `recovering`으로 바꾸고 **5초 뒤** 재시작한다.
  (`end` 직후 바로 열면 `audiostart`만 오고 실제 오디오가 오지 않는 현상 때문)
- `start()`가 `InvalidStateError`를 던지면 250ms 뒤 재시도하고 5회까지 시도한다.
- 죽은 인식 객체가 뒤늦게 쏘는 이벤트는 **세대 번호(generation)**로 무시한다.
- 정지 요청 뒤 2초 안에 `end`가 오지 않으면 강제로 마무리한다.

인식 객체 옵션은 `continuous = true`, `interimResults = true`, `maxAlternatives = 1`,
`lang = 'ko-KR'`이다. 결과는 `event.resultIndex`부터 순회해 `isFinal`로 갈라 낸다.

**참조 원본은 `spike/web/index.html`이다.** 위 수치와 절차는 전부 그 파일에서 실측으로
얻은 것이므로, 새로 설계하지 말고 옮겨 온 뒤 모듈 경계에 맞게 정리한다.

**화면 꺼짐 방지**: 자막이 켜진 동안만 Wake Lock을 잡는다. 한 시간 회의에서 화면이 꺼지면
인식이 함께 죽는다. 지원하지 않는 브라우저에서는 조용히 넘어간다(실패해도 자막은 계속된다).

## 코드 구조

빌드 도구가 없다. 포크하는 사람이 `npm install` 없이 파일을 열 수 있어야 한다.

```
web/
  index.html        화면 뼈대 + 스타일
  captions.js       자막 상태와 글자 크기 (순수, DOM 없음)
  recognition.js    인식 수명주기와 끊김 복구 (브라우저 API 주입)
  app.js            위 둘을 DOM에 연결하는 얇은 배선
  test/
    captions.test.js
    recognition.test.js
```

테스트는 `web/` 디렉터리에서 `node --test`로 돈다. 브라우저가 필요 없다.
⚠ `node --test web/test/`처럼 **디렉터리를 인자로 주면 Node 26이 모듈로 해석해
`MODULE_NOT_FOUND`로 죽는다.** 테스트가 실패한 것처럼 보이지만 돌지도 않은 것이다. 스파이크가 쓰던
"HTML에서 정규식으로 `<script>`를 뜯어 `vm`에 넣는" 방식은 버린다. 모듈이 분리되면
그냥 `import`하면 된다.

로컬 확인은 정적 서버로 한다(`npx serve web` 또는 `python3 -m http.server`).
ES 모듈이라 `file://`로는 열리지 않는다.

## 인터페이스 계약

**이 절이 병렬 세션의 경계다.** A와 B는 이 계약만 지키면 서로를 기다리지 않는다.

### `captions.js` (세션 B 소유)

```js
// 자막 저장소. DOM을 모른다.
export function createCaptionStore();
//   .appendFinal(text)   확정 문단 추가. 빈 문자열·공백뿐이면 무시한다.
//   .setInterim(text)    중간 결과를 교체한다(누적하지 않는다).
//   .clear()             전부 비운다.
//   .getState()          -> { finals: string[], interim: string }
//   .toText()            -> string. 확정 문단만 줄바꿈 하나로 이은 복사용 전문.
//                          아직 확정되지 않은 중간 결과는 넣지 않는다.

// 글자 크기
export const FONT_STEPS = [20, 24, 28, 34, 40, 48];  // px 오름차순
export const DEFAULT_FONT_SIZE = 28;
export function nextFontSize(current, step);  // step: -1 | +1. 목록 양 끝을 넘지 않는다.
export function loadFontSize(storage);        // 저장값 없음·손상·목록 밖이면 DEFAULT_FONT_SIZE
export function saveFontSize(storage, px);    // storage 접근 실패는 삼킨다
//   localStorage 키는 'maldongmu.fontSize'

// 자동 스크롤 판정
export function shouldAutoScroll({ scrollTop, scrollHeight, clientHeight }, threshold = 48);
//   맨 아래에서 threshold(px) 이내면 true
```

### `recognition.js` (세션 A 소유)

```js
export function createRecognizer(deps);
//   .start()   인식을 시작한다.
//   .stop()    사용자 정지. 이후 자동 재시작을 하지 않는다.
//   .getStatus() -> 'idle' | 'listening' | 'recovering' | 'stopping'
```

`deps`는 전부 주입된다(테스트에서 가짜로 대체 가능해야 한다).

```js
{
  SpeechRecognitionCtor,   // window.SpeechRecognition || window.webkitSpeechRecognition
  onEvent,                 // (event) => void
  lang: 'ko-KR',
  restartDelayMs: 5000,
  startRetryDelayMs: 250,
  maxStartRetries: 5,
  stopTimeoutMs: 2000,
  timers: { setTimeout, clearTimeout },   // ⚠ 테스트에서만. 아래 경고를 볼 것
}
```

⚠ **`app.js`는 `timers`를 넘기지 않는다**(2026-09-13 Chrome 152 실측). 위 형태를 브라우저에서
그대로 넘기면 `TypeError: Illegal invocation`으로 죽는다. 브라우저의 `setTimeout`은 `Window`의
메서드라 호출 시 `this`가 진짜 `Window`인지 검사하는데, 평범한 객체에 담아
`timers.setTimeout(...)`으로 부르면 `this`가 그 객체가 되어 거부된다.

**Node에는 이 검사가 없어 `node --test`는 전부 통과한다.** 게다가 피해가 재시작 예약에서만
나므로, 아이폰에서 40초 뒤 첫 끊김이 왔을 때 자막이 조용히 멈추고 화면에는 아무 오류도 뜨지
않는다. `recognition.js`의 기본값이 호출을 감싸 두므로 **넘기지 않는 것이 정답**이고,
굳이 넘겨야 하면 감싸서 넘긴다.

`onEvent`가 받는 사건은 넷이다.

```js
{ type: 'status', status: 'idle' | 'listening' | 'recovering' | 'stopping' }
{ type: 'final',   text: string }
{ type: 'interim', text: string }
{ type: 'error',   kind: 'not-supported' | 'permission-denied' | 'no-speech' | 'unknown', message: string }
```

`kind` 매핑은 Web Speech의 `error` 값을 옮긴 것이다. `not-allowed`와 `service-not-allowed`는
`permission-denied`로, `no-speech`는 그대로, 나머지는 `unknown`으로 접는다.

**세 가지를 구별해야 한다.**

- `permission-denied`: 자동 재시작을 하지 않는다. 같은 오류가 무한히 반복된다.
  상태 줄에 "마이크를 허용해 주세요"를 띄운다.
- `no-speech`: **오류로 취급하지 않는다.** 조용한 회의에서 정상적으로 발생한다.
  `error` 사건은 내되 `app.js`는 상태 줄을 건드리지 않고 평소의 끊김 복구 절차로 처리한다.
- ⚠ **`unknown`도 상태 줄을 건드리지 않는다**(2026-09-13 판정). 아이폰은 침묵을 `no-speech`가
  아니라 **`aborted` + 메시지 `No speech detected`**로 보내므로 우리 매핑에서 `unknown`이 된다.
  이것을 상태 줄에 띄우면 조용한 교무회의에서 **40초마다 오류 문구가 뜬다**(`PROGRESS.md` 실측:
  487초에 12회 끊김). **상태 줄을 바꾸는 오류는 `permission-denied`와 `not-supported` 둘뿐이다.**
  나머지는 `status` 사건이 주는 `recovering`("연결이 끊겨 복구하는 중입니다")이 이미 덮는다.

  메시지 문자열을 보고 `aborted`를 `no-speech`로 접는 대안은 기각했다. 브라우저 문구가 바뀌면
  조용히 깨지고, 계약을 바꾸는 일이기도 하다.

  ⚠ **이 결정의 대가**: 진짜 장애(`network` 등)도 상태 줄에 뜨지 않는다. 자막이 안 나오는데
  화면은 "복구하는 중"만 보여 준다. 1차는 단순함을 택하고, 실사용에서 이 상황이 실제로
  혼란을 주는지 확인한 뒤 재검토한다(`docs/BACKLOG.md`).
- `aborted`: 정지·재시작 과정에서 정상적으로 발생한다. 우리가 의도한 중단이면 사건을
  내지 않고, 그렇지 않으면 `unknown`으로 올린다.

### `index.html`의 DOM 계약 (세션 B 소유, app.js가 의존)

`#status` `#captions` `#finals` `#interim` `#toggle` `#fontDown` `#fontUp` `#copy` `#notice`

(화면 그림의 `#controls`는 배치용 컨테이너일 뿐이라 `app.js`가 참조하지 않는다.
이름을 바꾸거나 없애도 된다.)

`#copy`는 `hidden` 상태로 시작한다. 글자 크기는 `#captions`에 인라인 `font-size`로 적용한다.

### `app.js` (통합 세션 소유)

세션 A·B가 끝난 뒤 코디네이터가 쓴다. 하는 일은 배선뿐이다.

- 미지원 브라우저 판정 후 시작 버튼 비활성 + 상태 문구
- `recognition` 사건을 `captionStore`에 넣고 DOM에 반영
- 스크롤 판정 호출, 글자 크기 버튼, 복사 버튼, Wake Lock

## 테스트

### `captions.test.js`

- 확정 문단이 넣은 순서대로 쌓인다
- 중간 결과는 교체된다(누적되지 않는다)
- 빈 문자열과 공백뿐인 확정은 무시된다
- `toText()`가 문단을 줄바꿈으로 잇는다
- `nextFontSize()`가 목록 양 끝을 넘지 않는다
- `loadFontSize()`가 저장값 없음·손상값·목록 밖 값에 기본값을 준다
- `saveFontSize()`가 storage 예외를 삼킨다(사파리 비공개 모드)
- `shouldAutoScroll()`이 맨 아래·중간·경계에서 맞는 값을 낸다

### `recognition.test.js`

가짜 `SpeechRecognition`과 가짜 타이머로 돌린다.

- `start()` 후 상태가 `listening`이 된다
- 확정 결과가 `final` 사건으로, 중간 결과가 `interim` 사건으로 나간다
- 사용자 정지 없이 `end`가 오면 `recovering`이 되고 5초 뒤 재시작한다
- 사용자가 정지하면 재시작하지 않는다
- `start()`의 `InvalidStateError`에 250ms 뒤 재시도하고, 5회 실패하면 `error`를 낸다
- 죽은 세대의 이벤트가 상태를 바꾸지 못한다
- 정지 뒤 `end`가 오지 않아도 2초 뒤 `idle`로 끝난다
- `not-allowed` 오류 뒤에는 재시작하지 않는다

## 병렬 세션 분할

| 세션 | 소유 파일 | 하는 일 |
|---|---|---|
| A | `web/recognition.js`, `web/test/recognition.test.js` | 인식 수명주기와 끊김 복구 |
| B | `web/index.html`, `web/captions.js`, `web/test/captions.test.js` | 화면·스타일·자막 규칙 |
| C | `README.md`, `CHANGELOG.md`, `docs/BACKLOG.md` | 문서 정비와 `doc-audit` 경고 처리 |

파일이 겹치지 않는다. `web/app.js`와 배포는 A·B 완료 뒤 코디네이터 세션이 맡는다.

규모가 작아 병렬의 이득이 크지 않다는 점은 위원장에게 이미 고지했다.

## 배포

Vercel 정적 호스팅(서버 0). **배포 실행은 자율성 헌장 하드 스톱 2번(외부 발신·배포)에
걸리므로 위원장 승인 뒤에 한다.** 도메인 후보는 `maldongmu.dodoplanet.space`.

`spike/web/`의 기존 임시 배포(`live-caption-spike.vercel.app`)는 아이폰 로그 판독이 끝나면
`vercel remove`로 정리한다(별도 메모리 항목).

## 성공 판정

1. 선생님이 링크를 받아 열고 **시작 한 번**으로 자막이 나온다(설명 없이).
2. 한 시간 회의 동안 끊겨도 사용자가 손대지 않고 자막이 이어진다.
3. 놓친 대목을 위로 올려 읽는 동안 새 자막이 화면을 채가지 않는다.
4. "이걸 실제 회의에서 쓰겠다"는 답이 나온다. 안 나오면 무엇이 부족한지가 다음 설계의 입력이다.

## 설계 리뷰 판정

**적대적 리뷰 생략.** 이 spec은 상태 머신(`idle`/`listening`/`recovering`/`stopping`)과
끊김 복구 불변식을 담아 리뷰 판별 기준 ①에 걸리지만, 그 상태 머신은 새 설계가 아니라
`spike/web/index.html`에서 실측으로 검증을 마친 절차의 이식이다. 외부 통합은 브라우저 내장
API 하나이고 실호출로 확인했다. 프로토타입이라 마이그레이션·저장 포맷·보안 면에서 비가역
결정이 없다. 구현 뒤 묶음별 서브에이전트 리뷰로 충분하다고 본다.
