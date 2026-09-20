# SpaceXAI Grok Voice Transcribe 2.0 조사 (2026-09-21)

2026-09-18 출시 소식을 받고 조사했다. 공식 문서와 발표에 적힌 것, 제3자가 확인한 것,
아직 아무도 재지 않은 것을 구분해 적는다. 이 프로젝트는 실측하지 않은 수치를 근거로
순위를 바꾸지 않는다.

## 결론 한 줄

**문서상으로는 이 프로젝트가 찾던 조건(실시간 스트리밍 + 실시간 화자 분리 + 한국어)을
한 API가 처음으로 모두 적어 놓았다. 그러나 한국어 성능 근거는 0이고, 화자 분리 정확도는
Muse·Deepgram이 똑같이 "지원"이라 적어 놓고 실측에서 무너졌던 바로 그 항목이다.
그리고 브라우저에서 직접 붙일 수 없어 1차 웹앱 경로는 바뀌지 않는다.**

## 무엇이 나왔나

| 항목 | 값 | 출처 |
|---|---|---|
| 모델 | `grok-voice-transcribe-2.0` (API 기본값) | docs.x.ai |
| 출시일 | 2026-09-18 | x.ai/news |
| 이전 버전 | `grok-voice-transcribe-1.0`, 몇 주 내 중단 예고 | x.ai/news |
| STT API 자체 | 2026-04-17 발표 (2.0은 모델 교체) | x.ai/news |
| 가격 | 배치 시간당 $0.10, **스트리밍 시간당 $0.20** | x.ai/news |
| 한국어 | **지원**(`ko`), 총 27개 언어 | docs.x.ai |
| 공개 가중치 | 없음, API 전용 | MarkTechPost |

## 스트리밍 프로토콜

| 항목 | 값 |
|---|---|
| 엔드포인트 | `wss://api.x.ai/v1/stt` |
| 설정 방법 | URL 쿼리 파라미터. 별도 설정 메시지 없음 |
| 인증 | `Authorization: Bearer $XAI_API_KEY` **헤더** |
| 오디오 | 컨테이너 없는 바이너리 프레임. base64 아님 |
| 인코딩 | `pcm`(기본)·`mulaw`·`alaw`·`opus` |
| 샘플레이트 | 8000·16000·22050·24000·44100·48000 (기본 16000) |
| 권장 청크 | 100ms (16kHz PCM16 기준 3,200바이트) |
| 중간 결과 | `interim_results=true` → 약 500ms 간격 `transcript.partial` |
| 종료 신호 | 클라이언트 `finalize` / `audio.done` |
| 첫 이벤트 | `transcript.created` 수신 전에는 오디오를 보내지 않는다 |

**확정 단계가 3단이다.** Muse·Deepgram의 2단(partial/final)보다 하나 많다.

| 단계 | `is_final` | `speech_final` | 뜻 |
|---|:-:|:-:|---|
| Interim | false | false | 텍스트가 더 바뀔 수 있다 |
| Chunk final | true | false | 약 3초 분량이 확정됐다 |
| Utterance final | true | true | 화자가 멈췄고 발화가 끝났다 |

턴 분절 제어 파라미터가 노출돼 있다: `endpointing`(침묵 ms, 0~5000, 기본 400),
`vad_threshold`(기본 0.08), `smart_turn`(종료 감지 신뢰도 임계값),
`smart_turn_timeout`(강제 확정 최대 침묵 ms). 응답에는 `end_of_turn_confidence`가 실린다.

기타: `keyterm` 최대 100개(각 50자)로 고유명사 바이어싱, `filler_words`,
`multichannel`(최대 8채널), 배치 파일 최대 500MB, 단어마다 `confidence`.

## 화자 분리 (이 프로젝트의 핵심 관심사)

- 파라미터 `diarize=true`. 켜면 **단어마다 `speaker` 정수 필드**가 붙는다.
- 스트리밍 WebSocket에서도 같은 파라미터를 지원한다고 적혀 있다.
- 발표 문구: "Detect speakers in both pre-recorded and real-time streaming with
  word-level speaker IDs using Diarization", 2.0 발표에서는 "추가 비용 없음"과
  "실시간 화자 턴 감지".

⚠ **이 항목은 문서만으로 판정하지 않는다.** Meta Muse와 Deepgram도 문서에 같은 말을 적어
놓았고, 실녹음 실측에서 스트리밍 3명 < 배치 4명 < 상용 배치 7명으로 과소 계수됐다
(`docs/spike-2026-09-03-realtime-stt.md`). 단어 단위 라벨이라는 점은 Muse의 세그먼트 단위
`speaker` 이벤트보다 세밀하지만, 세밀함이 정확함은 아니다.

## 성능 주장과 그 근거

벤더 주장:

- 공개 벤치마크에서 "스트리밍 모델 32개 중 정확도 1위".
- 내부 평가에서 단문 음성인식 단어 오류율 20.6% → 6.8%, "1.0보다 2배 정확, 같은 가격".

확인한 것:

- 인용된 공개 벤치마크는 Artificial Analysis의 **AA-WER Streaming**이다. 구성은 약 8시간
  오디오로 AA-AgentTalk 50%, VoxPopuli 25%, Earnings22 25%.
