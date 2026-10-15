import json
import tempfile
import unittest
import wave
from pathlib import Path

import stream_plan as sp


def write_wav(path, seconds, rate=16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b'\x01\x00' * int(seconds * rate))


def make_root(tmp):
    """합성 자료 루트. 실제 발화를 쓰지 않는다."""
    root = Path(tmp)
    for ds, n, sec in (('fleurs-ko', 5, 4.0), ('zeroth', 3, 2.0)):
        ref = root / 'public' / ds / 'ref' / 'test.jsonl'
        ref.parent.mkdir(parents=True)
        with ref.open('w') as f:
            for i in range(n):
                f.write(json.dumps({'id': f'{ds}/test/{i:02d}', 'split': 'test', 'evaluation_ready': True,
                                    'audio': f'a/{i}.wav', 'samples': int(sec * 16000),
                                    'sample_rate': 16000, 'text': f'가나{i}'}) + '\n')
    tsv = root / 'chonghoe-2026' / 'ref' / 'aligned.tsv'
    tsv.parent.mkdir(parents=True)
    tsv.write_text('# 헤더\n# line\trel_sec\trel_hhmmss\tmethod\tspeaker\ttext\n'
                   '1\t\t\tout-of-range\tA\t녹음전\n'
                   '2\t5\t00:00:05\tanchor\tA\t하나\n'
                   '3\t300\t00:05:00\tanchor\tA\t둘\n'
                   '4\t590\t00:09:50\tanchor\tB\t셋\n'
                   '5\t620\t00:10:20\tanchor\tB\t넷\n', encoding='utf-8')
    write_wav(root / 'chonghoe-2026' / 'audio' / 'chonghoe_16k.wav', 700)
    write_wav(root / 'jangnal-2026' / 'audio' / 'jangnal_1bu_16k.wav', 30)
    return root


class BundleTest(unittest.TestCase):
    def clips(self, secs):
        return [(f'id{i}', Path(f'{i}.wav'), s, f't{i}') for i, s in enumerate(secs)]

    def test_greedy_with_gap_under_cap(self):
        units = sp.bundle('x', self.clips([4, 4, 4, 4]), gap=1.0, max_seconds=10)
        # 4+1+4=9, 다음은 9+1+4=14>10 이므로 새 묶음
        self.assertEqual([len(u.pieces) for u in units], [2, 2])
        self.assertEqual([u.seconds for u in units], [9, 9])
        self.assertEqual(units[0].ref, 't0 t1')
        self.assertEqual(units[1].clip_ids, ['id2', 'id3'])
        self.assertTrue(all(u.seconds <= 10 for u in units))

    def test_every_clip_once_in_order(self):
        clips = self.clips([3, 7, 2, 5, 1, 9])
        units = sp.bundle('x', clips, gap=1.0, max_seconds=10)
        self.assertEqual([i for u in units for i in u.clip_ids], [c[0] for c in clips])

    def test_clip_longer_than_cap_rejected(self):
        with self.assertRaises(ValueError):
            sp.bundle('x', self.clips([11]), max_seconds=10)


class MeetingTest(unittest.TestCase):
    def test_split_at_nearest_line_boundary(self):
        lines = [(0, 'a'), (40, 'b'), (55, 'c'), (90, 'd')]
        units = sp.meeting_units('m', Path('m.wav'), lines, end=100, max_segment=60)
        self.assertEqual([(u.pieces[0].start, u.pieces[0].end) for u in units], [(0, 55), (55, 100)])
        self.assertEqual([u.ref for u in units], ['a b', 'c d'])
        self.assertEqual(units[0].scoring, 'del_sub')

    def test_unsplittable_rejected(self):
        with self.assertRaises(ValueError):
            sp.meeting_units('m', Path('m.wav'), [(0, 'a'), (95, 'b')], end=100, max_segment=60)

    def test_out_of_range_lines_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            lines = sp.aligned_lines(root / 'chonghoe-2026' / 'ref' / 'aligned.tsv')
            self.assertEqual([s for s, _ in lines], [5, 300, 590, 620])


