# eval 도구

음성 eval 자료를 다루는 스크립트다. 파싱·검증·채점은 deterministic하며 같은 입력에 같은 결과를 낸다.
네트워크 수집은 배포 상태에 따라 달라지므로 원본과 영수증을 보존한다.

| 스크립트 | 하는 일 |
|---|---|
| `align.py` | 시각 없는 속기록에 시각을 붙인다. STT 전사를 다리 삼아 단어 시퀀스를 정렬하고 앵커 사이를 보간한다 |
| `verify_align.py` | 정렬 결과를 검증한다. 각 줄의 시각에서 전사를 꺼내 내용이 맞는지 3-gram으로 재고 역행·끝단을 확인한다 |
| `score.py` | 정답과 전사의 CER/WER을 정규화 단계별로 낸다 |
| `collect_public.py` | 한국어 공개 원본 5종과 제작자 정답을 다운로드하고 SHA-256 영수증을 남긴다 |
| `prepare_public.py` | 원본의 음성·정답을 대응하고 분할별 JSONL, 샘플 수·해시·검증 인벤토리를 만든다 |
| `collect_kss.py` | KSS v4 원본 ZIP과 단일 성우 보조 정답을 확보한다 |
| `collect_ami.py` | AMI scenario-only dev/test의 음성과 사람이 검토한 발화 구간을 확보한다 |
| `score_cases.py` | 공개 정답 JSONL과 결과 JSONL을 ID로 대응해 삽입 포함 micro CER/WER을 낸다 |
| `public_data.py`, `range_download.py` | 저장소 경계, 덮어쓰기 방지, 안전한 압축 해제, 검증된 조각의 다운로드 재개 |
| `run_eval.py` | 실시간 STT 2단계 평가 실행기. 기본은 dry-run 예상 비용표, 실행은 예산 확인 후 |
| `cost.py` | 엔진 단가 표, 예상 비용, 실행 중 예산 차단, 지출 장부 |
| `stream_plan.py` | 단계별 스트리밍 세션 구성(공개 클립 묶음, 회의 녹음 분할), PCM 디코드 |
| `engines.py` | 엔진 어댑터 7종(muse·deepgram·grok·mai·rtzr·gemini·mai-vercel). 실시간 페이싱 전송과 이벤트 기록 |
| `stream_score.py` | 세션 결과의 CER(표준/삭제+치환)과 partial·final 지연 집계 |

## 자료는 저장소 밖에 있다

음성과 속기록은 실제 회의 기록이라 **이 저장소에 두지 않는다**(CLAUDE.md 「테스트 음원
취급 규칙」). 위치는 환경변수로 받는다.

```bash
export LIVE_CAPTION_EVAL_DATA=~/Mac-Projects/live-caption-data/eval   # 기본값
```

세트마다 `$LIVE_CAPTION_EVAL_DATA/<세트>/{audio,ref,baseline}/` 구조다.
저장소의 `eval/<세트>/MANIFEST.md`에는 집계·측정 조건·판정만 기록한다.
회의 자료의 내부 원본 경로는 저장소 밖 `<자료>/SOURCES.md`에 둔다.

## 쓰는 순서

```bash
D=${LIVE_CAPTION_EVAL_DATA:-~/Mac-Projects/live-caption-data/eval}

# 1. 전사 (시각 포함)
python ${SPEECH_TOOLKIT:-~/Mac-Projects/speech-toolkit}/STT/deepgram_stt.py <오디오.wav> --lang ko --timestamps

# 2. 정렬
python eval/tools/align.py \
  --steno $D/<세트>/ref/stenograph.txt \
  --ts <오디오>_deepgram_ts.txt \
  --out $D/<세트>/ref/aligned.tsv

# 3. 검증 (반드시 한다. 정렬은 틀려도 조용히 틀린다)
python eval/tools/verify_align.py \
  --aligned $D/<세트>/ref/aligned.tsv \
  --ts <오디오>_deepgram_ts.txt \
  --duration <초>

# 4. 채점
python eval/tools/score.py \
  --ref $D/<세트>/ref/stenograph.txt \
  --hyp $D/<세트>/baseline/<엔진>.txt
```

