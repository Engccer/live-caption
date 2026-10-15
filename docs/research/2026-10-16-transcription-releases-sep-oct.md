# 2026년 9~10월 전사 모델 출시 조사 (2026-10-16)

마이크로소프트 전사 모델 출시 소식을 계기로, 2026-09-01 이후 나온 전사·화자 분리 모델 중
이 프로젝트가 참고할 것을 모았다. 출처는 공식 문서·모델 카드를 우선했고, 2차 보도에만 있는
수치는 그렇다고 적었다. **아무것도 실측하지 않았다.** 이 프로젝트는 실측하지 않은 수치로
후보 순위를 바꾸지 않는다.

## 결론

- **마이크로소프트 MAI-Transcribe-2-Streaming**: 한국어를 지원하는 실시간 전사이고 브라우저에서
  직접 붙을 수 있는 인증 경로가 문서에 있다. 그러나 **실시간 화자 분리가 없다.** 회의용으로는
  Muse와 같은 자리(전사는 빠르지만 누가 말했는지는 모름)에 들어간다.
- **마이크로소프트 VibeVoice-ASR-Streaming**: 같은 회사의 다른 팀(Microsoft Research)이 낸
  **공개 가중치(MIT) 스트리밍 전사 + 화자 귀속** 모델이다. 모델 카드에 한국어가 있다.
  셀프호스팅 경로에서 WhisperLiveKit 조합과 비교할 새 후보다.
- **NVIDIA Nemotron-3-Diarization**: Streaming Sortformer의 후속 화자 분리 모델이다.
  WhisperLiveKit이 쓰는 Sortformer 계열을 교체할 후보지만, 한국어 학습·평가 기록이 없다.
- **1차 웹앱 경로는 바뀌지 않는다.** 서버 없이 브라우저 내장 API로 간다는 결정을 뒤집을
  근거가 이번 출시에는 없다(아래 각 항목의 "웹앱" 줄).

## 마이크로소프트 MAI-Transcribe-2 (배치)

| 항목 | 값 | 출처 |
|---|---|---|
| 출시 | 2026-09-03 | 2차 보도(DataNorth 등) |
| 한국어 | 지원(`ko`), 총 60개 언어 | Microsoft Learn |
| 화자 분리 | 있음(`diarization.enabled`). 화자 분리를 켜면 받을 수 있는 녹음 길이가 짧아진다 | Microsoft Learn |
| 그 밖의 기능 | 단어 단위 타임스탬프, 키워드 편향(`phraseList`), 군더더기 제거 스타일(`clean`) | Microsoft Learn |
| 가격 | 오디오 시간당 $0.10, 2026년 말까지 한시 가격 | 2차 보도. 이후 가격 미공개 |
| 화자 분리 오류율(DER) | 미공개 | 2차 보도 |

**이 프로젝트에서의 자리**: 실시간이 아니므로 자막에는 못 쓴다. 회의 뒤 정리본이나 eval 정답
정렬용 배치 전사 후보다. 단 CLAUDE.md 규칙대로 **상용 출력은 eval 정답이 될 수 없다.**

## 마이크로소프트 MAI-Transcribe-2-Streaming (실시간)

| 항목 | 값 | 출처 |
|---|---|---|
| 출시 | 2026-10-01, 공개 프리뷰(SLA 없음, 운영 비권장) | Microsoft Learn |
| 한국어 | 지원(`ko`), 60개 언어, 자동 언어 감지 | Microsoft Learn |
| **화자 분리** | **없음.** 이벤트에 화자 정보가 없고 문서에도 언급이 없다 | Microsoft Learn, 2차 보도의 비교표 |
| 지연(벤더 주장) | 첫 partial 약 100~120ms, 발화 종료 후 final 약 130ms | 2차 보도. 320ms라는 보도도 있어 엇갈림 |
| 정확도(벤더 주장) | AA-WER Streaming 2.5%, 1위 | 마이크로소프트 발표. 리더보드 등재는 미확인 |
| 가격 | 오디오 시간당 $0.54, 연말까지 도입가 | 2차 보도(TestingCatalog) |
| 서비스 리전 | 스웨덴 중부, 미국 중부, 미국 동부2, 동남아시아 | Microsoft Learn |
| 세션 상한 | 1시간 | Microsoft Learn |

