import itertools
import random
import unittest

import stream_score as ss
from score import edit_distance


def brute_del_sub(ref, hyp):
    """독립 구현: 정답의 부분수열 중 가설의 부분수열인 가장 긴 것을 전수로 찾는다.
    삽입이 공짜이고 삭제·치환이 1이면 최솟값 = len(ref) - 그 길이다."""
    def is_subseq(a, b):
        it = iter(b)
        return all(c in it for c in a)
    for k in range(len(ref), -1, -1):
        if any(is_subseq(c, hyp) for c in itertools.combinations(ref, k)):
            return len(ref) - k


class DelSubTest(unittest.TestCase):
    def test_reviewer_counterexample(self):
        self.assertEqual(ss.del_sub_errors('bbbcacac', 'caacbaaacb'), 3)

    def test_matches_brute_force(self):
        rng = random.Random(20261016)
        for _ in range(400):
            ref = ''.join(rng.choice('abc') for _ in range(rng.randint(0, 7)))
            hyp = ''.join(rng.choice('abc') for _ in range(rng.randint(0, 8)))
            self.assertEqual(ss.del_sub_errors(ref, hyp), brute_del_sub(ref, hyp), (ref, hyp))

    def test_insertions_free(self):
        self.assertEqual(ss.del_sub_errors('가나다', 'x가y나z다w'), 0)
        self.assertEqual(ss.del_sub_errors('가나다', ''), 3)


class CharCountsTest(unittest.TestCase):
    def test_standard_includes_insertions(self):
        c = ss.char_counts('가나다', '가나다 라마', 'standard')
        self.assertEqual((c['errors'], c['ref_chars']), (2, 3))
        self.assertEqual(c['errors'], edit_distance('가나다', '가나다라마'))

    def test_del_sub_excludes_insertions_and_fillers(self):
        c = ss.char_counts('가나다라', '어 가나다라 잡담', 'del_sub')
        self.assertEqual(c['errors'], 0)
        c = ss.char_counts('가나다라', '가나', 'del_sub')
        self.assertEqual(c['errors'], 2)

    def test_empty_hypothesis(self):
        self.assertEqual(ss.char_counts('가나', '', 'standard')['errors'], 2)

    def test_ref_chars(self):
        self.assertEqual(ss.ref_chars('가, 나 다!', 'standard'), 3)


class LatencyTest(unittest.TestCase):
    def test_partial_and_final_lags(self):
        ev = [{'kind': 'transcript', 'text': 'a', 'final': False, 't_ms': 300, 'audio_ms': 100},
              {'kind': 'transcript', 'text': 'b', 'final': False, 't_ms': 500, 'audio_ms': 100},
              {'kind': 'transcript', 'text': 'c', 'final': True, 't_ms': 900, 'audio_ms': 200},
              {'kind': 'transcript', 'text': 'd', 'final': False, 't_ms': 900},     # 위치 없음
              {'kind': 'speaker', 't_ms': 100, 'audio_ms': 0}]
        lat = ss.latency_stats(ev)
        self.assertEqual(lat['partial'], {'n': 2, 'median_ms': 300, 'max_ms': 400})
        self.assertEqual(lat['final'], {'n': 1, 'median_ms': 700, 'max_ms': 700})

    def test_no_positions(self):
        self.assertEqual(ss.latency_stats([])['partial']['median_ms'], None)


class AggregateTest(unittest.TestCase):
    def test_micro_average(self):
        rows = [{'set': 's', 'sent_seconds': 1, 'events': [], 'counts': {'errors': 1, 'ref_chars': 10}},
                {'set': 's', 'sent_seconds': 2, 'events': [], 'counts': {'errors': 3, 'ref_chars': 30}},
                {'set': 'n', 'sent_seconds': 5, 'events': [], 'counts': None}]
        out = ss.aggregate(rows)
        self.assertAlmostEqual(out['s']['cer'], 0.1)
        self.assertEqual(out['s']['sent_seconds'], 3)
        self.assertIsNone(out['n']['cer'])


if __name__ == '__main__':
    unittest.main()