## 함정

- **전사에 keyterm을 주면 정렬이 좋아진다.** 참석자 이름과 조직 용어를 `keyterms.txt`에
  넣고 오디오와 같은 폴더에 두면 `deepgram_stt.py`가 자동으로 읽는다. 인명이 맞게
  전사돼야 앵커가 늘어난다.
- **`score.py`의 CER을 그대로 믿지 말 것.** 속기사가 잡담을 안 적었으면 그만큼이
  삽입 오류로 잡혀 점수를 망친다. 삭제와 치환만 세는 지표를 쓴다.
  근거와 채택 지표는 `eval/chonghoe-2026/MANIFEST.md`에 있다.
- **간투사는 단독 토큰일 때만 지운다.** `그`·`저`·`네`는 지시사·대답으로도 쓰여
  부분 문자열로 지우면 내용이 깨진다.

## 공개 자료 수집과 준비

Python 3.12 이상, `curl`, 표본 디코드 확인용 `ffmpeg`를 쓴다. 외부 Python 패키지는 없다.
`--connections` 병렬 재개는 `fcntl`을 제공하는 macOS/Linux 환경용이다.
웹앱 실행 의존성과 무관한 eval 도구다. 데이터셋별 채택 범위·라이선스·실측은
`eval/public-korean/MANIFEST.md`, `eval/kss-public/MANIFEST.md`, `eval/ami-public/MANIFEST.md`를 본다.

```bash
# 5종 한국어 자료의 원본 및 정답. 원본과 해제본 공간을 모두 확보해야 한다.
python3 eval/tools/collect_public.py --extract
python3 eval/tools/prepare_public.py

# 대형 원본 전송이 느릴 때. 검증된 조각을 재사용한다.
python3 eval/tools/collect_public.py --datasets seoul zeroth --extract --connections 8 --workers 2

python3 eval/tools/collect_kss.py --extract
python3 eval/tools/collect_ami.py

# 도구 자체의 합성 fixture 테스트. 실제 발화를 사용하지 않는다.
python3 -m unittest discover -s eval/tools -p 'test_*.py'
```

공개 자료도 `$LIVE_CAPTION_EVAL_DATA/public/<자료>/`에 둔다. 기본 경로는
`~/Mac-Projects/live-caption-data/eval/public/`이며, 저장소 안을 지정하거나 심볼릭 링크로 우회하면 거부한다.
원본은 `raw/`, 추출본은 `extracted/`, 한국어 5종의 정답은 `ref/<split>.jsonl`이다.
KSS 정답은 `refs.jsonl`, AMI 발화 구간은 `ref/<회의>.segments.json`과 RTTM이다.
음성 경로는 **해당 자료 폴더 기준 상대 경로**다.

다운로드 영수증은 URL·UTC 수집 시각·바이트·SHA-256을 보존한다. FLEURS 음성은 배포자
SHA-256과도 대조한다. 나머지의 로컬 SHA-256은 이후 파일 변조 검사용이며 배포자의 서명을
검증했다는 뜻이 아니다. FLEURS와 Deeply 보충 JSON은 제작자 저장소 revision도 고정한다.
기존 원본·정답이 같으면 재사용하고 다르면 덮어쓰지 않는다. 입력을 바꿔 재준비할 때는
별도 `--root`를 사용한다. 완료 전 끊긴 파일은 성공으로 집계하지 않는다.
단일 연결은 매번 새 임시 파일에서 받으며 검증 없이 예전 조각을 이어붙이지 않는다.
Range 다운로드만 원본 식별자와 조각별 해시를 확인해 재개한다. Zeroth는 전체 원본을
보존하되 음성·전사와 `AUDIO_INFO`만 해제하며 언어모델·사전은 해제하지 않는다.
해제본은 파일별 무결성 manifest로 재검증한다. 완료 표시만 있고 실제 파일이 없으면 실패한다.

## 공개 자료 채점 계약