### 스트리밍 프로토콜

| 항목 | 값 |
|---|---|
| 엔드포인트 | `wss://{리소스}.services.ai.azure.com/mai/v1/realtime?intent=transcription` |
| 형태 | OpenAI Realtime API와 비슷한 JSON 이벤트 |
| 인증 | Entra 토큰(`Authorization` 헤더), `api-key` 헤더, **또는 `api-key` 쿼리 문자열** |
| 오디오 | PCM16 mono 16k/24k, **base64로 감싼 JSON**(`input_audio_buffer.append`). 10~20ms 청크 권장 |
| 중간 결과 | `...intermediate`가 확정분 뒤의 임시 꼬리 전체를 매번 교체 |
| 확정 결과 | `...delta`(새로 확정된 조각, 공백 가공 없이 이어 붙임), commit 뒤 `...completed` |
| 발화 경계 | **서버 VAD 없음.** `turn_detection`은 `null`만 허용. 클라이언트가 쉼을 감지해 `commit`을 보내야 한다 |
| 설정 변경 | 첫 오디오 전송 뒤에는 바꿀 수 없다 |

**웹앱**: 쿼리 문자열 인증 덕분에 브라우저 WebSocket으로 직접 붙는 것 자체는 가능하다(Grok과
다른 점). 그러나 공개 웹앱에 키를 넣으면 키가 그대로 노출되므로, 실제로는 단기 토큰을 발급하는
서버가 필요하다. 서버를 두지 않는다는 1차 결정과 충돌하는 것은 Grok과 같다.

**회의용 판단**: 실시간 화자 분리가 없고 화자 전환 신호도 없다. Muse·Deepgram에서는 정체(who)는
못 믿어도 전환(when)은 쓸 수 있었는데, 이 모델은 그 신호조차 주지 않는다. 화자 정보가 필요하면
별도 화자 분리 모델을 옆에 붙여야 한다.

## 마이크로소프트 VibeVoice-ASR-Streaming (공개 가중치)

| 항목 | 값 | 출처 |
|---|---|---|
| 공개 | 2026-09-02 Hugging Face 업로드, 논문 arXiv 2609.02812 (09-02, v2 09-10) | HF API, arXiv |
| 만든 곳 | Microsoft Research (MAI 팀과 별개) | 모델 카드 |
| 라이선스 | MIT, 가중치·추론 코드 공개 | HF API, 논문 |
| 크기 | 1.5B, 7B (7B는 백본 기준 이름, 전체 약 9B라는 보도) | HF, 2차 보도 |
| 한국어 | 모델 카드 언어 10개에 `ko` 포함. **한국어 수치는 없다** | HF API |
| 화자 | 논문은 별도 화자 분리 단계 없이 "누가 무엇을 말했나"를 스트리밍으로 낸다고 함. 2차 보도는 기본 출력이 평문이라 함(엇갈림) | arXiv, 2차 보도 |
| 지연 | 측정 수치 없음. 고정 청크 + 짧은 미리보기 구조 | arXiv |

**이 프로젝트에서의 자리**: 셀프호스팅 경로의 새 후보다. 지금까지 그 경로의 기준은
WhisperLiveKit(Whisper 저지연 정책 + Streaming Sortformer)였는데, VibeVoice는 전사와 화자 귀속을
한 모델이 동시에 낸다. 재야 할 것: 한국어 CER, 화자 귀속 정확도(화자 수 계수 포함),
1.5B가 맥이나 아이폰급 기기에서 실시간으로 도는지.

## NVIDIA Nemotron-3-Diarization (공개 가중치, 화자 분리 전용)

