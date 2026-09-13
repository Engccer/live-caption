# 공개 한국어 STT eval 자료

## 목적과 저장 위치

상용 STT 선택에 쓸 재현 가능한 한국어 기준선과 조건별 보조 자료다.
원음·전사·화자별 정보는 `$LIVE_CAPTION_EVAL_DATA/public/`에만 둔다.
기본값은 `~/Mac-Projects/live-caption-data/eval/public/`이며 공개 저장소에는 자료 본문을 싣지 않는다.
수집일은 2026-09-14다. 수집 명령과 JSONL 계약은 [도구 사용법](../tools/README.md)이 정본이다.

**한국어 6종 43,415개 음성, 124.13시간을 실제 확보했다.** 영어 AMI를 포함하면
7종 43,455개 음성 파일, 146.56시간이다. 이 합계에는 학습 자료와 평가 보류 자료도 포함된다.
바로 비교할 공식 한국어 test는 FLEURS와 Zeroth의 **839개, 2.53시간**이다.

## 실제 확보와 준비

| 자료 | 실제 음성/정답 | 실제 길이 | 역할 | 준비 상태 |
|---|---:|---:|---|---|
| FLEURS 한국어 | 2,915 / 2,915 | 10.04시간 | 공식 test 382개, dev 226개, train 2,307개 | 분할별 정답 JSONL 완료 |
| Pansori TEDxKR | 2,989 / 2,987 | 정답 대응 2.68시간 | 강연 보조 자료, 공식 test 분할 없음 | 미대응 음성 2개 제외 |
| Deeply 공개 부분집합 | 1,697 / 1,697 | 2.93시간 | 잔향 조건 3종, 반복 대본 199묶음 | 제작자 보충 JSON과 전량 대응 |
| KSS v4 | 12,854 / 12,854 | 12.86시간 | 성우 1명 낭독 보조 자료 | 평가 보류 표시로 정답 준비, [상세](../kss-public/MANIFEST.md) |
| Seoul Corpus | 240 / 240 | 42.75시간 | 40명 면담 자발화, 철자·발음·음소 TextGrid | 정답 JSONL 완료, 평가 보류 |
| Zeroth Korean | 22,720 / 22,720 | 52.87시간 | 공식 test 457개, train 22,263개 | 분할별 정답 JSONL 완료 |

영어 화자 분리 보조 자료인 AMI는 40개 22.43시간을 확보했고 그중 39개 21.76시간이
평가 적격이다. 음성과 정답 길이가 맞지 않는 1개는 제외했다. [별도 기록](../ami-public/MANIFEST.md)으로 관리한다.
서로 다른 언어·자료·학습 분할을 합친 점수로 한국어 엔진을 고르지 않는다.

## 정답 출처와 사용 조건

