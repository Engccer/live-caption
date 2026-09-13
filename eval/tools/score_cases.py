#!/usr/bin/env python3
"""JSONL 정답과 가설을 ID로 대조해 삽입을 포함한 micro CER/WER을 집계한다.

정규화는 score.norm(punct=True)만 적용한다. 숫자와 간투사는 보존한다.
--split 지정 시 정답만 해당 split으로 고르며, 가설은 선택된 ID 집합과
정확히 같아야 한다. 다른 split의 가설도 초과 입력으로 거부한다.
train은 --split train을 명시한 경우만 채점한다. 원문과 개별 ID는 출력하지 않는다.
"""

import argparse
import json
import math
import sys
from pathlib import Path

from score import edit_distance, norm


class InputError(ValueError):
    """입력 내용을 노출하지 않는 검증 오류."""


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError('JSON 객체에 중복 키가 있습니다')
        result[key] = value
    return result


def _reject_constant(_value):
    raise InputError('JSON에 비유한 숫자가 있습니다')


def _check_finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise InputError('JSON에 비유한 숫자가 있습니다')
    if isinstance(value, dict):
        for item in value.values():
            _check_finite(item)
    elif isinstance(value, list):
        for item in value:
            _check_finite(item)


def _string(row, field, *, empty=False):
    value = row.get(field)
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise InputError(f'{field} 필드의 문자열 형식이 잘못되었습니다')
    return value


def _validate(row, kind):
    if not isinstance(row, dict):
        raise InputError('JSON 객체가 필요합니다')
    _check_finite(row)
    _string(row, 'id')
    _string(row, 'text', empty=kind == 'hyp')
    if kind == 'hyp':
        return
    for field in ('dataset', 'split', 'cluster', 'audio'):
        _string(row, field)
    if row['split'] not in ('train', 'dev', 'test', 'all'):
        raise InputError('split은 train/dev/test/all 중 하나여야 합니다')
    duration = row.get('duration_seconds')
    if type(duration) not in (int, float) or duration <= 0:
        raise InputError('duration_seconds는 유한한 양수여야 합니다')
    if type(row.get('evaluation_ready')) is not bool:
        raise InputError('evaluation_ready는 불리언이어야 합니다')
    metrics = row.get('eligible_metrics')
    if not isinstance(metrics, list) or any(not isinstance(m, str) for m in metrics):
        raise InputError('eligible_metrics는 문자열 배열이어야 합니다')
    if not norm(row['text'], punct=True):
        raise InputError('정규화 후 정답이 비어 있습니다')


def load_rows(path, kind):
    """누락/중복/형식 오류를 줄 번호만으로 알리고 입력 값은 숨긴다."""
    rows = {}
    try:
        with Path(path).open(encoding='utf-8') as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    row = json.loads(line, object_pairs_hook=_object,
                                     parse_constant=_reject_constant)
                    _validate(row, kind)
                    if row['id'] in rows:
                        raise InputError('중복 ID가 있습니다')
                    rows[row['id']] = row
                except (ValueError, RecursionError) as exc:
                    reason = str(exc) if isinstance(exc, InputError) else 'JSON 형식이 잘못되었습니다'
                    raise InputError(f'{kind} {line_number}행: {reason}') from None
    except (OSError, UnicodeError):
        raise InputError(f'{kind} 파일을 UTF-8로 읽을 수 없습니다') from None
    if not rows:
        raise InputError(f'{kind} 입력이 비어 있습니다')
    return rows


def _counts():
    return {'cases': 0, 'character_errors': 0, 'reference_characters': 0,
            'word_errors': 0, 'reference_words': 0}


def _ratios(counts):
    return dict(counts, cer=counts['character_errors'] / counts['reference_characters'],
                wer=counts['word_errors'] / counts['reference_words'])


def score_cases(refs, hyps, *, split=None, allow_provisional=False):
    """행별 거리를 더한 뒤 전체 정답 분모로 나누며 행 평균은 쓰지 않는다."""
    selected = {key: row for key, row in refs.items()
                if split is None or row['split'] == split}
    if not selected:
        raise InputError('선택한 split의 정답이 없습니다')
    if split != 'train' and any(row['split'] == 'train' for row in selected.values()):
        raise InputError('train 채점은 --split train을 명시해야 합니다')
    missing = selected.keys() - hyps.keys()
    extra = hyps.keys() - selected.keys()
    if missing or extra:
        raise InputError(f'ID 불일치: 누락 {len(missing)}개, 초과 {len(extra)}개')
    provisional = sum(not row['evaluation_ready'] or not {'cer', 'wer'}.issubset(row['eligible_metrics'])
                      for row in selected.values())
    if provisional and not allow_provisional:
        raise InputError('평가 미준비 정답이 있습니다. 임시 채점에는 --allow-provisional이 필요합니다')
    overall = _counts()
    groups = {}
    for key, row in selected.items():
        ref = norm(row['text'], punct=True)
        hyp = norm(hyps[key]['text'], punct=True)
        ref_chars, hyp_chars = ref.replace(' ', ''), hyp.replace(' ', '')
        ref_words, hyp_words = ref.split(), hyp.split()
        counts = {'cases': 1,
                  'character_errors': edit_distance(ref_chars, hyp_chars),
                  'reference_characters': len(ref_chars),
                  'word_errors': edit_distance(ref_words, hyp_words),
                  'reference_words': len(ref_words)}
        group = groups.setdefault((row['dataset'], row['split']), _counts())
        for field, value in counts.items():
            overall[field] += value
            group[field] += value
    return {'normalization': 'NFC; punctuation to spaces; collapse whitespace; preserve numbers and fillers',
            'aggregation': 'micro', 'selected_split': split,
            'evaluation_ready': not bool(provisional), 'provisional_cases': provisional,
            'allow_provisional': allow_provisional,
            'overall': _ratios(overall),
            'by_dataset_split': [dict(dataset=dataset, split=group_split, **_ratios(counts))
                                 for (dataset, group_split), counts in sorted(groups.items())]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', required=True, help='정답 JSONL')
    parser.add_argument('--hyp', required=True, help='가설 JSONL')
    parser.add_argument('--split', choices=('train', 'dev', 'test', 'all'),
                        help='정답 split 선택. 가설은 선택한 ID만 포함해야 함')
    parser.add_argument('--allow-provisional', action='store_true', help='미준비 정답의 임시 채점 허용')
    args = parser.parse_args(argv)
    try:
        result = score_cases(load_rows(args.ref, 'ref'), load_rows(args.hyp, 'hyp'),
                             split=args.split, allow_provisional=args.allow_provisional)
    except InputError as exc:
        print(f'오류: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