class StageTest(unittest.TestCase):
    def test_taste_cuts_at_last_line_start_before_600(self):
        with tempfile.TemporaryDirectory() as tmp:
            units = sp.stage_units(make_root(tmp), 'taste')
            self.assertEqual([u.id for u in units], ['chonghoe-2026/first', 'jangnal-2026/all'])
            self.assertEqual(units[0].pieces[0].end, 590)
            self.assertEqual(units[0].ref, '하나 둘')
            self.assertIsNone(units[1].ref)
            self.assertAlmostEqual(sum(u.seconds for u in units), 620)

    def test_core_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            units = sp.stage_units(make_root(tmp), 'core')
            sets = [u.set for u in units]
            self.assertEqual(sorted(set(sets)), ['chonghoe-2026', 'fleurs-ko', 'jangnal-2026', 'zeroth'])
            fleurs = [u for u in units if u.set == 'fleurs-ko']
            self.assertEqual(sum(len(u.clip_ids) for u in fleurs), 5)
            self.assertAlmostEqual(sum(u.seconds for u in fleurs), 5 * 4 + 4 * 1.0)
            chonghoe = [u for u in units if u.set == 'chonghoe-2026']
            self.assertEqual(chonghoe[0].ref, '하나 둘 셋 넷')

    def test_unready_reference_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            ref = root / 'public' / 'zeroth' / 'ref' / 'test.jsonl'
            rows = [json.loads(x) for x in ref.read_text().splitlines()]
            rows[0]['evaluation_ready'] = False
            ref.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
            with self.assertRaises(ValueError):
                sp.stage_units(root, 'core')

    def test_per_engine_split_leaves_others_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            plan = sp.engine_units(root, 'taste', ['muse', 'gemini', 'deepgram'])
            self.assertIs(plan['muse'], plan['deepgram'])
            self.assertEqual([u.id for u in plan['muse']], ['chonghoe-2026/first', 'jangnal-2026/all'])
            self.assertTrue(all(u.seconds <= 540 for u in plan['gemini']))
            self.assertEqual([u.id for u in plan['gemini']][:2],
                             ['chonghoe-2026/first-seg-1', 'chonghoe-2026/first-seg-2'])
            # 같은 정답 글자가 빠짐없이 나뉘어 들어간다
            self.assertEqual(' '.join(u.ref for u in plan['gemini'] if u.ref), '하나 둘')

    def test_common_split_uses_minimum_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            plan = sp.engine_units(root, 'taste', ['muse', 'gemini'], common=True)
            self.assertIs(plan['muse'], plan['gemini'])
            self.assertTrue(all(u.seconds <= 540 for u in plan['muse']))
            only_unlimited = sp.engine_units(root, 'taste', ['deepgram'], common=True)
            self.assertEqual(len(only_unlimited['deepgram']), 2)

    def test_split_adds_pieces_until_all_fit(self):
        # 2분할이면 목표 50초에 가장 가까운 경계 30에서 잘려 뒤가 70초로 상한을 넘으므로 3분할로 간다
        lines = [(0, 'a'), (10, 'b'), (30, 'c'), (70, 'd')]
        units = sp.meeting_units('m', Path('m.wav'), lines, end=100, max_segment=55)
        self.assertEqual([(u.pieces[0].start, u.pieces[0].end) for u in units], [(0, 30), (30, 70), (70, 100)])
        self.assertEqual(' '.join(u.ref for u in units), 'a b c d')

    def test_session_limit_check(self):
        unit = sp.Unit('u', 's', [sp.Piece(Path('a'), 0, 4000)])
        with self.assertRaises(ValueError):
            sp.check_session_limits([unit], ['mai'])
        sp.check_session_limits([unit], ['deepgram'])


class PcmTest(unittest.TestCase):
    def test_slices_and_silence_gap(self):
        audio = {Path('a'): b'\x01\x00' * 16000, Path('b'): b'\x02\x00' * 16000}
        unit = sp.Unit('u', 's', [sp.Piece(Path('a'), 0, 0.5), sp.Piece(Path('b'), 0.5, 1.0)], gap=0.25)
        pcm = sp.unit_pcm(unit, decode=lambda p: audio[p])
        self.assertEqual(len(pcm), (8000 + 4000 + 8000) * 2)
        self.assertEqual(pcm[16000:24000], b'\x00' * 8000)
        self.assertAlmostEqual(len(pcm) / 2 / 16000, unit.seconds)

    def test_pcm_length_check(self):
        unit = sp.Unit('u', 's', [sp.Piece(Path('a'), 0, 1.0)])
        self.assertIsNone(sp.check_pcm_length(unit, b'\x00\x00' * 16100))     # 6.25ms 차이 허용
        self.assertIn('불일치', sp.check_pcm_length(unit, b'\x00\x00' * 15000))
        # 파일이 계획보다 짧으면 unit_pcm이 잘라 낸 결과도 걸린다
        short = sp.unit_pcm(unit, decode=lambda p: b'\x00\x00' * 8000)
        self.assertIn('불일치', sp.check_pcm_length(unit, short))

    def test_decode_reads_pcm16_wav_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'x.wav'
            write_wav(path, 0.5)
            self.assertEqual(len(sp.decode_pcm(path)), 16000)


if __name__ == '__main__':
    unittest.main()
