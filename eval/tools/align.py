#!/usr/bin/env python3
"""속기록에 시각을 붙인다.

속기록에는 시각이 없고 STT 전사에는 있다. 둘은 표현이 다르지만 순서가 같으므로
단어 시퀀스를 정렬해 공통 앵커를 찾고, 앵커 사이를 선형 보간해 속기록 각 줄의
시작 시각을 구한다.

사용법:
    python align.py --steno <속기록.txt> --ts <deepgram_ts.txt> --out <출력.tsv>

입력 형식:
    속기록  : 한 줄이 한 단위. `-이름:` 또는 `-(이름)`으로 화자 라벨이 붙을 수 있다.
    전사    : `[HH:MM:SS] [화자 N] 텍스트` 한 줄에 하나.
"""

import argparse
import difflib
import re
import sys
from pathlib import Path

LABEL_COLON = re.compile(r'^-([가-힣]{2,4}):\s*(.*)$')
LABEL_PAREN = re.compile(r'^-\(([가-힣\s]{2,6})\)\s*(.*)$')
TS_LINE = re.compile(r'^\[(\d{2}):(\d{2}):(\d{2})\]\s*(?:\[화자\s*(\d+)\]\s*)?(.*)$')
# 비교용 정규화: 한글·숫자·영문만 남긴다. 구두점·공백·간투사 표기 차이를 지운다.
KEEP = re.compile(r'[^가-힣0-9a-zA-Z]')


def norm(text):
    return KEEP.sub('', text)


def read_steno(path):
    """속기록을 (줄번호, 화자, 원문) 리스트로 읽는다. 화자는 직전 값을 상속한다."""
    raw = Path(path).read_text(encoding='utf-8')
    out, cur = [], None
    for i, line in enumerate(re.split(r'\r\n|\r|\n', raw), 1):
        line = line.strip()
        if not line:
            continue
        m = LABEL_COLON.match(line) or LABEL_PAREN.match(line)
        if m:
            cur = m.group(1).strip()
            body = m.group(2)
        else:
            body = line[1:].strip() if line.startswith('-') else line
        out.append({'line': i, 'speaker': cur, 'text': body})
    return out


def read_ts(path):
    """전사를 (초, 화자번호, 텍스트) 리스트로 읽는다."""
    out = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        m = TS_LINE.match(line.strip())
        if not m:
            continue
        h, mi, s, spk, text = m.groups()
        out.append({'sec': int(h) * 3600 + int(mi) * 60 + int(s),
                    'spk': spk, 'text': text})
    return out


def to_words(units, key='text'):
    """단위 리스트를 (정규화 단어, 단위 인덱스) 리스트로 편다."""
    words, owner = [], []
    for idx, u in enumerate(units):
        for w in u[key].split():
            n = norm(w)
            if n:
                words.append(n)
                owner.append(idx)
    return words, owner


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--steno', required=True)
    ap.add_argument('--ts', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--offset', type=int, default=0,
                    help='영상 t=0의 절대 시각(초). 지정하면 절대 시각 열을 더한다.')
    args = ap.parse_args()

    steno = read_steno(args.steno)
    ts = read_ts(args.ts)
    if not steno or not ts:
        sys.exit('입력이 비었다')

    sw, so = to_words(steno)
    tw, to = to_words(ts)

    sm = difflib.SequenceMatcher(None, sw, tw, autojunk=False)
    blocks = sm.get_matching_blocks()

    # 속기록 단위별로 "매칭된 전사 단위"의 최소 시각을 모은다.
    hit = {}
    matched_words = 0
    for a, b, size in blocks:
        if not size:
            continue
        matched_words += size
        for k in range(size):
            si, ti = so[a + k], to[b + k]
            sec = ts[ti]['sec']
            if si not in hit or sec < hit[si]:
                hit[si] = sec

    # 앵커가 없는 단위는 앞뒤 앵커로 보간한다.
    anchors = sorted(hit)
    times, method = [None] * len(steno), [''] * len(steno)
    for i in range(len(steno)):
        if i in hit:
            times[i], method[i] = hit[i], 'anchor'
    # 첫 앵커 앞과 마지막 앵커 뒤는 녹음에 없는 구간이다. 시각을 지어내지 않는다.
    # (속기사는 녹화 시작 전 대화부터 적는 일이 있다.)
    first, last = (anchors[0], anchors[-1]) if anchors else (None, None)
    prev = None
    for i in range(len(steno)):
        if times[i] is not None:
            prev = i
            continue
        if first is None or i < first or i > last:
            method[i] = 'out-of-range'
            continue
        nxt = next((j for j in anchors if j > i), None)
        span = nxt - prev
        frac = (i - prev) / span
        times[i] = round(times[prev] + (times[nxt] - times[prev]) * frac)
        method[i] = 'interp'

    # 시각은 단조 증가해야 한다.
    for i in range(1, len(times)):
        if times[i] is not None and times[i - 1] is not None and times[i] < times[i - 1]:
            times[i] = times[i - 1]

    def hhmmss(sec):
        return f'{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}'

    lines = ['# 속기록 시각 정렬 결과',
             f'# 속기록 {len(steno)}단위, 전사 {len(ts)}단위',
             f'# 단어 매칭률 {matched_words}/{len(sw)} ({matched_words / len(sw) * 100:.1f}%)',
             '# method: anchor=전사와 직접 매칭, interp=앞뒤 앵커로 보간, '
             'out-of-range=녹음 범위 밖(시각 없음)']
    header = ['line', 'rel_sec', 'rel_hhmmss']
    if args.offset:
        header.append('abs_hhmmss')
    header += ['method', 'speaker', 'text']
    lines.append('# ' + '\t'.join(header))

    for i, u in enumerate(steno):
        t = times[i]
        row = [str(u['line']),
               '' if t is None else str(t),
               '' if t is None else hhmmss(t)]
        if args.offset:
            row.append('' if t is None else hhmmss(args.offset + t))
        row += [method[i], u['speaker'] or '', u['text']]
        lines.append('\t'.join(row))

    Path(args.out).write_text('\n'.join(lines) + '\n', encoding='utf-8')

    n_anchor = method.count('anchor')
    n_interp = method.count('interp')
    print(f'속기록 {len(steno)}단위, 전사 {len(ts)}단위')
    print(f'단어 매칭률: {matched_words}/{len(sw)} ({matched_words / len(sw) * 100:.1f}%)')
    n_out = method.count('out-of-range')
    print(f'앵커 {n_anchor}단위, 보간 {n_interp}단위, 녹음 범위 밖 {n_out}단위')
    print(f'출력: {args.out}')


if __name__ == '__main__':
    main()
