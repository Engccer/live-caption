"""중단된 예전 다운로드와 임시 경로가 새 원본을 오염시키지 않는다."""
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from public_data import download, digest, finish_download


class DownloadRegressionTests(unittest.TestCase):
    def test_old_partial_symlink_is_never_used(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'corpus.bin'
            old = root / 'existing.bin'
            old.write_bytes(b'old-source')
            target.with_name(target.name + '.part').symlink_to(old)

            def curl(args, **kwargs):
                self.assertNotIn('--continue-at', args)
                output = Path(args[args.index('--output') + 1])
                self.assertNotEqual(output, target.with_name(target.name + '.part'))
                output.write_bytes(b'new-source')

            with patch('public_data.subprocess.run', side_effect=curl):
                result = download('https://example.invalid/current', target)
            self.assertEqual(target.read_bytes(), b'new-source')
            self.assertEqual(old.read_bytes(), b'old-source')
            self.assertEqual(result['sha256'], digest(target))

    def test_wrong_publisher_digest_never_promotes_download(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'corpus.bin'

            def curl(args, **kwargs):
                Path(args[args.index('--output') + 1]).write_bytes(b'wrong-source')

            with patch('public_data.subprocess.run', side_effect=curl):
                with self.assertRaises(ValueError):
                    download('https://example.invalid/current', target, sha256='0' * 64)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name(target.name + '.receipt.json').exists())

    def test_network_failure_never_creates_complete_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'corpus.bin'
            with patch('public_data.subprocess.run', side_effect=subprocess.CalledProcessError(22, 'curl')):
                with self.assertRaises(subprocess.CalledProcessError):
                    download('https://example.invalid/current', target)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_final_symlink_is_rejected_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'corpus.bin'
            target.symlink_to(root / 'another.bin')
            with patch('public_data.subprocess.run') as run:
                with self.assertRaises(ValueError):
                    download('https://example.invalid/current', target)
                run.assert_not_called()

    def test_range_cleanup_preserves_unknown_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'corpus.bin'
            partial = root / 'corpus.bin.ranged'
            partial.write_bytes(b'new-source')
            parts = root / 'corpus.bin.ranged.parts'
            parts.mkdir()
            for name in ['.lock', 'manifest.json', '000000.bin', '000000.sha256']:
                (parts / name).write_bytes(b'owned')
            note = parts / 'keep-existing-note.txt'
            note.write_bytes(b'keep me')
            finish_download('https://example.invalid/current', target, partial, None,
                            root / 'corpus.bin.receipt.json', range_parts=1)
            self.assertEqual(note.read_bytes(), b'keep me')
            self.assertEqual(list(parts.iterdir()), [note])
            self.assertEqual(target.read_bytes(), b'new-source')


if __name__ == '__main__':
    unittest.main()
