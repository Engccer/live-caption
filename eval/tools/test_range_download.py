"""외부 통신 없이 로컬 HTTP 서버로 Range 검증·재개·덮어쓰기 방지를 확인한다."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from range_download import fetch_ranges, RangeError
from public_data import REPO


PAYLOAD = b'0123456789abcdef' * 19


class RangeDownloadTests(unittest.TestCase):
    def setUp(self):
        self.mode = 'normal'
        self.etag = '"version-one"'
        self.requests = []
        case = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                start, end = map(int, self.headers['Range'][6:].split('-'))
                case.requests.append((start, end))
                if case.mode == 'ignore':
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(PAYLOAD)))
                    self.end_headers()
                    self.wfile.write(PAYLOAD)
                    return
                body = PAYLOAD[start:end + 1]
                self.send_response(206)
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(PAYLOAD)}')
                self.send_header('ETag', case.etag)
                if case.mode == 'badlength' and end > 0:
                    body = body[:-1]
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/fixture'
        self.tmp = tempfile.TemporaryDirectory()
        self.output = Path(self.tmp.name) / 'archive.bin'
        self.chunk_patch = patch('range_download.CHUNK_BYTES', 64)
        self.chunk_patch.start()

    def tearDown(self):
        self.chunk_patch.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def test_normal_parallel_download_and_digest(self):
        result = fetch_ranges(self.url, self.output)
        self.assertEqual(self.output.read_bytes(), PAYLOAD)
        self.assertEqual(result['bytes'], len(PAYLOAD))
        self.assertEqual(result['parts'], 5)
        self.assertEqual(len(result['sha256']), 64)

    def test_range_ignored_fails_without_final_file(self):
        self.mode = 'ignore'
        with self.assertRaises(RangeError):
            fetch_ranges(self.url, self.output)
        self.assertFalse(self.output.exists())

    def test_wrong_response_length_fails_without_final_file(self):
        self.mode = 'badlength'
        with self.assertRaises(RangeError):
            fetch_ranges(self.url, self.output)
        self.assertFalse(self.output.exists())

    def test_restart_reuses_verified_parts(self):
        with patch('range_download.os.link', side_effect=OSError('일시 중단')):
            with self.assertRaises(OSError):
                fetch_ranges(self.url, self.output)
        self.requests.clear()
        fetch_ranges(self.url, self.output)
        self.assertEqual(self.requests, [(0, 0)])
        self.assertEqual(self.output.read_bytes(), PAYLOAD)

    def test_existing_final_is_never_overwritten(self):
        self.output.write_bytes(b'original')
        with self.assertRaises(RangeError):
            fetch_ranges(self.url, self.output)
        self.assertEqual(self.output.read_bytes(), b'original')
        self.assertEqual(self.requests, [])

    def test_changed_source_rejects_existing_parts(self):
        with patch('range_download.os.link', side_effect=OSError('일시 중단')):
            with self.assertRaises(OSError):
                fetch_ranges(self.url, self.output)
        self.etag = '"version-two"'
        with self.assertRaises(RangeError):
            fetch_ranges(self.url, self.output)
        self.assertFalse(self.output.exists())

    def test_corrupt_same_size_part_rejected(self):
        with patch('range_download.os.link', side_effect=OSError('일시 중단')):
            with self.assertRaises(OSError):
                fetch_ranges(self.url, self.output)
        chunk = self.output.with_name(self.output.name + '.parts') / '000000.bin'
        chunk.write_bytes(b'x' * 64)
        with self.assertRaises(RangeError):
            fetch_ranges(self.url, self.output)
        self.assertFalse(self.output.exists())

    def test_repository_output_is_rejected_before_network_or_write(self):
        output = REPO / 'range-download-forbidden-test.bin'
        self.assertFalse(output.exists())
        with self.assertRaises(RangeError):
            fetch_ranges(self.url, output)
        self.assertFalse(output.exists())
        self.assertFalse(output.with_name(output.name + '.parts').exists())
        self.assertEqual(self.requests, [])

    def test_parts_directory_symlink_is_rejected(self):
        target = Path(self.tmp.name) / 'unrelated'
        target.mkdir()
        parts = self.output.with_name(self.output.name + '.parts')
        parts.symlink_to(target, target_is_directory=True)
        with self.assertRaises(RangeError):
            fetch_ranges(self.url, self.output)
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(self.requests, [])

    def test_internal_symlinks_preserve_their_targets(self):
        for index, name in enumerate(('.lock', 'manifest.json', '000000.tmp',
                                      '000000.bin', '000000.sha256', 'assembled.tmp')):
            with self.subTest(name=name):
                output = Path(self.tmp.name) / f'output-{index}.bin'
                parts = output.with_name(output.name + '.parts')
                parts.mkdir()
                target = Path(self.tmp.name) / f'unrelated-{index}.txt'
                target.write_bytes(b'preserve me')
                (parts / name).symlink_to(target)
                with self.assertRaises(RangeError):
                    fetch_ranges(self.url, output)
                self.assertEqual(target.read_bytes(), b'preserve me')
                self.assertFalse(output.exists())
        self.assertEqual(self.requests, [])

    def test_dangling_internal_symlink_is_rejected_without_creating_target(self):
        parts = self.output.with_name(self.output.name + '.parts')
        parts.mkdir()
        target = Path(self.tmp.name) / 'must-not-be-created'
        (parts / 'assembled.tmp').symlink_to(target)
        with self.assertRaises(RangeError):
            fetch_ranges(self.url, self.output)
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