| 항목 | 값 | 출처 |
|---|---|---|
| 공개 | 2026-09-23 | 모델 카드 |
| 라이선스 | OpenMDW 1.1, 상업 이용 가능 | 모델 카드 |
| 크기·화자 수 | 99.2M 파라미터, 최대 8명 | 모델 카드 |
| 지연 설정 | 1.04초(기본), 0.64초, 0.32초 | 모델 카드 |
| DER | DIHARD III 1.04초 설정에서 13.18(이전 Sortformer 4spk-v2.1은 19.60) | 모델 카드 |
| 한국어 | **학습·평가 언어 목록에 없다** | 모델 카드 |
| 실행 환경 | NVIDIA GPU, 리눅스 권장 | 모델 카드 |

**이 프로젝트에서의 자리**: 이전 Sortformer가 4명 상한이었던 데 비해 8명이라 회의에 더 맞는다.
화자 분리는 목소리 특성을 보므로 언어 의존이 전사보다 약하다고 흔히 보지만, 한국어 회의
녹음으로 확인한 사람은 아직 없다. WhisperLiveKit의 화자 분리 부품을 이것으로 바꿀 수 있는지가
셀프호스팅 경로의 확인 과제다.

## 그 밖에 참고할 소식

- **구글 AI Edge Foresight** (2026-10-06): 애플 실리콘 맥에서 인터넷 없이 회의를 받아쓰고
  Gemma 4로 질의응답하는 실험 앱. 온디바이스 회의 전사의 사례이지만 영어 외 언어 성능은
  밝히지 않았다. 전사에 어떤 모델을 쓰는지도 공개되지 않았다.
- **AssemblyAI Universal-3.6 Pro Realtime** (2026-09-29로 보도): 상용 실시간 API.
  AssemblyAI 자체 블로그의 언급만 확인했고 한국어 지원 여부는 확인하지 않았다.
- **애플 iOS 받아쓰기 개선** (2026-09 신제품 발표): "정확도와 활용 범위가 크게 개선"이라는
  발표만 있다. iOS 단계 후보인 `SpeechAnalyzer`의 한국어 실측 과제는 그대로다.

## 확인 범위

- 2026-09-01~10-15 이메일 브리핑(`Briefings/email`)에서 전사 관련 항목을 추렸다.
  09-04(MAI-Transcribe-2), 10-02·10-05·10-08(Streaming), 10-12(Foresight)가 출발점이다.
- MAI 두 모델은 Microsoft Learn 문서(2026-10-07·10-14 갱신본)로 대조했다. 마이크로소프트
  모델 카드 PDF는 텍스트를 추출하지 못해 읽지 못했다.
- 리더보드 순위는 Artificial Analysis 화면에서 직접 확인하지 못했다. AA-WER Streaming 평가
  데이터(AA-AgentTalk·VoxPopuli·Earnings22)는 한국어 성능을 말해 주지 않는다.

## 출처

- [MAI-Transcribe-2, Microsoft Learn](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe)
- [MAI-Transcribe-2-Streaming 개요, Microsoft Learn](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe-2-streaming)
- [MAI-Transcribe-2-Streaming Realtime API, Microsoft Learn](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe-2-streaming-realtime)
- [MAI-Transcribe-2 모델 페이지](https://microsoft.ai/models/mai-transcribe-2/)
- [TestingCatalog: Streaming 출시 보도](https://www.testingcatalog.com/microsoft-launches-mai-transcribe-2-streaming/)
- [DataNorth: MAI-Transcribe-2 출시 보도](https://datanorth.ai/news/microsoft-released-mai-transcribe-2)
- [VibeVoice-ASR-Streaming 기술 보고서, arXiv 2609.02812](https://arxiv.org/abs/2609.02812)
- [microsoft/VibeVoice-ASR-Streaming-7B, Hugging Face](https://huggingface.co/microsoft/VibeVoice-ASR-Streaming-7B)
- [nvidia/Nemotron-3-Diarization, Hugging Face](https://huggingface.co/nvidia/Nemotron-3-Diarization)
- [Google AI Edge Foresight 보도, Notebookcheck](https://www.notebookcheck.net/Google-AI-Edge-Foresight-Offline-AI-for-meeting-notes-on-Mac.1418337.0.html)
- [AssemblyAI 실시간 STT 비교 글](https://www.assemblyai.com/blog/best-api-models-for-real-time-speech-recognition-and-transcription)