정답 행에는 `id`, `dataset`, `split`, `cluster`, `text`, `audio`, `duration_seconds`,
`eligible_metrics`, `evaluation_ready`가 있다. 인식 결과는 같은 `id`와 `text`를 가진 JSONL로
저장한다. 결과가 없었던 발화도 `text`를 빈 문자열로 남긴다. ID 누락·추가·중복은 실패다.

```bash
D=${LIVE_CAPTION_EVAL_DATA:-~/Mac-Projects/live-caption-data/eval}
python3 eval/tools/score_cases.py \
  --ref "$D/public/fleurs-ko/ref/test.jsonl" \
  --hyp "$D/public/fleurs-ko/baseline/engine-test.jsonl"
```

- **표준 CER/WER**: `(치환 + 삭제 + 삽입) / 정답 길이`. 행별 거리를 더한 뒤 전체 정답
  길이로 나눈다. 문장별 오류율의 단순 평균이 아니다.
- **정규화**: NFC, 구두점 제거, 공백 통일. CER은 공백 제외. 간투사·숫자는 보존한다.
  총회 속기록의 삽입 제외 및 간투사 삭제 규칙을 공개 자료에 적용하지 않는다.
- **분할**: `test`는 후보 최종 비교, `dev`는 튜닝, `train`은 진단/개발 보관용이다.
  학습 분할은 `--split train`을 명시해야 채점된다. `--split`을 지정했다면 가설도 그 ID만
  포함해야 한다. `all`은 공식 split이 없는 보조 자료이며 공식 test라고 부르지 않는다.
- **준비 상태**: `evaluation_ready: false`는 기본 채점 거부. `--allow-provisional`로 낸
  결과는 임시 점수다. 음원 확보와 평가 적합성 확정은 다르다.
- **독립 단위**: `cluster`는 같은 문장/세션/면담을 묶는다. 파일 수를 독립 표본 수로
  해석하거나 자료 종류를 섞은 한 점수로 엔진을 고르지 않는다.
- **화자와 지연**: 한국어 낭독 파일을 이어붙여 화자 전환 정답을 만들지 않는다.
  데이터셋의 시각만으로 실시간 지연을 측정할 수 없으며 별도 스트리밍 하네스가 필요하다.

이 도구는 STT API를 호출하지 않는다. 인식 결과가 없는 상태에서는 엔진 순위나 정확도를
보고하지 않는다. 각 후보의 호출 설정·비용·오류를 기록하고 지연은 다른 날 최소 2회 측정한다.

## 비용 안전장치와 2단계 평가

실시간 STT 후보를 같은 음성·같은 조건으로 비교한다. **유료 API를 부르므로 기본 동작은
dry-run(네트워크 0)이다.** 실제 실행은 예산과 확인 플래그가 모두 있어야 시작한다.

| 단계 | 세트 | 엔진당 전송 |
|---|---|---|
| `taste` | 총회 앞부분(600초 안 마지막 속기록 줄 시작점, 579초에서 자름) + 장날 전체 | 0.283h |
| `core` | FLEURS 한국어 test 382개 + Zeroth test 457개 + 총회 전체 + 장날 전체 | 3.963h (묶음 무음 822초 포함) |

학습 분할·Seoul·KSS·AMI는 넣지 않는다.

### 쓰는 순서

```bash
# 1. 예상 비용표 (네트워크 0)
python3 eval/tools/run_eval.py --stage taste
python3 eval/tools/run_eval.py --stage core --engines muse,grok

# 2. 실제 실행. 키가 있는 엔진만 돌고, 키가 없는 엔진은 빠진 환경변수를 알리고 건너뛴다
python3 eval/tools/run_eval.py --stage taste --engines muse,deepgram,grok,rtzr,gemini \
  --budget-krw 1000 --confirm --parallel          # 누적 한도는 기본 20,000원(--total-cap-krw)

# 3. 누적 지출
python3 eval/tools/run_eval.py --ledger
```

