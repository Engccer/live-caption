# 실시간 캡션 오픈소스 조사 (2026-09-03)

라이선스·스타 수·최근 커밋일은 GitHub API 직접 조회 실측치.

## 이 조사가 뒤집은 것

**스파이크에서 "실시간 화자 분리는 스트리밍 클러스터링의 구조적 한계"라고 결론 낸 것은 과잉
일반화였다.** 상용 API(Muse·Deepgram)가 화자 수를 과소 계수한 실측은 유효하지만, 그것은
**배치 전제로 만든 화자 분리를 스트리밍에 얹은 구현**의 문제이지 온라인 화자 분리가
원리적으로 불가능하다는 뜻이 아니다. 증분 클러스터링·화자 캐시로 처음부터 온라인으로 설계된
알고리즘이 오픈소스에 있고, 지연 실측치까지 공개돼 있다.

## A. 온디바이스/셀프호스팅 실시간 STT 엔진

| 프로젝트 | 라이선스 | 스타 | 최근 활동 | 아키텍처 | 한국어 |
|---|---|---|---|---|---|
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | MIT | 53,387 | 2026-08-31 | 완전 온디바이스(C/C++) | 되지만 청크 기반이라 문장 잘림 잦음 |
| [WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit) | Apache-2.0 | 10,989 | 2026-09-01 | 셀프호스팅 FastAPI+WS 서버 + 웹UI | 지원(Whisper/Qwen3-ASR 백엔드) |
| [WhisperLive](https://github.com/collabora/WhisperLive) | MIT | 4,246 | 2026-08-31 | 서버-클라이언트, faster_whisper/TensorRT | 지원 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | 25,201 | 2025-11-19(정체) | CTranslate2 엔진 | 지원, 한국어 파인튜닝본 다수 |
| [ufal/whisper_streaming](https://github.com/ufal/whisper_streaming) | MIT | 3,672 | 2025-11-12 | LocalAgreement 정책 원조 구현 | 지원 |
| [Vosk](https://github.com/alphacep/vosk-api) | Apache-2.0 | 15,102 | 2026-08-09 | Kaldi 기반, 진짜 프레임 단위 스트리밍 | 모델은 있으나 품질 리포트 빈약 |
| [Moonshine](https://github.com/usefulsensors/moonshine) | 확인 필요 | 10,996 | 2026-08-31 | 초저지연 엣지 ASR | 한국어 모델 미확인(영어 중심) |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Apache-2.0 | 14,573 | 2026-09-02 | C++ 코어 + 12개 언어 바인딩 | 한국어 streaming zipformer(~60MB, 160ms) 있으나 [이슈 #2886](https://github.com/k2-fsa/sherpa-onnx/issues/2886) 빈 결과 버그 |
| [NVIDIA Nemotron 3.5 ASR Streaming 0.6B](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) | OpenMDW-1.1(상업 허용) | - | 2026-06 | Cache-aware FastConformer, GPU 지향 | 40개 로케일에 한국어 포함 |
| [Kyutai STT](https://github.com/kyutai-labs/delayed-streams-modeling) | Apache-2.0 | 3,021 | 2026-01-26 | 진짜 스트리밍(0.5~2.5초) | **한국어 없음** |

## B. 완성형 실시간 캡션 앱

| 프로젝트 | 라이선스 | 스타 | 최근 활동 | 특징 |
|---|---|---|---|---|
| [abb128/LiveCaptions](https://github.com/abb128/LiveCaptions) | GPL-3.0 | 1,784 | 2025-02-27 | aprilasr, 완전 로컬, **영어 전용** |
| [Buzz](https://github.com/chidiwilliams/buzz) | MIT | 21,276 | 2026-08-28 | 데스크톱 받아쓰기·번역 도구. 연속 실시간 자막 UX는 아님 |
| Web Captioner(현 Maestra) | 상용 전환 | - | - | 브라우저 Web Speech API 의존 → 오디오가 Google로 나감 |

## C. 웹 기반 구현체

**WhisperLiveKit**이 사실상 이 카테고리의 정답에 가깝다. FastAPI+WebSocket 서버와 웹 프론트엔드를
제공하고, 실시간 자막용 최신 연구가 이미 조립돼 있다:

- **AlignAtt 정책**(SOTA 2025) 기반 초저지연 전사
- **LocalAgreement 정책**(SOTA 2023) 겸용
- **NLLB 기반 200개 언어 동시통역**
- **Streaming Sortformer**(NVIDIA, 2025 SOTA) 실시간 화자 분리 내장
- OpenAI/Deepgram 호환 API 제공

브라우저 Web Speech API 기반 구현은 셋업이 0에 가깝지만 오디오가 클라우드(주로 Google)로 나가
프라이버시·오프라인 요구와 상충한다.

## D. iOS/Swift

| 프로젝트 | 라이선스 | 스타 | 최근 활동 | 비고 |
|---|---|---|---|---|
| [WhisperKit](https://github.com/argmaxinc/WhisperKit) | MIT | 6,353 | 2026-08-13 | CoreML 온디바이스, Neural Engine 최적화, 실시간 스트리밍·단어 타임스탬프·VAD 내장. 한국어는 채택 모델 크기에 좌우 |
| Apple `SFSpeechRecognizer` (iOS 26+ `SpeechAnalyzer`) | OS 내장 | - | - | 완전 온디바이스, 한국어 공식 지원, 엔지니어링 비용 0. 캡션 UX는 직접 구현 |

## E. 스트리밍 화자 분리 (핵심 관심사)

| 프로젝트 | 라이선스 | 스타 | 진짜 스트리밍인가 |
|---|---|---|---|
| [diart](https://github.com/juanmc2005/diart) | MIT | 2,024 | **예.** pyannote 임베딩 위 500ms 롤링 버퍼 증분 클러스터링. RealTimeInference API, 웹소켓 서빙 |
| [pyannote-audio](https://github.com/pyannote/pyannote-audio) | MIT | 10,500 | 아니오. 기본 파이프라인은 오프라인(전체 오디오 필요). 상용 "Live-1"만 스트리밍 |
| [NVIDIA Streaming Sortformer](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1) | Apache-2.0 | - | **예.** Arrival-Order Speaker Cache. **지연 0.08~1.12초 설정 가능**([논문](https://arxiv.org/pdf/2507.18446)). 기본 4화자, [Ultra-Sortformer](https://github.com/mago-research/Ultra-Sortformer)가 4명 초과 지원 |
| sherpa-onnx 화자분리 | Apache-2.0 | - | **아니오(함정).** "streaming" 툴킷에 있지만 화자분리 자체는 오프라인 후처리 |

`diart`와 Streaming Sortformer 둘 다 캐시/롤링버퍼 기반 진짜 온라인 알고리즘이다. 상용 API가
배치 화자분리를 스트리밍에 억지로 끼워 넣은 것과 설계 자체가 다르다. WhisperLiveKit이 이미
Streaming Sortformer를 통합해 검증했다는 점도 신뢰도를 높인다.

## 온디바이스 한국어 실시간 전사 실용성

- **모바일**: sherpa-onnx 한국어 스트리밍 zipformer가 이론상 최적(60MB/160ms)이나 버그 리포트가
  있어 채택 전 실측 검증 필수. WhisperKit은 되지만 모델 크기(turbo=809M)에 따라 기기 성능에 좌우.
  **Apple `SFSpeechRecognizer`/`SpeechAnalyzer`가 가장 검증된 "공짜 온디바이스 한국어 실시간"**
  (오픈소스 엔진은 아니고 OS API).
- **서버/셀프호스팅(더 현실적)**: WhisperLiveKit + 한국어 파인튜닝 Whisper(large-v3-turbo 계열)
  조합이 완성도 최고. NVIDIA Nemotron 3.5 ASR Streaming도 유력하나 GPU 필요.
- Vosk 한국어는 실측 품질 리포트가 부족하고 Kaldi 기반이라 구조적으로도 불리.

## 추천

1. **웹앱**: WhisperLiveKit 셀프호스팅 + 한국어 파인튜닝 Whisper + 내장 Streaming Sortformer.
   Apache-2.0이라 라이선스가 깨끗하고 버퍼링·정책 연구가 이미 조립돼 있다.
2. **iOS**: 1차는 Apple `SFSpeechRecognizer`로 최소 비용 프로토타입 → 부족하면 WhisperKit으로 교체.
3. **화자 분리**: `diart`(가벼움, 웹소켓 서빙 용이)로 프로토타입 → 부족하면 Streaming Sortformer.
4. **주의**: sherpa-onnx 한국어 모델은 스펙이 매력적이지만 미해결 버그가 있으니 반드시 실측할 것.
