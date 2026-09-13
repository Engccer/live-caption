# AMI 공개 회의 평가 자료

## 자료와 사용 범위

- 확인일: 2026-09-14.
- 영어 4인 회의의 **scenario-only 공식 dev/test 분할**, Mix-Headset 음원을 확보했다.
- 음원 40건, 22.428시간, 2,583,682,160바이트. 수동 전사 ZIP v1.6.2는 22,887,865바이트다.
- 평가 사용 가능: **39건, 21.755시간**. 음원과 전사 길이가 맞지 않는 1건은 평가 대상에서 분리했다.
- 용도: 영어 다자간 자연 발화의 전사와 화자 전환 보조 검증. 한국어 성능이나 실제 원거리 마이크 성능을 대표하지 않는다.

| 분할 | 확보 음원 | 평가 사용 가능 | 사용 가능 시간 | 발화 세그먼트 | 실단어 수 |
|---|---:|---:|---:|---:|---:|
| dev | 20 | 20 | 10.657시간 | 9,512 | 99,160 |
| test | 20 | 19 | 11.098시간 | 8,644 | 97,185 |

시간은 WAV의 프레임 수로 계산했다. 세그먼트와 단어 수는 사용 가능 자료만 집계했다.
4명의 헤드셋을 섞은 mono 음원이므로 한 개의 원거리 마이크를 사용하는 조건과 구별한다.
역할을 부여한 시나리오 회의로, 조직의 실제 업무 회의와 구별한다.

## 출처와 정답의 성격

- [공식 다운로드](https://groups.inf.ed.ac.uk/ami/download/): 음원과 manual annotations v1.6.2, **CC BY 4.0**. 로그인·신청·약관 동의 화면 없이 공식 HTTPS 파일을 받았다.
- [공식 분할](https://groups.inf.ed.ac.uk/ami/corpus/datasets.shtml): scenario-only의 dev/test 각 20개 회의. Full-corpus-ASR 분할과 혼용하지 않는다.
- [전사 절차](https://groups.inf.ed.ac.uk/ami/corpus/transcription.shtml): 자동 에너지 사전 분절을 사람이 조정하고, 다음 사람이 전체 구간을 다시 검토했다. 화자별 전사와 채널 구분을 제공한다.
- **단어·음소 시각은 강제정렬로 자동 생성됐다.** 이 수집기는 그 값을 발화 정답 경계로 사용하지 않고 `segments/*.xml`의 `transcriber_start`·`transcriber_end`를 보존한다.
- 수집기가 만든 RTTM은 사람이 검토한 **전사 세그먼트**의 화자 경계다. 정밀한 무음 제거·중첩 기준·UEM을 갖춘 공식 DER 평가 프로토콜과 동일하다고 간주하지 않는다. 공식 DER 수치와 비교하려면 별도 평가 구간·collar·중첩 처리 규칙이 필요하다.

## 확인된 제한

- **TS3007c**: 공식 Mix-Headset은 2,420초인데 전사 세그먼트가 2,430.2초까지 이어진다. 음원 밖 경계 5건이 있어 해당 회의의 `eligible_for_evaluation`을 `false`로 기록하고 RTTM을 생성하지 않았다. 원본 음원·전사와 경계는 보존했다. 따라서 사용할 test는 공식 20건 중 19건이다.
- **ES2011c**: 비언어 발성 1개의 원본 경계가 역전돼 있다. JSON에 `boundary_valid: false`로 보존하며 speech RTTM에는 넣지 않는다.
- **TS3003d**: 단어 XML의 실단어 2개와 문장부호 1개가 어떤 전사 세그먼트에서도 참조되지 않고 자동 시각도 0초다. 원본 ZIP에 보존했으며 사람 경계를 추정해 추가하지 않았다.
- 순수 웃음·기침 등 비언어 이벤트는 speech RTTM에서 제외한다. 청취 불능 발화인 `gap`은 유지한다. JSON에는 비언어 이벤트 종류별 개수를 남긴다.

## 저장과 재현

음원, 전사, 개별 화자 정보는 저장소 밖 `$LIVE_CAPTION_EVAL_DATA/public/ami/`에만 둔다.
기본 자료 루트는 `~/Mac-Projects/live-caption-data/eval`이다.

```bash
python3 eval/tools/collect_ami.py --workers 4
python3 -m unittest discover -s eval/tools -p test_collect_ami.py -v
```

- `raw/`: 공식 WAV 40개와 전사 ZIP, 각 다운로드의 출처 URL·시간·SHA-256 영수증.
- `ref/`: 전사 JSON 40개와 사용 가능 회의 RTTM 39개.
- `inventory.json`: 각 음원·전사·RTTM의 경로·해시, 분할과 평가 적격 여부. 소비자는 `eligible_for_evaluation`이 참인 행만 사용한다.
- `summary.json`: 확보·사용 가능 수량을 분리한 집계. `quality-audit.json`·`verification.json`: 이번 수집의 품질 대조와 검증 기록.

모든 WAV의 16kHz·16bit·mono PCM 전체 길이와 SHA-256, 모든 정답 파일 해시, ZIP CRC를 확인했다.
160개 화자 단어 XML의 참조를 대조했으며 중복 참조는 없었다. 서로 다른 회의 5건은 ffmpeg 전체 디코딩도 통과했다.
정답 경계·참조 오류·비언어 이벤트·잘린 PCM·음원 밖 경계 관련 회귀 테스트 8개가 통과했다.
SHA-256은 현지 무결성 기록이며 배포자가 별도로 공표한 체크섬과의 대조는 아니다.
