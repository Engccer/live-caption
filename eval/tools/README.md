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

## 자료는 저장소 밖에 있다

음성과 속기록은 실제 회의 기록이라 **이 저장소에 두지 않는다**(CLAUDE.md 「테스트 음원
취급 규칙」). 위치는 환경변수로 받는다.

```bash
export LIVE_CAPTION_EVAL_DATA=~/live-caption-eval   # 기본값
```

세트마다 `$LIVE_CAPTION_EVAL_DATA/<세트>/{audio,ref,baseline}/` 구조다.
저장소의 `eval/<세트>/MANIFEST.md`에는 집계·측정 조건·판정만 기록한다.
회의 자료의 내부 원본 경로는 저장소 밖 `<자료>/SOURCES.md`에 둔다.

## 쓰는 순서

```bash
D=${LIVE_CAPTION_EVAL_DATA:-~/live-caption-eval}

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
`~/live-caption-eval/public/`이며, 저장소 안을 지정하거나 심볼릭 링크로 우회하면 거부한다.
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
D=${LIVE_CAPTION_EVAL_DATA:-~/live-caption-eval}
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
