#!/usr/bin/env python3
"""정답 속기록과 STT 전사의 오류율을 잰다.

한국어는 띄어쓰기가 유동적이라 어절 단위 WER이 표기 차이에 과민하다.
CER(문자 오류율)을 주 지표로 쓰고 WER을 함께 낸다.

정규화 단계를 겹쳐 가며 재서, 어느 규칙이 실제 인식 오류와 표기 차이를
가르는지 보여 준다.

사용법:
    python score.py --ref <속기록.txt> --hyp <전사.txt> [--hyp <전사2.txt> ...]
"""

import argparse
import re
import unicodedata
from pathlib import Path

LABEL_COLON = re.compile(r'^-([가-힣]{2,4}):\s*')
LABEL_PAREN = re.compile(r'^-\(([가-힣\s]{2,6})\)\s*')
TS_PREFIX = re.compile(r'^\[\d{2}:\d{2}:\d{2}\]\s*')
SPK_PREFIX = re.compile(r'^\[화자\s*\d+\]\s*')
BRACKET = re.compile(r'\[[^\]]*\]')          # [박수] [웃음] 등 비언어 표기
PAREN_NOTE = re.compile(r'\([^)]*\)')         # (청취 불능) (종료) 등
PUNCT = re.compile(r'[^\w\s]|_', re.UNICODE)
SPACE = re.compile(r'\s+')

# 단독 토큰으로 나타날 때만 지우는 간투사. 지시사로도 쓰이는 말이 섞여 있어
# 부분 문자열로 지우면 안 된다.
FILLERS = {'어', '음', '아', '그', '저', '뭐', '에', '으', '어허', '흠',
           '네', '예', '자', '이제', '좀', '막', '뭐랄까', '그냥'}


def strip_markup(text):
    text = TS_PREFIX.sub('', text)
    text = SPK_PREFIX.sub('', text)
    text = LABEL_COLON.sub('', text)
    text = LABEL_PAREN.sub('', text)
    text = BRACKET.sub(' ', text)
    text = PAREN_NOTE.sub(' ', text)
    return text


def load(path):
    raw = Path(path).read_text(encoding='utf-8')
    out = []
    for line in re.split(r'\r\n|\r|\n', raw):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        out.append(strip_markup(line))
    return ' '.join(out)


def norm(text, *, punct=False, fillers=False, numbers=False):
    text = unicodedata.normalize('NFC', text)
    if punct:
        text = PUNCT.sub(' ', text)
    if fillers:
        text = ' '.join(w for w in text.split() if w not in FILLERS)
    if numbers:
        # 자릿수 구분 쉼표와 단위 앞 공백을 지워 표기 차이를 없앤다.
        text = re.sub(r'(?<=\d),(?=\d)', '', text)
        text = re.sub(r'(\d)\s+(?=만|천|억|원|명|개|년|월|일|퍼센트|%)', r'\1', text)
    return SPACE.sub(' ', text).strip()


def edit_distance(a, b):
    """Levenshtein 거리. 메모리를 아끼려고 두 행만 쓴다."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def rates(ref, hyp):
    rc, hc = ref.replace(' ', ''), hyp.replace(' ', '')
    cer = edit_distance(rc, hc) / len(rc) if rc else 0.0
    rw, hw = ref.split(), hyp.split()
    wer = edit_distance(rw, hw) / len(rw) if rw else 0.0
    return cer, wer, len(rc), len(hc)


STAGES = [
    ('원문 그대로', {}),
    ('구두점 제거', {'punct': True}),
    ('+ 간투사 제거', {'punct': True, 'fillers': True}),
    ('+ 숫자 표기 통일', {'punct': True, 'fillers': True, 'numbers': True}),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref', required=True, help='정답 속기록')
    ap.add_argument('--hyp', required=True, action='append', help='STT 전사 (여러 번 지정 가능)')
    args = ap.parse_args()

    ref_raw = load(args.ref)
    print(f'정답: {Path(args.ref).name}  {len(ref_raw.replace(" ", "")):,}자\n')

    for hp in args.hyp:
        hyp_raw = load(hp)
        print(f'--- {Path(hp).name} ---')
        print(f'{"정규화":<20} {"CER":>7} {"WER":>7}   {"정답자수":>8} {"가설자수":>8}')
        for label, opt in STAGES:
            r = norm(ref_raw, **opt)
            h = norm(hyp_raw, **opt)
            cer, wer, rl, hl = rates(r, h)
            print(f'{label:<20} {cer:>6.1%} {wer:>7.1%}   {rl:>8,} {hl:>8,}')
        print()


if __name__ == '__main__':
    main()