- **이 벤치마크에 한국어는 없다.** AgentTalk·Earnings22는 영어이고 VoxPopuli는 유럽의회
  녹음이다. 즉 **1위 주장은 한국어 성능에 대해 아무것도 말해 주지 않는다.**
- 내부 WER 20.6% → 6.8%도 언어가 명시돼 있지 않다. MarkTechPost는 "These internal results
  are vendor-reported and not independently reproduced"라고 명시했다.
- AA-WER Streaming 소개 글의 상위 모델은 Cartesia Ink-2(semantic endpoints) WER 3.59% /
  0.21초, ElevenLabs Scribe v2 Realtime 3.64% / 0.14초, Cartesia Ink-2(external endpoints)
  3.66% / 0.09초였다. **그 글에는 Grok Voice Transcribe가 없다.** 리더보드 제공자 목록에는
  SpaceXAI가 들어 있으나 수치는 인터랙티브 차트에만 있어 정적 조회로는 확인하지 못했다.
- AA가 재는 지연은 **"발화 종료 감지 이후" 첫 partial / 첫 final까지의 시간**이다.
  이 프로젝트가 스파이크에서 잰 "오디오 전송 대비 partial 도착 지연"(Muse 중앙값 151ms)과
  **정의가 다르므로 직접 비교할 수 없다.**
- 공식 문서·발표 어디에도 **지연 수치가 없다.**

## 데이터 취급

- 기본값: API 요청·응답을 암호화해 **30일 보존**(오남용 감사 목적), 이후 자동 삭제.
- 학습: 명시적 허가 없이 API 입출력으로 학습하지 않는다고 밝힌다.
- Zero Data Retention: 팀 단위로 적용되며 켜면 디스크에 저장하지 않는다. 대신 저장 의존
  기능(Files/Collections, Batch, Deferred 등)이 꺼진다.
- ZDR을 쓰지 않으면 비식별·집계 데이터를 다른 목적에 쓸 수 있다고 적혀 있다.

회의·상담 음성을 다루는 앱에서 30일 보존은 그냥 넘길 조건이 아니다.

## 이 프로젝트에 대한 시사점

1. **1차 웹앱 경로는 바뀌지 않는다.** 인증이 `Authorization` 헤더인데 브라우저의 WebSocket
   API는 커스텀 헤더를 붙일 수 없다. 키를 프런트엔드에 두는 것도 공개 저장소에서는 불가다.
   즉 **중계 서버가 필요하고**, 서버를 두지 않는다는 확정 전제와 정면으로 부딪힌다.
   (참고로 스피치투스피치 쪽에는 `POST /v1/realtime/client_secrets`로 최대 1시간짜리 임시
   토큰을 발급하는 경로가 있으나, 그 발급 자체가 서버를 요구하고 STT WebSocket에 쓸 수
   있다는 서술은 찾지 못했다.)
2. **무료라는 전제와도 부딪힌다.** 스트리밍 시간당 $0.20이면 2시간 회의에 약 $0.40(560원
   안팎)이다. 리턴제로 시간당 1,000원보다는 싸고 Muse($0.18/h)와는 비슷하다. 비용 자체는
   작지만 "무료·오픈소스"라는 전제(`PROGRESS.md`)와는 다른 축이다.
3. **가치가 있는 자리는 iOS 단계와 셀프호스팅 경로다.** iOS 앱은 어차피 네트워크 호출을
   앱이 직접 하므로 헤더 인증이 문제가 되지 않는다. 애플 온디바이스 API와 견줄 후보가
   하나 늘었다.
4. **판정 전에 실측이 필요하고, 잴 수 있는 하네스가 이미 있다.** `spike/`가 Muse·Deepgram을
   같은 조건으로 측정한 구조이므로 엔드포인트 하나를 추가하는 일이다. 재야 할 것은 셋이다:
   한국어 실녹음 WER, 오디오 전송 대비 partial 지연(Muse 151ms와 같은 정의로),
   실시간 화자 수 계수.
5. **정답 자료 기준은 그대로다.** 상용 API 출력을 정답으로 쓰지 않는다. 화자 경계를 사람이
   그은 자료가 없으면 화자 분리는 잴 수 없다. 이 제약이 이번에도 그대로 걸린다.

## 출처

- [Introducing Grok Voice Transcribe 2.0](https://x.ai/news/grok-voice-transcribe-2)
- [Grok Speech to Text and Text to Speech APIs](https://x.ai/news/grok-stt-and-tts-apis)
- [Speech to Text | SpaceXAI Docs](https://docs.x.ai/developers/model-capabilities/audio/speech-to-text)
- [Voice | Inference API REST 레퍼런스](https://docs.x.ai/developers/rest-api-reference/inference/voice)
- [FAQ API Security | SpaceXAI Docs](https://docs.x.ai/developers/faq/security)
- [MarkTechPost 보도 (2026-09-18)](https://www.marktechpost.com/2026/09/18/spacexai-releases-grok-voice-transcribe-2-0/)
- [AA-WER Streaming 벤치마크 소개](https://artificialanalysis.ai/articles/new-streaming-speech-to-text-benchmark-aa-wer-streaming)
- [Artificial Analysis 스트리밍 STT 리더보드](https://artificialanalysis.ai/speech-to-text/streaming)