엔진 이름은 `muse`(별칭 `meta-muse`), `deepgram`, `grok`(`xai`), `mai`(`mai-streaming`),
`rtzr`, `gemini`(`gemini-live`), `mai-vercel`(`vercel-mai`·`mai-gateway`)다. 지정하지 않으면 `mai`를 뺀 6종이다.
`mai`와 `mai-vercel`은 같은 모델(MAI-Transcribe-2-Streaming)을 Azure 직접과 Vercel AI Gateway 경유로 부른다.
기본은 `mai-vercel`이고 `mai`는 명시할 때만 돈다. 둘을 함께 지정하면 비용이 두 번 든다는 경고를 낸다. `--parallel`은 엔진들을 동시에, `--jobs N`은 엔진마다 세션 N개를 동시에 연다.
전송은 실시간 속도라 `core`는 `--jobs 1`이면 엔진당 약 4시간 걸린다. 동시 세션 한도는
Muse 8개, 리턴제로 무료 계정 5개다. 동시 세션이 지연 측정에 영향을 주는지는 확인하지 않았다.

### 필요한 환경변수

| 엔진 | 환경변수 |
|---|---|
| muse | `META_API_KEY` |
| deepgram | `DEEPGRAM_API_KEY` |
| grok | `XAI_API_KEY` |
| mai | `AZURE_MAI_ENDPOINT`(`https://<리소스>.services.ai.azure.com`), `AZURE_MAI_API_KEY`, `AZURE_MAI_DEPLOYMENT_NAME` |
| rtzr | `RTZR_CLIENT_ID`, `RTZR_CLIENT_SECRET` |
| gemini | `GEMINI_API_KEY` |
| mai-vercel | `AI_GATEWAY_API_KEY`(Vercel AI Gateway API 키) |

mai는 현재 구독에서 배포 불가(2026-10-16)라 같은 모델을 Vercel AI Gateway로 부르는 `mai-vercel`을 더했다. `mai` 어댑터는 그대로 둔다.

`websockets` 패키지가 필요하다(eval 도구 중 이것만 외부 패키지다). FLEURS(float WAV)와
Zeroth(FLAC)는 `ffmpeg`로 16kHz mono PCM16으로 변환해 보낸다.

### dry-run 출력 예

```
단계 taste: 세션 2개, 엔진당 전송 1,019.9초 (0.283h), 그중 묶음 무음 0.0초

세트                 세션    클립      전송(초)         채점
chonghoe-2026       1     1      579.0      삭제+치환
jangnal-2026        1     1      440.9      정답 없음

엔진           세션      과금(초)    단가($/h)     예상($)     예상(원)
muse          2    1,019.9      0.180     0.051        71
deepgram      2    1,019.9      0.462     0.131       183
grok          2    1,019.9      0.200     0.057        79
rtzr          2    1,019.9      0.714     0.202       283
gemini        3    1,019.9      0.850     0.241       337
mai-vercel    2    1,019.9      0.540     0.153       214
합계                                        0.835     1,169
별도 분할: gemini (세션 상한 540초, 세션 3개, 최장 440.9초)

누적 지출 0원 / 한도 20,000원
```

`core` 기본 6엔진 합계는 약 $11.68(16,348원)이다(1,400원/달러). 기본 누적 한도 20,000원 안에 들지만
여유가 크지 않다. `mai`까지 더하면 19,344원으로 한도에 거의 닿는다.

### 비용 계산과 차단

- **단가는 `cost.py`의 `PRICES` 한 곳에만 있다.** 각 값의 출처를 주석으로 달았다. 문서·보도
  값이며 실청구서로 확인한 값이 아니다. 연결당 최소 과금(리턴제로 세션당 10초)은 세션마다 올려 반영한다.
- **gemini는 토큰 과금이라 시간당 $0.85가 추정이다.** 입력 오디오 $3.50/1M 토큰(초당 32토큰,
  분당 약 $0.0067)과 출력 텍스트 $21/1M 토큰(한국어 말 1분 약 350토큰, 분당 약 $0.0074)을 더해
  보수적으로 올렸다. 서버가 `usageMetadata`를 보내면 장부의 `tokens`에 세션별 마지막 값의 합을 남긴다.
