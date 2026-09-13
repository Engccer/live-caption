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
