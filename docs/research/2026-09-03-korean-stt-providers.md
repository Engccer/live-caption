# 국내 실시간 스트리밍 STT 프로바이더 조사 (2026-09-03)

"실시간"은 마케팅 문구가 아니라 **문서에 WebSocket/gRPC 스트리밍 엔드포인트가 명시된 경우만**
인정했다. 확인 못 한 항목은 추측하지 않고 명시했다.

## 결론 한 줄

**실시간 스트리밍에서 화자 분리까지 지원한다고 문서로 확인된 국내 프로바이더는 없었다.**
실시간 스트리밍이 확실한 곳은 리턴제로·CLOVA Speech·다글로·KT 네 곳이고, 문서 완성도와
가격 투명성은 리턴제로가 가장 높다.

## 비교표

| 프로바이더 | 실시간 스트리밍 | 실시간 화자분리 | 가격(공개) | 무료 티어 | 문서 |
|---|---|---|---|---|---|
| **리턴제로(VITO/RTZR)** | **있음**(gRPC + WebSocket) | **없음**(화자분리는 파일 STT 전용) | 시간당 1,000원(0~1,000h) 누진 할인, 최소 10초 | 가입 시 600분 | [developers.rtzr.ai](https://developers.rtzr.ai/) |
| **네이버클라우드 CLOVA Speech** | **있음**(gRPC) | **없음**(스트리밍 Config에 필드 없음) | 약 0.5원/초(≈30원/분), 비공식 인용 | 월 20분 | [guide.ncloud-docs.com](https://guide.ncloud-docs.com/docs/clovaspeech-overview) |
| **다글로(액션파워)** | **있음**(gRPC `StreamingRecognize`) | 확인 못 함(문의 필요) | 공개 요금표 없음(선불 포인트) | 가입 시 약 10시간 | [developers.daglo.ai](https://developers.daglo.ai/guide/STT-Realtime.html) |
| **ETRI 공공 AI** | **없음**(파일 단위 REST) | 없음 | 무료 | 전체 무료 | [aiopen.etri.re.kr](https://aiopen.etri.re.kr/) |
| **카카오엔터프라이즈** | 공개 API **2022-07-01 종료** | 확인 못 함 | 비공개(제휴 문의) | 없음 | [종료 공지](https://devtalk.kakao.com/t/api/141770) |
| **KT 지니 Dictation** | **있음**(gRPC) | 확인 못 함 | 확인 못 함(승인제 추정) | 확인 못 함 | [apilink.kt.co.kr](https://apilink.kt.co.kr/) (접속 오류) |
| **셀바스AI** | 확인 못 함(개발자 포털에 TTS만 게시, STT는 B2B 추정) | 확인 못 함 | 확인 못 함 | 확인 못 함 | 사이트 SSL 만료 |
| **마음AI(구 마인즈랩)** | 확인 못 함(공개 개발자 문서 미발견) | 확인 못 함 | 확인 못 함 | 확인 못 함 | 미발견 |
| **솔트룩스** | 자체 STT 제품·문서 미발견 | - | - | - | 미발견 |
| **SK텔레콤** | 개발자용 공개 STT API 미발견(에이닷은 소비자 앱) | - | - | - | - |

## 상세

### 리턴제로 (VITO / RTZR) — 최유력 후보

- gRPC `grpc-openapi.vito.ai:443`, WebSocket `wss://openapi.vito.ai/v1/transcribe:streaming`.
  인증은 `https://openapi.vito.ai/v1/authenticate`.
- **화자분리는 실시간에 없다.** 스트리밍 `DecoderConfig`에 `SampleRate`, `Encoding`, `UseItn`,
  `UseDisfluencyFilter`, `UseProfanityFilter`, `Domain`만 있고 화자분리 필드가 전혀 없다.
  화자분리 문서는 경로가 `/docs/stt-file/diarization/`으로 **파일 전용**임이 URL로도 확인된다.
  (검색 요약이 "실시간 화자분리 지원"이라 시사했으나 1차 문서 대조 결과 미지원으로 정정.)
- **가격**: T1 0~1,000h 시간당 1,000원 → T2 500원 → T3 400원 → T4 300원. 스트리밍과 파일 STT
  동일 요율. 최소 집계 10초. 가입 시 600분 무료.
- **정확도**: 자사 벤치마크([Awesome-Korean-Speech-Recognition](https://github.com/rtzr/Awesome-Korean-Speech-Recognition))
  에서 CER 6.77%로 최저(Whisper 11.34%, Google STT v2 11.59%, ETRI 7.15%, CLOVA 7.96%).
  **자사 저장소라 이해상충이 있으므로 참고용으로만 볼 것.**
- 지연 공개 수치 없음.

### 네이버클라우드 CLOVA Speech

- gRPC `clovaspeech-gw.ncloud.com:50051`.
- 스트리밍 Config는 `transcription`, `keywordBoosting`, `forbidden`, `semanticEpd`,
  `translationEpd`뿐으로 화자분리 필드 없음.
- 가격은 초당 약 0.5원 수준으로 추정(비공식 인용, 공식 요금표는 콘솔 로그인 필요). 묵음도 과금.
- **공공기관용 별도 포털(gov-ncloud.com)이 있어 개인정보 국내 보관 요건에 유리.**

### 다글로 (액션파워)

- 양방향 gRPC `StreamingRecognize`. Bearer 토큰. LINEAR16 / 16kHz / 모노 고정.
  세션당 최대 6시간, 한국어·영어(혼합) 지원.
- 화자분리가 STT 부가기능 목록에는 있으나 실시간 적용 여부는 문서상 불명확 →
  api-support@daglo.ai 문의 필요.
- 개발자 API 요금표가 문서에 없다. `daglo.ai/pricing`은 소비자용 노트 앱 요금제로 보이며
  개발자 API와 동일한지 확인 못 함(혼동 주의).

### 후보에서 제외

- **카카오**: 공개 REST API가 2022-07-01 종료. 현재는 B2B 제휴 문의만 가능해 셀프서비스 불가.
- **ETRI**: 완전 무료지만 파일 단위 REST라 실시간 자막에 부적합.

### 재확인 필요

- **KT 지니 Dictation**: "long 유형은 EPD가 발생해도 세션을 종료하지 않고 PCM을 계속 수신"이라는
  문구로 스트리밍 존재는 확인([GitHub 가이드](https://github.com/gigagenie/cloud-aiapi)). 그러나
  API Link 포털 접속 오류로 엔드포인트·화자분리·가격 1차 대조 실패. apilink@kt.com 문의 권장.
- **셀바스AI**: `cloud.selvasai.com` 개발자 포털에 TTS만 있고 STT 없음. Selvy Speech 소개
  페이지는 SSL 인증서 만료로 접속 불가(회사 측 문제로 보임). 재확인 권장.
- **마음AI·솔트룩스·SKT**: 공개 개발자 문서를 찾지 못해 결론 보류.

## 자막 앱 관점 시사점

1. 국내 프로바이더를 쓰면 **개인정보 국내 보관**은 얻지만 **실시간 화자 분리는 못 얻는다.**
   화자 구분이 필요하면 국내 실시간 전사 + 별도 온라인 화자 분리 엔진(diart, Streaming
   Sortformer) 조합이 된다.
2. 리턴제로 시간당 1,000원은 Meta Muse($0.18/h ≈ 250원)보다 4배가량 비싸다. 다만 국내 결제·
   국내 리전·한국어 특화라는 축이 다르다.
3. 무료 티어(리턴제로 600분, 다글로 10시간)가 프로토타입에는 충분하다.