- **한도는 둘이다.** `--budget-krw`는 **이번 실행 한 번**에 쓸 수 있는 금액이고,
  `--total-cap-krw`(기본 20,000원)는 **장부에 쌓인 모든 실행의 누적 지출** 상한이다.
  시작 전 화면에 `누적 지출 X원 / 한도 Y원`을 낸다(dry-run도 같다).
- **실행 전**: 키가 있는 엔진들의 예상 비용 합이 이번 예산이나 남은 누적 한도(한도 - 장부 누적)를
  넘으면 시작하지 않는다. 두 금액과 환율(`--krw-per-usd`)은 유한한 양수만 받는다.
- **실행 중**: 차단 기준은 `min(이번 예산, 남은 누적 한도)`다. 청크를 보내기 전에 누적 전송
  음성으로 비용을 더해 보고, 기준을 넘게 되는 청크는 보내지 않고 그 세션을 종료 신호로 닫는다.
  남은 세션은 열지 않는다. 여러 엔진이 기준 하나를 공유한다. 이 추적은 **보낸 음성 길이 기준
  추정**이다. 연결 시간으로 과금하는 엔진이라면 세션마다 종료 대기(최대 30초)만큼 더 청구될 수
  있으므로, **첫 실호출 때 각 업체 대시보드의 청구 내역과 장부를 대조해 확인한다.**
- **지출 장부**: `$LIVE_CAPTION_EVAL_DATA/../runs/ledger.jsonl`에 엔진이 끝날 때마다 한 줄씩
  덧붙인다(실행 이름·단계·종료 상태·전송 초·과금 초·추정 지출·계획 금액·차단 기준·중단/오류
  세션 수). 종료 상태는 `completed`·`budget`(예산 차단)·`exception`·`interrupted`(Ctrl-C·취소)다.
  예외나 Ctrl-C로 끝나도 그때까지 보낸 만큼을 기록하고, 함께 돌던 엔진은 멈춘 뒤 기록한다.
  엔진마다 한 번만 기록한다. dry-run은 기록하지 않는다. 장부를 지우면 누적 한도가 무력해진다.

### 묶음과 분할

- **공개 클립 묶음**: FLEURS·Zeroth 클립을 ID 순으로 1초 무음을 끼워 한 스트림으로 보낸다.
  묶음 하나는 무음 포함 600초 이하다(FLEURS 9묶음, Zeroth 8묶음). 무음도 전송이므로 비용에
  들어간다. 정답은 묶음 안 클립 정답을 이어 붙인 것이고 채점은 공개 자료 계약과 같은
  표준 CER(구두점 정규화, 삽입 포함, 묶음별 거리 합 / 정답 문자 합)이다.
- **회의 녹음 분할**: 세션 상한(Muse·MAI 1시간)을 넘지 않도록 3000초를 넘는 녹음은 속기록 줄
  경계에서 나눈다. 총회 전체는 1963초 지점에서 둘로 나뉜다. 상한이 그보다 짧은 엔진이 없으면
  모든 엔진이 같은 분할을 받는다.
- **세션 상한이 짧은 엔진(gemini 540초)**: 기본은 그 엔진만 자기 상한으로 다시 나누고 다른
  엔진의 분할은 그대로 둔다(실행 결과의 `별도 분할` 줄). core에서 gemini는 29세션(공개 묶음 19,
  총회 9, 장날 1), 나머지는 20세션이다. 공개 자료는 클립 사이 무음에서만 끊기므로 분할 차이가
  CER에 영향을 주지 않는다. **총회는 다르다.** 자르는 자리가 많을수록 줄 꼬리 삭제가 늘어
  gemini만 불리해진다. 그래서 gemini를 다른 엔진과 총회 CER로 견줄 때는 `--common-split`을 쓴다.
  고른 엔진들의 상한 중 최솟값으로 한 번 나눠 모든 엔진이 같은 단위를 받는다. 대신 다른 엔진의
  분할도 바뀌므로 그 결과는 같은 분할 방식의 실행끼리만 비교한다. 장부의 `split` 필드
  (`per-engine`·`common`)가 어느 쪽이었는지 남긴다. 줄 경계로 상한 안에 들지 않으면 조각 수를
  늘려 다시 나누고, 장날은 줄 정보가 없어 같은 길이로 나눈다.
  줄 경계의 시각은 정렬 추정이라 경계를 넘는 줄 꼬리가 삭제로 잡혀 절대 CER이 약간 높게
  나올 수 있지만, 모든 엔진에 똑같이 적용되므로 엔진 간 비교는 공정하다.
