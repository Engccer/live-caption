"""실자료 없이 저장 경계와 압축 해제의 실패 안전성을 검증한다."""
import io
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import public_data as subject


class PublicDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='public-data-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()

    def archive(self, kind, name='safe.txt', symlink=False):
        archive = self.base / f'fixture.{kind}'
        if kind == 'tar':
            with tarfile.open(archive, 'w') as stream:
                member = tarfile.TarInfo(name)
                if symlink:
                    member.type = tarfile.SYMTYPE
                    member.linkname = '../escaped.txt'
                    stream.addfile(member)
                else:
                    member.size = len(b'fixture')
                    stream.addfile(member, io.BytesIO(b'fixture'))
        else:
            with zipfile.ZipFile(archive, 'w') as stream:
                member = zipfile.ZipInfo(name)
                if symlink:
                    member.create_system = 3
                    member.external_attr = (stat.S_IFLNK | 0o777) << 16
                stream.writestr(member, b'../escaped.txt' if symlink else b'fixture')
        return archive

    def test_repository_and_descendant_roots_are_rejected_without_writes(self):
        for root in (subject.REPO, subject.REPO / 'never-create-eval-fixture'):
            with self.subTest(root=root), self.assertRaises(ValueError):
                subject.data_root(root)
        self.assertFalse((subject.REPO / 'never-create-eval-fixture').exists())

    def test_symlink_into_repository_is_rejected(self):
        link = self.base / 'linked-repository'
        link.symlink_to(subject.REPO, target_is_directory=True)
        with self.assertRaises(ValueError):
            subject.data_root(link / 'never-create-eval-fixture')

    def test_external_root_is_created(self):
        root = self.base / 'accepted'
        self.assertEqual(subject.data_root(root), root)
        self.assertTrue(root.is_dir())

    def test_tar_and_zip_cannot_escape_or_overwrite_external_file(self):
        sentinel = self.base / 'escaped.txt'
        sentinel.write_bytes(b'keep')
        for kind in ('tar', 'zip'):
            for member in ('../escaped.txt', str(sentinel)):
                with self.subTest(kind=kind, member=member):
                    archive = self.archive(kind, member)
                    target = self.base / f'extracted-{kind}'
                    with self.assertRaises(ValueError):
                        getattr(subject, f'extract_{kind}')(archive, target)
                    self.assertFalse(target.exists())
                    self.assertEqual(sentinel.read_bytes(), b'keep')

    def test_tar_and_zip_reject_symlinks_without_partial_output(self):
        for kind in ('tar', 'zip'):
            with self.subTest(kind=kind):
                archive = self.archive(kind, symlink=True)
                target = self.base / f'links-{kind}'
                with self.assertRaises(ValueError):
                    getattr(subject, f'extract_{kind}')(archive, target)
                self.assertFalse(target.exists())

    def test_existing_extraction_directory_is_not_overwritten(self):
        for kind in ('tar', 'zip'):
            with self.subTest(kind=kind):
                target = self.base / f'existing-{kind}'
                target.mkdir()
                sentinel = target / 'safe.txt'
                sentinel.write_bytes(b'keep')
                with self.assertRaises(FileExistsError):
                    getattr(subject, f'extract_{kind}')(self.archive(kind), target)
                self.assertEqual(sentinel.read_bytes(), b'keep')

    def test_valid_archives_extract_and_repeat_without_changing_files(self):
        for kind in ('tar', 'zip'):
            with self.subTest(kind=kind):
                archive = self.archive(kind, 'nested/safe.txt')
                target = self.base / f'valid-{kind}'
                extract = getattr(subject, f'extract_{kind}')
                extract(archive, target)
                stored = target / 'nested/safe.txt'
                before = stored.stat().st_mtime_ns
                extract(archive, target)
                self.assertEqual(stored.read_bytes(), b'fixture')
                self.assertEqual(stored.stat().st_mtime_ns, before)

    def test_reuse_rejects_missing_modified_and_extra_extracted_files(self):
        for kind in ('tar', 'zip'):
            for alteration in ('missing', 'modified', 'extra', 'extra-directory', 'symlink'):
                with self.subTest(kind=kind, alteration=alteration):
                    archive = self.archive(kind, 'nested/safe.txt')
                    target = self.base / f'changed-{kind}-{alteration}'
                    extract = getattr(subject, f'extract_{kind}')
                    extract(archive, target)
                    stored = target / 'nested/safe.txt'
                    if alteration == 'missing':
                        stored.unlink()
                    elif alteration == 'modified':
                        stored.write_bytes(b'changed')  # 원본과 같은 길이의 변조도 잡아야 한다.
                    elif alteration == 'extra':
                        (target / 'extra.txt').write_bytes(b'keep')
                    elif alteration == 'extra-directory':
                        (target / 'unexpected-directory').mkdir()
                    else:
                        stored.unlink()
                        outside = self.base / f'symlink-content-{kind}'
                        outside.write_bytes(b'fixture')
                        stored.symlink_to(outside)
                    manifest_before = (target / '.archive-manifest.json').read_bytes()
                    with self.assertRaises(ValueError):
                        extract(archive, target)
                    self.assertEqual((target / '.archive-manifest.json').read_bytes(), manifest_before)
                    if alteration == 'missing':
                        self.assertFalse(stored.exists())
                    elif alteration == 'modified':
                        self.assertEqual(stored.read_bytes(), b'changed')
                    elif alteration == 'symlink':
                        self.assertTrue(stored.is_symlink())

    def test_marker_only_legacy_migration_adds_manifest_without_replacing_data(self):
        for kind in ('tar', 'zip'):
            with self.subTest(kind=kind):
                archive = self.archive(kind, 'nested/safe.txt')
                target = self.base / f'legacy-{kind}'
                (target / 'nested').mkdir(parents=True)
                stored = target / 'nested/safe.txt'
                stored.write_bytes(b'fixture')
                (target / '.archive-sha256').write_text(subject.digest(archive) + '\n')
                before = (stored.stat().st_ino, stored.stat().st_mtime_ns)
                getattr(subject, f'extract_{kind}')(archive, target)
                self.assertEqual((stored.stat().st_ino, stored.stat().st_mtime_ns), before)
                manifest = json.loads((target / '.archive-manifest.json').read_text())
                self.assertEqual(manifest['files']['nested/safe.txt'],
                                 {'bytes': 7, 'sha256': subject.digest(stored)})
                self.assertEqual(manifest['directories'], ['nested'])

    def test_marker_only_migration_rejects_changed_tree_without_creating_manifest(self):
        for kind in ('tar', 'zip'):
            for alteration in ('missing', 'modified', 'extra'):
                with self.subTest(kind=kind, alteration=alteration):
                    archive = self.archive(kind)
                    target = self.base / f'legacy-bad-{kind}-{alteration}'
                    target.mkdir()
                    if alteration != 'missing':
                        (target / 'safe.txt').write_bytes(b'changed' if alteration == 'modified' else b'fixture')
                    if alteration == 'extra':
                        (target / 'extra.txt').write_bytes(b'keep')
                    (target / '.archive-sha256').write_text(subject.digest(archive) + '\n')
                    with self.assertRaises(ValueError):
                        getattr(subject, f'extract_{kind}')(archive, target)
                    self.assertFalse((target / '.archive-manifest.json').exists())

    def test_reuse_rejects_symlink_to_extracted_root(self):
        archive = self.archive('zip')
        target = self.base / 'actual-root'
        subject.extract_zip(archive, target)
        link = self.base / 'linked-root'
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            subject.extract_zip(archive, link)
        self.assertTrue(link.is_symlink())

    def selection_archive(self):
        archive = self.base / 'selected.tar'
        entries = {'train_data_01/sample.bin': b'train',
                   'test_data_01/sample.bin': b'test', 'AUDIO_INFO': b'info',
                   'language-model/large.txt': b'x' * 1024 * 1024}
        with tarfile.open(archive, 'w') as stream:
            for name, content in entries.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                stream.addfile(member, io.BytesIO(content))
        return archive

    def test_tar_selection_skips_other_roots_and_verifies_selected_files(self):
        archive = self.selection_archive()
        target = self.base / 'selected'
        roots = ('test_data_01', 'train_data_01', 'AUDIO_INFO')
        subject.extract_tar(archive, target, include_roots=roots)
        manifest = json.loads((target / '.archive-manifest.json').read_text())
        self.assertEqual(manifest['include_roots'], sorted(roots))
        self.assertEqual(manifest['archive_sha256'], subject.digest(archive))
        self.assertEqual(set(manifest['files']), {'test_data_01/sample.bin',
                                                 'train_data_01/sample.bin', 'AUDIO_INFO'})
        self.assertFalse((target / 'language-model').exists())
        subject.extract_tar(archive, target, include_roots=tuple(reversed(roots)))
        (target / 'test_data_01/sample.bin').write_bytes(b'edit')
        with self.assertRaises(ValueError):
            subject.extract_tar(archive, target, include_roots=roots)
        self.assertEqual((target / 'test_data_01/sample.bin').read_bytes(), b'edit')

    def test_tar_selection_change_is_rejected_without_changing_existing_data(self):
        archive = self.selection_archive()
        target = self.base / 'selection-policy'
        roots = ('test_data_01',)
        subject.extract_tar(archive, target, include_roots=roots)
        before = (target / '.archive-manifest.json').read_bytes()
        for changed in (None, ('train_data_01',), ('test_data_01', 'AUDIO_INFO')):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                subject.extract_tar(archive, target, include_roots=changed)
        self.assertEqual((target / '.archive-manifest.json').read_bytes(), before)
        self.assertFalse((target / 'train_data_01').exists())

    def test_marker_only_selected_tree_migrates_from_full_archive(self):
        archive = self.selection_archive()
        target = self.base / 'legacy-selection'
        (target / 'test_data_01').mkdir(parents=True)
        stored = target / 'test_data_01/sample.bin'
        stored.write_bytes(b'test')
        (target / '.archive-sha256').write_text(subject.digest(archive) + '\n')
        before = (stored.stat().st_ino, stored.stat().st_mtime_ns)
        subject.extract_tar(archive, target, include_roots=('test_data_01',))
        self.assertEqual((stored.stat().st_ino, stored.stat().st_mtime_ns), before)
        manifest = json.loads((target / '.archive-manifest.json').read_text())
        self.assertEqual(manifest['include_roots'], ['test_data_01'])

    def test_tar_invalid_or_absent_selection_does_not_publish_target(self):
        archive = self.selection_archive()
        for roots in ((), '../escape', ('../escape',), ('unknown',)):
            with self.subTest(roots=roots), self.assertRaises(ValueError):
                subject.extract_tar(archive, self.base / 'invalid-selection', include_roots=roots)
            self.assertFalse((self.base / 'invalid-selection').exists())

    def test_download_rejects_existing_checksum_mismatch_without_network(self):
        path = self.base / 'download.bin'
        path.write_bytes(b'keep')
        receipt = {'url': 'https://example.invalid/source', 'sha256': '0' * 64}
        path.with_name(path.name + '.receipt.json').write_text(json.dumps(receipt))
        with patch.object(subject.subprocess, 'run') as network:
            with self.assertRaises(ValueError):
                subject.download(receipt['url'], path)
            network.assert_not_called()
        self.assertEqual(path.read_bytes(), b'keep')

    def test_publisher_checksum_is_checked_even_with_matching_receipt(self):
        path = self.base / 'download.bin'
        path.write_bytes(b'keep')
        receipt = {'url': 'https://example.invalid/source', 'sha256': subject.digest(path)}
        path.with_name(path.name + '.receipt.json').write_text(json.dumps(receipt))
        with self.assertRaises(ValueError):
            subject.download(receipt['url'], path, sha256='0' * 64)

    def test_write_new_keeps_matching_file_and_rejects_replacement(self):
        path = self.base / 'reference.json'
        subject.write_new(path, 'synthetic')
        subject.write_new(path, 'synthetic')
        with self.assertRaises(FileExistsError):
            subject.write_new(path, 'different')
        self.assertEqual(path.read_text(), 'synthetic')


if __name__ == '__main__':
    unittest.main()
