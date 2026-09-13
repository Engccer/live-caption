// 자막 상태와 화면 규칙. DOM도 브라우저 API도 모른다.

// 확정 문단을 쌓고 중간 결과 하나를 들고 있는 저장소.
export function createCaptionStore() {
  let finals = [];
  let interim = '';

  return {
    // 확정 문단을 더한다. 빈 문자열과 공백뿐인 값은 무시한다.
    appendFinal(text) {
      const trimmed = String(text ?? '').trim();
      interim = '';
      if (trimmed === '') return;
      finals.push(trimmed);
    },

    // 중간 결과를 교체한다. 누적하지 않는다.
    setInterim(text) {
      interim = String(text ?? '');
    },

    clear() {
      finals = [];
      interim = '';
    },

    // 복사본을 준다. 부르는 쪽이 배열을 건드려도 저장소가 오염되지 않는다.
    getState() {
      return { finals: [...finals], interim };
    },

    // 복사용 전문. 확정 문단만 넣는다.
    toText() {
      return finals.join('\n');
    },
  };
}

// --- 글자 크기 ---

export const FONT_STEPS = [20, 24, 28, 34, 40, 48]; // px, 오름차순
export const DEFAULT_FONT_SIZE = 28;
const FONT_SIZE_KEY = 'maldongmu.fontSize';

// 위로는 지금보다 큰 첫 단계, 아래로는 지금보다 작은 첫 단계.
// 그런 단계가 없으면 지금 값을 그대로 둔다.
export function nextFontSize(current, step) {
  const found = step > 0
    ? FONT_STEPS.find((size) => size > current)
    : [...FONT_STEPS].reverse().find((size) => size < current);
  return found ?? current;
}

// 저장값이 없거나 손상됐거나 단계 목록 밖이면 기본값을 준다.
// 저장소 접근 자체가 막힌 경우(사파리 비공개 모드)도 마찬가지다.
export function loadFontSize(storage) {
  try {
    const saved = Number(storage.getItem(FONT_SIZE_KEY));
    return FONT_STEPS.includes(saved) ? saved : DEFAULT_FONT_SIZE;
  } catch {
    return DEFAULT_FONT_SIZE;
  }
}

// 저장에 실패해도 삼킨다. 글자 크기를 기억하지 못하는 것이
// 자막이 멈추는 것보다 훨씬 가볍다.
export function saveFontSize(storage, px) {
  try {
    storage.setItem(FONT_SIZE_KEY, String(px));
  } catch {
    // 무시한다.
  }
}