- **길이 확인**: 세션마다 디코드한 PCM 길이를 계획과 대조하고 10ms 넘게 다르면 그 세션을
  보내지 않고 사유를 출력한다(오류 세션으로 집계).
- **총회 채점**: MANIFEST 채택 지표 그대로 구두점·간투사·숫자 표기를 정규화하고
  (삭제 + 치환) / 정답 문자수로 잰다. 삽입 비용 0, 삭제·치환 비용 1인 DP로 최솟값을 구한다.
  녹음 범위 밖 속기록 줄은 정답에서 뺀다.
- **중단된 세션**: 예산 차단·오류 세션은 CER 합산에서 뺀다. 대신 엔진마다 채점 포함 비율
  (포함된 정답 글자 / 계획 전체 정답 글자)을 함께 낸다. 이 비율이 100%가 아니면 세트 CER은
  일부 구간만의 값이다.
- **장날**: 축어 정답이 없어 CER을 내지 않는다(MANIFEST 판정). 지연과 전송만 잰다.
- **지연**: 수신 시각 - 엔진이 알린 오디오 위치(`spike/score.py`와 같은 정의). 오디오 위치를
  주지 않는 이벤트는 지연 계산에서 빠진다(아래 불확실성 참조).

### 산출물

`$LIVE_CAPTION_EVAL_DATA/../runs/<날짜>-<단계>/<엔진>/<세션>.json`에 전사 텍스트와 이벤트가,
`summary.json`에 집계만 들어간다. 저장소 안에는 아무것도 쓰지 않는다. 화면에는 엔진·세트별
CER, partial 지연 중앙/최대, final 지연 중앙, 전송 초, 채점 포함 비율, 추정 지출, 종료 상태만 나온다.

### 실호출 전 남은 불확실성

**muse·deepgram은 `spike/probe.py`에서 실호출로 확인한 순서를 옮겼다. grok·mai·rtzr·gemini는 문서만
보고, mai-vercel은 AI SDK 소스만 보고 짰다. 다음 세션의 첫 실호출이 검증 게이트다.** 로컬 가짜 서버 테스트는 메시지 순서만
보장한다. 첫 실행은 `taste`에 엔진 하나씩, 작은 예산으로 시작하고 세션 JSON의 이벤트를 열어
아래를 확인한다.

- **grok**: `transcript.created`의 본문, `finalize` 표기(`finalize`/`Finalize`가 문서 안에서 엇갈림.
  이 어댑터는 `audio.done`만 쓴다), `transcript.partial`의 `start`·`duration`이 interim에도 오는지,
  `transcript.done.text`가 확정 조각 합과 같은지(다르면 `check` 이벤트를 남기고 done을 채택),
  세션 상한(문서에 없음). `diarize=true`를 켰다.
- **mai**: 이벤트에 오디오 위치 필드가 문서에 없어 **지연을 못 잴 수 있다**(`audio_end_ms`가
  오면 쓴다). 서버 VAD가 없어 클라이언트가 commit한다: 3초 이후 300ms 조용하면, 아니면 10초에
  강제. 강제 commit이 단어 중간을 자를 수 있다. `language: "ko"` 허용 여부와 과금 기준(오디오
  시간인지 연결 시간인지), 가격($0.54/h는 2차 보도)도 미확인이다.
