"""공개 AMI 전사 정규화의 경계·화자·비언어 이벤트 보존 검증."""
from pathlib import Path
import tempfile
import unittest
import wave

from collect_ami import audio_info, meeting_ids, out_of_audio_segments, parse_speaker, rttm_text


WORDS = b'''<root xmlns:nite="http://nite.sourceforge.net/">
  <w nite:id="w0" starttime="4.5" endtime="4.8">sample</w>
  <w nite:id="w1" punc="true">.</w>
  <vocalsound nite:id="w2" type="laugh" />
  <gap nite:id="w3" />
</root>'''


def segment_xml(first='w0', last='w1', start='4.0', end='5.0', filename='ES2004a.A.words.xml'):
    return f'''<root xmlns:nite="http://nite.sourceforge.net/">
      <segment transcriber_start="{start}" transcriber_end="{end}">
        <nite:child href="{filename}#id({first})..id({last})" />
      </segment></root>'''.encode()


class AmiTests(unittest.TestCase):
    def test_manual_boundary_overrides_forced_word_timing(self):
        result = parse_speaker(WORDS, segment_xml(), 'ES2004a', 'A')[0]
        self.assertEqual((result['start'], result['end']), (4.0, 5.0))
        self.assertEqual(result['text'], 'sample .')
        self.assertEqual(result['lexical_word_count'], 1)
        self.assertEqual(rttm_text('ES2004a', [result]),
                         'SPEAKER ES2004a 1 4.000000 1.000000 <NA> <NA> A <NA> <NA>\n')

    def test_laughter_excluded_but_unintelligible_speech_preserved(self):
        laugh = parse_speaker(WORDS, segment_xml('w2', 'w2'), 'ES2004a', 'A')[0]
        gap = parse_speaker(WORDS, segment_xml('w3', 'w3'), 'ES2004a', 'A')[0]
        self.assertFalse(laugh['speech'])
        self.assertEqual(laugh['event_counts'], {'vocalsound': 1})
        self.assertEqual(rttm_text('ES2004a', [laugh]), '')
        self.assertTrue(gap['speech'])
        self.assertEqual(gap['event_counts'], {'gap': 1})

    def test_wrong_speaker_reference_rejected(self):
        with self.assertRaises(ValueError):
            parse_speaker(WORDS, segment_xml(filename='ES2004a.B.words.xml'), 'ES2004a', 'A')

    def test_invalid_non_speech_boundary_retained_and_not_scored(self):
        event = parse_speaker(WORDS, segment_xml('w2', 'w2', '5', '4'), 'ES2004a', 'A')[0]
        self.assertFalse(event['boundary_valid'])
        self.assertFalse(event['speech'])
        self.assertEqual((event['start'], event['end']), (5.0, 4.0))
        self.assertEqual(rttm_text('ES2004a', [event]), '')

    def test_bad_reference_and_nonfinite_or_reversed_times_rejected(self):
        for xml in [segment_xml(last='missing'), segment_xml('w2', 'w0'),
                    segment_xml(start='nan'), segment_xml(end='inf'), segment_xml(start='5', end='4')]:
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                parse_speaker(WORDS, xml, 'ES2004a', 'A')

    def test_official_scenario_split_disjoint_and_complete(self):
        dev, test = set(meeting_ids('dev')), set(meeting_ids('test'))
        self.assertEqual((len(dev), len(test)), (20, 20))
        self.assertFalse(dev & test)
        self.assertIn('ES2003a', dev)
        self.assertIn('TS3007d', test)

    def test_full_pcm_length_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / 'good.wav'
            with wave.open(str(good), 'wb') as audio:
                audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                audio.writeframes(b'\0\0' * 160)
            self.assertEqual(audio_info(good)['duration_seconds'], 0.01)
            bad = Path(tmp) / 'truncated.wav'
            bad.write_bytes(good.read_bytes()[:-2])
            with self.assertRaises(ValueError):
                audio_info(bad)

    def test_audio_mismatch_reported_without_clipping_human_boundaries(self):
        segments = [{'start': 9.0, 'end': 11.0}, {'start': 12.0, 'end': 13.0},
                    {'start': 0.0, 'end': 10.0}]
        self.assertEqual(out_of_audio_segments(segments, 10.0), 2)
        self.assertEqual(segments[0]['end'], 11.0)


if __name__ == '__main__':
    unittest.main()
