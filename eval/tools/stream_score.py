#!/usr/bin/env python3
"""스트리밍 결과의 문자 오류율과 지연을 집계한다. 텍스트는 출력하지 않는다.

- standard: 공개 자료 계약(score_cases.py)과 같다. 구두점만 정규화하고 삽입을 포함한다.
- del_sub: 총회 MANIFEST의 채택 지표다. 구두점·간투사·숫자 표기를 정규화하고
  (삭제 + 치환) / 정답 문자수로 잰다. 속기사가 버린 잡담이 삽입으로 잡히기 때문이다.
"""
import statistics

from score import edit_distance, norm

_OPTIONS = {'standard': {'punct': True},
            'del_sub': {'punct': True, 'fillers': True, 'numbers': True}}


def del_sub_errors(ref, hyp):
    """삽입 비용 0, 삭제·치환 1인 DP로 (삭제 + 치환)의 최솟값을 구한다."""
    prev = [0] * (len(hyp) + 1)                # 앞쪽 삽입은 공짜
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1,                 # 삭제
                           cur[j - 1],                  # 삽입(0)
                           prev[j - 1] + (rc != hc)))   # 일치·치환
        prev = cur
    return prev[-1]


def _normalized(text, scoring):
    return norm(text or '', **_OPTIONS[scoring]).replace(' ', '')


def ref_chars(ref_text, scoring):
    return len(_normalized(ref_text, scoring))


def char_counts(ref_text, hyp_text, scoring):
    ref, hyp = _normalized(ref_text, scoring), _normalized(hyp_text, scoring)
    errors = edit_distance(ref, hyp) if scoring == 'standard' else del_sub_errors(ref, hyp)
    return {'errors': errors, 'ref_chars': len(ref)}


def latency_stats(events):
    """수신 시각 - 엔진이 알린 오디오 위치(ms). 위치를 주지 않는 이벤트는 뺀다."""
    def lags(final):
        return [e['t_ms'] - e['audio_ms'] for e in events
                if e.get('kind') == 'transcript' and bool(e.get('final')) == final
                and e.get('audio_ms') is not None and e.get('text')]
    out = {}
    for name, xs in (('partial', lags(False)), ('final', lags(True))):
        out[name] = ({'n': len(xs), 'median_ms': round(statistics.median(xs)), 'max_ms': round(max(xs))}
                     if xs else {'n': 0, 'median_ms': None, 'max_ms': None})
    return out


def aggregate(results):
    """세트별로 행 거리를 더해 정답 문자 합으로 나눈다(micro). 지연은 이벤트를 모아 잰다."""
    sets = {}
    for r in results:
        s = sets.setdefault(r['set'], {'units': 0, 'errors': 0, 'ref_chars': 0, 'scored': False,
                                       'sent_seconds': 0.0, 'events': [], 'aborted': 0})
        s['units'] += 1
        s['sent_seconds'] += r['sent_seconds']
        s['events'] += r['events']
        s['aborted'] += bool(r.get('aborted'))
        if r.get('counts'):
            s['scored'] = True
            s['errors'] += r['counts']['errors']
            s['ref_chars'] += r['counts']['ref_chars']
    out = {}
    for name, s in sets.items():
        out[name] = {'units': s['units'], 'aborted': s['aborted'], 'sent_seconds': s['sent_seconds'],
                     'cer': s['errors'] / s['ref_chars'] if s['scored'] and s['ref_chars'] else None,
                     'latency': latency_stats(s['events'])}
    return out
