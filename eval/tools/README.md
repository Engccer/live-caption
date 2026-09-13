# eval 도구

실녹음 eval 자료를 다루는 스크립트다. 전부 deterministic하며 같은 입력에 같은 결과를 낸다.

| 스크립트 | 하는 일 |
|---|---|
| `align.py` | 시각 없는 속기록에 시각을 붙인다. STT 전사를 다리 삼아 단어 시퀀스를 정렬하고 앵커 사이를 보간한다 |
| `verify_align.py` | 정렬 결과를 검증한다. 각 줄의 시각에서 전사를 꺼내 내용이 맞는지 3-gram으로 재고 역행·끝단을 확인한다 |
| `score.py` | 정답과 전사의 CER/WER을 정규화 단계별로 낸다 |

## 자료는 저장소 밖에 있다

음성과 속기록은 실제 회의 기록이라 **이 저장소에 두지 않는다**(CLAUDE.md 「테스트 음원
취급 규칙」). 위치는 환경변수로 받는다.

```bash
export LIVE_CAPTION_EVAL_DATA=~/live-caption-eval   # 기본값
```

세트마다 `$LIVE_CAPTION_EVAL_DATA/<세트>/{audio,ref,baseline}/` 구조다.
저장소의 `eval/<세트>/MANIFEST.md`가 그 자료의 원본 경로·실측·판정을 기록한다.

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
