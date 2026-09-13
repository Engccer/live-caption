#!/usr/bin/env python3
"""정렬 결과를 검증한다.

정렬은 틀려도 조용히 틀린다. 각 속기록 줄에 붙은 시각으로 전사를 꺼내
그 줄과 실제로 같은 내용인지 3-gram 중복률로 재고, 단조성과 끝단 여백을 확인한다.

사용법:
    python verify_align.py --aligned <aligned.tsv> --ts <deepgram_ts.txt> [--duration 3913]
"""

import argparse
import re
import statistics
from pathlib import Path

KEEP = re.compile(r'[^가-힣0-9a-zA-Z]')
TS_LINE = re.compile(r'^\[(\d{2}):(\d{2}):(\d{2})\]\s*(?:\[화자\s*(\d+)\]\s*)?(.*)$')


def norm(t):
    return KEEP.sub('', t)


def trigram_recall(a, b):
    """a의 3-gram 중 b에 있는 비율. a가 3자 미만이면 판정을 건너뛴다."""
    if len(a) < 3:
        return None
    A = {a[i:i + 3] for i in range(len(a) - 2)}
    B = {b[i:i + 3] for i in range(len(b) - 2)}
    return len(A & B) / len(A)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--aligned', required=True)
    ap.add_argument('--ts', required=True)
    ap.add_argument('--duration', type=int, default=0, help='오디오 길이(초)')
    ap.add_argument('--show', type=int, default=10, help='일치율 하위 몇 줄을 보일지')
    args = ap.parse_args()

    rows = []
    for l in Path(args.aligned).read_text(encoding='utf-8').splitlines():
        if l.startswith('#') or not l.strip():
            continue
        p = l.split('\t')
        rows.append({'line': int(p[0]), 'sec': int(p[1]) if p[1] else None,
                     'method': p[3], 'speaker': p[4], 'text': p[5] if len(p) > 5 else ''})

    ts = []
    for l in Path(args.ts).read_text(encoding='utf-8').splitlines():
        m = TS_LINE.match(l.strip())
        if m:
            h, mi, s, _, txt = m.groups()
            ts.append((int(h) * 3600 + int(mi) * 60 + int(s), txt))

    timed = [r for r in rows if r['sec'] is not None]

    def window(t0, t1):
        return norm(' '.join(x[1] for x in ts if t0 <= x[0] <= t1))

    scored = []
    for i, r in enumerate(timed):
        t0 = r['sec'] - 3
        t1 = timed[i + 1]['sec'] + 3 if i + 1 < len(timed) else r['sec'] + 180
        sc = trigram_recall(norm(r['text']), window(t0, t1))
        r['score'] = sc
        if sc is not None:
            scored.append(sc)

    print(f'단위 {len(rows)}개 (시각 있음 {len(timed)}, 범위 밖 {len(rows) - len(timed)})')
    print(f'내용 일치율: 중앙 {statistics.median(scored):.2f}, 평균 {statistics.mean(scored):.2f}'
          f' (판정 대상 {len(scored)}개, 3자 미만 제외 {len(timed) - len(scored)}개)')
    print(f'  0.5 미만 {sum(1 for s in scored if s < 0.5)}개, '
          f'0.2 미만 {sum(1 for s in scored if s < 0.2)}개')

    bad = [i for i in range(1, len(timed)) if timed[i]['sec'] < timed[i - 1]['sec']]
    print(f'시각 역행: {len(bad)}개')

    if timed:
        print(f'범위: {timed[0]["sec"]}초 ~ {timed[-1]["sec"]}초', end='')
        if args.duration:
            print(f' (오디오 {args.duration}초, 끝단 여백 {args.duration - timed[-1]["sec"]}초)')
        else:
            print()

    worst = sorted((r for r in timed if r.get('score') is not None),
                   key=lambda x: x['score'])[:args.show]
    if worst:
        print(f'\n일치율 하위 {len(worst)}줄:')
        for r in worst:
            print(f'  줄{r["line"]:4d} {r["sec"] // 60:02d}:{r["sec"] % 60:02d} '
                  f'{r["method"]:12s} {r["score"]:.2f} | {r["text"][:50]}')

    out = [r for r in rows if r['sec'] is None]
    if out:
        print(f'\n녹음 범위 밖 {len(out)}줄:')
        for r in out:
            print(f'  줄{r["line"]:4d} | {r["text"][:60]}')


if __name__ == '__main__':
    main()
