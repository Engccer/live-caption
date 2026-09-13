"""인공 헤더와 인공 TextGrid로 공개 자료 파서의 계약을 검증한다."""
from pathlib import Path
import struct
import tempfile
import unittest

from prepare_public import audio_info, textgrid_tier, prepare, prepared_audio_files


def wav_bytes(tag=3, frames=4):
    bits = 32 if tag == 3 else 16
    align = bits // 8
    fmt = struct.pack('<HHIIHH', tag, 1, 16000, 16000 * align, align, bits)
    # 홀수 길이의 부가 chunk와 padding 뒤의 fmt/data도 읽어야 한다.
    body = (b'WAVEJUNK' + struct.pack('<I', 1) + b'x\x00'
            + b'fmt ' + struct.pack('<I', len(fmt)) + fmt
            + b'data' + struct.pack('<I', frames * align) + b'\x00' * frames * align)
    return b'RIFF' + struct.pack('<I', len(body)) + body


def flac_bytes():
    packed = (16000 << 44) | (15 << 36) | 160
    block = b'\x00' * 10 + packed.to_bytes(8, 'big') + b'\x00' * 16
    return b'fLaC\x80\x00\x00\x22' + block


def grid_text(name='utt.ortho.', declared=2):
    return f'''File type = "ooTextFile"
Object class = "TextGrid"
xmin = 0
xmax = 2
tiers? <exists>
size = 1
item []:
    item [1]:
        class = "IntervalTier"
        name = "{name}"
        xmin = 0
        xmax = 2
        intervals: size = {declared}
        intervals [1]:
            xmin = 0
            xmax = 1
            text = "인공 ""인용"" 예시"
        intervals [2]:
            xmin = 1
            xmax = 2
            text = ""
'''


class IncompleteCollectionTests(unittest.TestCase):
    def test_seoul_pairing_count_excludes_interrupted_zip_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / 'extracted' / 'sound' / 'sound-flac.zip'
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b'archive-name-fixture')
            complete = base / 'unpacked' / 'sound-flac' / 'complete.flac'
            complete.parent.mkdir(parents=True)
            complete.write_bytes(flac_bytes())
            pending = base / 'unpacked' / '.extract-interrupted' / 'incomplete.flac'
            pending.parent.mkdir(parents=True)
            pending.write_bytes(b'truncated')
            self.assertEqual(prepared_audio_files(base, 'seoul'), [complete])

    def test_in_progress_extraction_cannot_publish_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / 'public' / 'pansori'
            pending = base / 'extracted' / '.extract-interrupted'
            pending.mkdir(parents=True)
            (pending / 'example.trans.txt').write_text('example 인공 정답\n')
            (pending / 'example.flac').write_bytes(flac_bytes())
            with self.assertRaisesRegex(ValueError, '수집을 먼저 완료'):
                prepare(root, 'pansori')
            self.assertFalse((base / 'ref').exists())
            self.assertFalse((base / 'inventory.json').exists())


class PreparePublicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='prepare-public-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def write(self, name, content):
        path = self.base / name
        path.write_bytes(content)
        return path

    def test_fleurs_float_wav_and_chunk_padding_are_supported(self):
        info = audio_info(self.write('float.wav', wav_bytes()))
        self.assertEqual(info, {'sample_rate': 16000, 'channels': 1, 'samples': 4,
                                'duration_seconds': 4 / 16000})

    def test_truncated_wav_is_rejected(self):
        with self.assertRaises(ValueError):
            audio_info(self.write('truncated.wav', wav_bytes()[:-2]))

    def test_wav_chunk_cannot_extend_beyond_declared_riff_boundary(self):
        raw = bytearray(wav_bytes())
        struct.pack_into('<I', raw, 4, len(raw) - 10)
        with self.assertRaises(ValueError):
            audio_info(self.write('riff-boundary.wav', raw))

    def test_empty_wav_is_rejected(self):
        with self.assertRaises(ValueError):
            audio_info(self.write('empty.wav', wav_bytes(frames=0)))

    def test_flac_streaminfo_reports_exact_sample_count(self):
        info = audio_info(self.write('header.flac', flac_bytes()))
        self.assertEqual(info['samples'], 160)
        self.assertEqual(info['sample_rate'], 16000)
        self.assertEqual(info['duration_seconds'], .01)

    def test_truncated_flac_streaminfo_is_rejected(self):
        with self.assertRaises(ValueError):
            audio_info(self.write('truncated.flac', flac_bytes()[:-1]))

    def test_missing_flac_metadata_header_reports_validation_error(self):
        with self.assertRaises(ValueError):
            audio_info(self.write('missing-header.flac', b'fLaC'))

    def test_utf16_and_utf8_textgrid_preserve_escaped_quotes(self):
        for encoding in ('utf-16', 'utf-8-sig'):
            with self.subTest(encoding=encoding):
                path = self.write('synthetic.TextGrid', grid_text().encode(encoding))
                self.assertEqual(textgrid_tier(path), [(0., 1., '인공 "인용" 예시'), (1., 2., '')])

    def test_missing_reference_tier_is_rejected(self):
        path = self.write('missing.TextGrid', grid_text(name='phoneme').encode())
        with self.assertRaises(ValueError):
            textgrid_tier(path)

    def test_interval_count_mismatch_is_rejected(self):
        path = self.write('count.TextGrid', grid_text(declared=3).encode())
        with self.assertRaises(ValueError):
            textgrid_tier(path)


if __name__ == '__main__':
    unittest.main()
