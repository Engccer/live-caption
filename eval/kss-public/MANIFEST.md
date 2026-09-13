# KSS 공개 낭독 자료

## 판정

**보조 ASR 자료로 확보 완료, 독립 평가 세트로는 미확정.** 전문 성우 한 명의 실제
낭독 음성과 사람이 작성한 책의 대본으로 구성된다. TTS 학습용 자료이며 합성 음성이
아니다. 공식 ASR test split과 화자 전환 정답은 없다. 모든 참조 행은
`evaluation_ready: false`로 둔다.

## 출처와 이용 조건

- 제작자: Kyubyong Park.
- 공식 자료: <https://www.kaggle.com/datasets/bryanpark/korean-single-speaker-speech-dataset>
- 고정 배포 버전: Kaggle dataset version 4, `transcript.v.1.4.txt`.
- 라이선스: **CC BY-NC-SA 4.0**. 비상업 조건과 저작자 표시·동일조건변경허락을 따른다.
- 공개 API 메타데이터에서 라이선스를 확인했다. 이 회차에서 별도 인증이나 동의 없이
  공식 다운로드 URL이 ZIP을 제공했다.
- 소개 페이지는 성우의 실제 녹음과 제작자 책에서 추출한 대본의 결합을 명시한다.
  발화별 사람 청취 검수 여부는 별도 확인하지 않았다.

## 확보와 검증

2026-09-14 수집 결과다. 원본 ZIP, 메타데이터, 다운로드 영수증, 해제한 파일,
참조 JSONL과 검증 요약은 모두 저장소 밖 `$LIVE_CAPTION_EVAL_DATA/public/kss/`
(기본 `~/live-caption-eval/public/kss/`)에 있다.

| 항목 | 실측 |
|---|---:|
| 원본 ZIP | 3,076,028,179 bytes |
| 압축 해제 합계 | 4,319,020,817 bytes |
| CRC 검증 파일 | 12,855개 전부 통과 |
| WAV와 참조 행 | 각각 12,854개, 일대일 대응 |
| WAV 헤더 기준 총길이 | 46,286.24292517007초 |
| 형식 | 모두 44,100Hz, 16bit PCM |
| 채널 | mono 12,853개, stereo 1개 |
| 고유 대본 cluster | 12,463개 |
| 대본의 길이 표기와 WAV 길이 차이 110ms 초과 | 2개 |

소개 페이지의 12,853개와 달리 배포 실물에는 12,854개가 있다. 길이는 대본의
표기값 대신 모든 WAV의 프레임 수와 샘플레이트로 계산했다. stereo 파일은 원본으로
유지한다. 참조의 `text`는 숫자 등을 발음 형태로 푼 제작자 제공 expanded script이며,
같은 대본이 서로 다른 평가 단위로 섞이지 않도록 NFC·공백 정규화한 대본의 SHA-256을
`cluster`에 쓴다. 이러한 정규화는 원본 대본을 변경하지 않는다.

검증 해시:

```text
kss-v4.zip
0992432b98dd60ca44bc2a6f2be01fb9861cd6fbc23f09a1b8b6e77db49d21a9

refs.jsonl
4d7a67a37d64956c222269c6b3a6afce949694d4bae25b122a90e62a079ed05e
```

## 재현

```bash
python3 eval/tools/collect_kss.py --extract
```

`--extract` 없이 실행하면 원본과 인벤토리 요약을 확보한다. 압축 해제 전에는 해제 후
10GiB 여유 공간을 확보할 수 있는지 검사한다. 다운로드 재개, 원본 해시 영수증,
압축 경로 검증과 기존 파일 덮어쓰기 방지는 `eval/tools/public_data.py`를 재사용한다.
스크립트는 발화 원문을 콘솔에 출력하지 않는다.