| 자료 | 공식 출처 | 전사 및 경계의 성격 | 배포 조건 |
|---|---|---|---|
| FLEURS | [Google 공식 데이터](https://huggingface.co/datasets/google/fleurs), [제작 논문](https://arxiv.org/abs/2205.12446) | 사람이 번역한 FLORES 문장을 원어민이 읽고 검증. 자연 대화는 아님 | CC BY 4.0 |
| Zeroth | [OpenSLR 40](https://www.openslr.org/40/), [제작자](https://github.com/goodatlas/zeroth) | crowdsource 낭독과 전사. 세부 전사 검수 절차는 미확인 | CC BY 4.0 |
| Seoul | [OpenSLR 113](https://www.openslr.org/113/), [원논문](https://doi.org/10.13064/KSSS.2015.7.2.103) | 한글 전사는 사람 작성, 초기 자동 음소 경계는 사람이 교정 | CC BY-NC 2.0 |
| Pansori | [OpenSLR 58](https://www.openslr.org/58/) | 사람이 작성한 TEDx 자막 및 수동 정렬. 최종 품질 선별에는 Google STT 사용 | CC BY-NC-ND 4.0 |
| Deeply | [OpenSLR 97](https://www.openslr.org/97/), [제작자 저장소](https://github.com/deeplyinc/Korean-Read-Speech-Corpus) | 사람이 읽은 대본. 공개본은 전체 연구의 일부 조건만 포함 | CC BY-NC-ND 4.0 |
| KSS | [제작자 Kaggle v4](https://www.kaggle.com/datasets/bryanpark/korean-single-speaker-speech-dataset) | 전문 성우의 실제 음성과 대본. TTS 학습용이며 합성 음성이 아님 | CC BY-NC-SA 4.0 |

NC 자료는 비상업 범위의 로컬 연구 자료로 보관한다. 원본과 변환된 음성·전사 자료를
앱에 넣거나 다시 배포하지 않는다. 원본 배포 조건과 코드 저장소의 MIT 라이선스는 별개다.
공식 페이지/제작자 metadata를 `raw/`에 보존했다.

## 평가에 적용할 판정

- **주 비교**: 공식 한국어 test 분할을 별도 채점한다. FLEURS dev는 226개 2,779.86초,
  test는 382개 4,804.92초이며 train 2,307개 28,558.98초는 최종 점수에서 제외한다.
  Zeroth test는 457개 4,287.25초, train은 22,263개 186,046.91초다.
  FLEURS 분할 간 문장 ID·동일 음성 중복은 0개이며 Zeroth train 105명과 test 10명도 겹치지 않는다.
- **보조 비교**: Pansori 강연, Deeply 잔향, KSS 단일 성우는 각각 보고한다. 공개 학습·낭독
  자료에 모델이 노출됐을 가능성은 확인되지 않았으며 실사용 회의 품질을 대신하지 않는다.
- **Pansori**: 사람이 원전사를 작성했으므로 기계 전사를 정답으로 삼는 순환은 아니다.
  다만 Google STT를 통한 선별 편향이 있어 이를 중립적인 단독 최종 기준으로 삼지 않는다.
- **Seoul**: `utt.ortho.` tier와 인간 최종 교정 시각을 보존한다. 인터뷰 대상자 중심
  전사가 면담자 발화도 전부 담는지 확인 전에는 전체 녹음 CER·DER 정답으로 확정하지 않는다.
  `evaluation_ready: false`를 유지한다. `utt.prono.` 및 음소 tier 원본도 보존한다.
- **화자 분리**: 한국어 낭독 클립을 이어붙인 인공 전환을 실대화 정답으로 쓰지 않는다.
  Seoul의 음소 경계와 AMI의 발화 경계도 정밀도와 작성 방식이 다르다.
- **정규화**: 공개 자료에는 삽입을 포함한 표준 CER/WER을 적용한다. 총회 속기록의
  삽입 제외 정책과 간투사 제거를 복제하지 않는다.
- **지연**: 데이터셋 timestamp만으로 실시간 지연을 계산하지 않는다. 동일 음원·설정으로
  스트리밍 하네스를 돌리고 다른 날 최소 2회 재측정한다. 이번 수집에서는 STT API를 호출하지 않았다.

## 무결성과 품질 확인

원본별 `.receipt.json`에는 URL·바이트·수집 시각·SHA-256이 있다. FLEURS 음성은
배포자의 LFS SHA-256과 일치한다. revision은
`70bb2e84b976b7e960aa89f1c648e09c59f894dd`다.
Deeply 보충 정답은 제작자 revision `1c9cdb8ca1ba79bf982c97b16fb40657420c9cba`로 고정했다.

정규화한 음성마다 헤더 샘플 수·양수 길이·해시를 확인하고, 각 분할의 첫/중간/마지막 파일을
`ffmpeg -xerror`로 디코드한다. 이 표본 검증을 음성 전체 디코딩이나 사람의 전량 청취로
표현하지 않는다. 원본 해시와 reference 개수·시각 검증도 실제 발화가 대본과 완전히 같음을
입증하는 검사는 아니다.

- FLEURS TSV는 7열이다. 문장 안 인용부호를 TSV quoting으로 처리하면 34행의 구조가
  달라지므로 탭만으로 분리한다. float WAV를 지원하며 음성 샘플 수와 metadata를 전량 대조했다.
- Pansori는 음성 2개에 대응 전사가 없다. 원본은 보존하되 정답을 추정하지 않는다.
  제외 목록·음성 해시는 외부 `pairing-audit.json`에 있다.
- Deeply tar에는 문서가 예고한 JSON이 없고 `script.csv`만 있다. 파일명 숫자로 대본을
  추정하지 않고 제작자의 `Korean_Read_Speech_Corpus_sample.json`을 받아 1,697개 모두 대응했다.
- KSS의 소개 수량·mono 가정과 실물 차이는 별도 MANIFEST에 있다.
- Seoul 원음은 22,050Hz mono다. 240개 파일의 철자 발화 구간을 모두 파싱하고
  시각 순서·음원 범위를 검사했다. 153,905.50초를 확보했으며 40개 면담을 독립 묶음으로 둔다.
- Zeroth 원본 10,339,720,618바이트를 보존하고 음성·전사 22,720쌍과 `AUDIO_INFO`만 해제했다.
  사전·언어모델 파일은 해제하지 않는다. 115명의 음성이며 test와 train 화자는 겹치지 않는다.

정답을 같은 정답과 비교하는 채점 경로 점검은 FLEURS dev/test, Pansori, Deeply,
Zeroth test에서 통과했다. 이는 도구 점검이며 엔진 정확도 측정값이 아니다.
수집·추출·파싱·채점·AMI 정답 처리의 합성 회귀 테스트 66개와 독립 코드 리뷰를 통과했다.

## 추가 확보 후보와 접근 상태

아래는 **확보한 자료가 아니다**. 수집 실패·미공개·신청 필요를 0개 데이터셋으로 해석하지 않는다.

| 후보 | 공개 설명과 활용 | 후속 경로 |
|---|---|---|
| [AI Hub 회의 음성 132](https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=132) | 한국어 토론/토크 3,000시간, 전사 검증 설명 | 내국인 계정 신청·승인 후 eval용 분할 확보, 경계 제작 절차 확인 |
| [KsponSpeech 123](https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=123) | 2인 자유대화 1,000시간, eval-clean/other 각각 3,000발화 | AI Hub 승인 후 별도 eval archive 우선. clean/other는 언어모델 perplexity 분류이며 잡음 분류가 아님 |
| [주요 영역별 회의 464](https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=464) | 의회·팟캐스트·방송 등 7,000시간 | 신청형. 2026년 라벨 수정본과 인간 경계 제작 근거 확인 |
| [성인 감정 자유대화 71631](https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71631) | 2인 개별 채널·화자별 전사, 본문 성인 3,000시간 | 신청형. 상단 총규모와 본문 성인 규모가 달라 동일 값으로 확정하지 않음 |
| [구음장애 음성인식 608](https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=608) | 청각장애 범주 포함. 단어·문장·문단·준자유·자유발화 | 신청형. 자유발화 비중은 작으며 장애별 정답 검수와 자연대화 적합성을 별도 확인 |
| [구음장애인 명령어 71434](https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71434) | 청각장애 발화 포함, 13주제 명령어 | 온라인 안심존 연구 신청. 일반 내려받기 데이터와 구분 |
| [Common Voice 한국어 25.0](https://mozilladatacollective.com/datasets/cmn2ale8p018bo107nbvos0f7) | 검증 음성 2.51시간, train/dev/test 제공 | Mozilla Data Collective 다운로드 절차 확인 필요. 전체 수집량 10.3시간을 검증 정답량으로 쓰지 않음 |
| [ClovaCall](https://github.com/clovaai/ClovaCall) | 한국어 전화 예약, test 1,084발화 | 학술기관 연구자 신청. 데이터 이용약관과 코드 라이선스 구별 |
| [KMSAV](https://github.com/etri/kmsav) | 한국어 다인 자연발화 약 83시간, 사람 검증 전사 | 제작자 HOWTO의 YouTube 재구성 경로. 단일 오디오 묶음은 없고 비겹침 선택 편향이 있음 |
| [K-MIND](https://github.com/AIRC-KETI/K-MIND) | 논문 초록은 한국어 대화 115시간30분 설명 | 현재 저장소는 제목만 있는 README, release·음원·데이터 라이선스 미확인 |
| [AliMeeting](https://www.openslr.org/119/) | 중국어 2~4인 회의, 공개 Eval/Test | 직접 공개, 한국어 STT와 분리하는 추가 화자분리 후보 |
| [VoxConverse](https://www.robots.ox.ac.uk/~vgg/data/voxconverse/) | 다화자 RTTM, 반자동 경계의 인간 검수 | 공식 사이트가 현재 음원 미제공 명시. 오래된 다운로드 링크를 확보 가능 근거로 쓰지 않음 |
| [DIHARD III](https://dihardchallenge.github.io/dihard3/faq.html) | 다양한 음향 조건의 화자분리 benchmark | 옛 무료 challenge 배포 종료. LDC 신청·약관·가격 확인 필요 |
| [Korean Telephone Conversations](https://catalog.ldc.upenn.edu/LDC2003S07) | 한국어 통화 100건, 일부 구간 전사 | LDC 신청·가격 확인형. CALLHOME Korean으로 잘못 표기하지 않음 |

AI Hub는 회의 132와 KsponSpeech 123을 먼저 신청하고, 청각장애 발화는 608의 실제
장애 범주·전사 품질을 확인한 뒤 평가 설계에 추가한다. 인증·신청서 제출·약관 동의는
아직 수행하지 않았다. 현재 승인받은 AI Hub 자료는 없다.
구음장애와 청각장애를 같은 범주라고 가정하지 않는다.

### AI Hub 신청 준비

**연구 목적 초안**: 청각장애 교사가 회의와 연수의 발화를 실시간 자막으로 읽을 수 있도록
한국어 문자 통역 도구를 개발한다. 동일한 사람 정답과 음성을 사용해 음성 인식 후보의
문자 오류율, 단어 오류율, 발화 누락, 화자 전환 및 실시간 지연을 비교한다. 학습용 자료와
최종 평가 자료를 구분하고, 실제 회의의 자연스러운 말 바뀜과 장애 발화에서의 성능 한계를
평가한다. 연구 결과는 발화를 복원할 수 없는 집계와 재현 가능한 평가 절차로 정리한다.

신청 시 확인할 항목은 세 가지다.

1. 132·123은 평가용 음성/라벨 분할을 우선 요청한다. 608은 장애 범주별 구성과
   자유발화·준자유발화의 평가용 분량을 먼저 확인한다.
2. 사람이 작성·검수한 전사인지, 화자 경계를 사람이 검토했는지, 생략된 발화나
   마스킹 표기가 있는지 구축 가이드와 표본으로 확인한다.
3. 후보 상용 API로 음성을 전송할 수 있는지는 해당 데이터의 이용 조건으로 확인한다.
   승인받기 전에는 외부 전송 가능 여부를 확정하지 않는다. 데이터 재배포 허용과 코드 공개는 별개다.

회의 132의 샘플 링크도 비로그인 상태에서는 로그인으로 연결된다. 샘플은 별도 가공·마스킹될
수 있다는 공식 안내가 있으므로 확보하더라도 완전한 축어 정답으로 곧바로 채택하지 않는다.