- **rtzr**: 헤더 형식은 Go/Java 예제의 `Bearer`를 따랐다(Python 예제는 소문자 `bearer`).
  partial에는 `start_at`만 있고 길이가 0이라 **partial 지연을 못 잴 수 있다**(final만 잰다).
  `domain=MEETING`을 골랐다. 세션 최대 길이는 문서에 없다. 60초 무음이면 서버가 끊을 수 있다.
- **gemini**: 문서(ai.google.dev live-transcribe·api/live, 2026-10-16)와 무과금 모델 조회
  (`models/gemini-3.5-transcribe-live`, 지원 메서드 `bidiGenerateContent`)만 확인했다. 인증은 문서대로
  URL 쿼리 `key`이며 URL은 어디에도 기록하지 않고 오류 문구의 키는 `***`로 지운다. 확인할 것:
  종료 이벤트가 문서에 없어 `audioStreamEnd` 뒤 8초 동안 메시지가 없으면 끝난 것으로 본다(마지막
  확정 전사를 놓칠 수 있다). `inputTranscription`이 겹치지 않는 조각인지(지금은 공백으로 이어 붙인다).
  `endOffset`이 세션 시작 기준인지(지연 계산의 전제). `usageMetadata`가 누적 값인지. 실제 연결 상한과
  `goAway` 시점(이벤트로 기록). 설정 키는 문서의 WebSocket 표기(camelCase `languageCodes`)를 따랐다.
- **mai-vercel**: 웹 문서에 WebSocket 주소가 없어 AI SDK 소스(`@ai-sdk/gateway` 4.0.115,
  `@ai-sdk/provider-utils` 5.0.61)에서 프로토콜을 옮겼다. 주소 `wss://ai-gateway.vercel.sh/v4/ai/transcription-model?ai-model-id=…`,
  인증은 서브프로토콜 `ai-gateway-auth.<키>`(키는 URL에 들어가지 않는다)와 `Authorization` 헤더,
  첫 프레임 `transcription-stream.start`, 오디오 raw PCM 바이너리, 끝 `transcription-stream.audio-done`,
  서버 `finish` 파트 뒤 1000 종료다. 서버 키로 바로 연결하고 `getToken`(단기 토큰 발급)은 쓰지 않는다.
  확인할 것: ① **게이트웨이에 commit 프레임이 없다.** AI SDK의 Azure MAI 어댑터는 오디오 끝에서 한 번만
  commit하므로 게이트웨이도 그렇다면 확정 전사가 세션 끝에야 오고(final 지연 = 세션 길이), 3~10초마다
  commit하는 `mai`와 지연을 견줄 수 없다. 끝난 뒤 전사 대기는 120초로 늘렸다. ② 서버 키를 서브프로토콜로
  받는지(소스상 게이트웨이가 바꿔 읽는다고 적혀 있다). ③ `providerOptions.azure.language: "ko"`가 스트리밍에서
  전달되는지(문서의 `azure` 키 예시는 배치 모델 것). ④ 16kHz 허용(Azure 어댑터는 16000·24000 허용,
  Vercel 발표 예시가 16000). ⑤ partial·final에 오디오 위치(`startSecond` 등)가 오는지(없으면 지연을 못 잰다).
  `transcript-delta`에는 오디오 위치 필드가 없어 지연 집계에서 빠지고, final 지연은 `transcript-final`의 `endSecond`로만 잰다.
  ⑥ 게이트웨이 세션 상한(소스에 없어 Azure MAI 1시간을 따른다)과 과금 기준(오디오 시간인지 연결 시간인지),
  단가 $0.54/h는 모델 페이지 값이고 청구서로 확인하지 않았다. `finish` 텍스트가 비면 모은 delta·final로
  대체하고 `check` 이벤트를, 모두 비면 `empty` 이벤트를 남긴다. `error` 파트를 받으면 송신을 멈추고 바로 끝낸다.
- **muse·deepgram**: 남아 있는 스파이크 결과는 24kHz 합성 픽스처다. 16kHz(`PCM_16KHZ`, `sample_rate=16000`)
  전송은 코드가 허용하지만 기록된 실호출 결과로는 확인하지 못했다. Deepgram이 연결 시간으로 과금하는지도 미확인이다.
