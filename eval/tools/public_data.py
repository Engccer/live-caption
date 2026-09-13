#!/usr/bin/env python3
"""공개 eval 자료의 저장 경계, 다운로드 영수증, 안전한 압축 해제."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
import stat
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[2]


def outside_repo(path):
    resolved = Path(path).expanduser().resolve()
    if resolved == REPO or REPO in resolved.parents:
        raise ValueError('eval 자료는 저장소 밖에 두어야 합니다')
    return resolved


def data_root(root=None):
    root = outside_repo(root or os.environ.get('LIVE_CAPTION_EVAL_DATA', '~/live-caption-eval'))
    root.mkdir(parents=True, exist_ok=True)
    return root


def digest(path, algorithm='sha256'):
    h = hashlib.new(algorithm)
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_new(path, content):
    """기존 자료와 같으면 유지하고, 다르면 덮어쓰지 않고 실패한다."""
    if Path(path).is_symlink():
        raise ValueError('출력 파일의 심볼릭 링크는 허용하지 않습니다')
    path = outside_repo(path)
    raw = content.encode('utf-8') if isinstance(content, str) else content
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise FileExistsError(f'기존 파일과 내용이 다릅니다: {path.name}')
        return
    with path.open('xb') as stream:
        stream.write(raw)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


def download(url, path, sha256=None, connections=1):
    if Path(path).is_symlink():
        raise ValueError('다운로드 파일의 심볼릭 링크는 허용하지 않습니다')
    path = outside_repo(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = path.with_name(path.name + '.receipt.json')
    if path.exists():
        if not receipt_path.exists():
            raise FileExistsError(f'영수증 없는 기존 파일: {path.name}')
        receipt = json.loads(receipt_path.read_text())
        actual = digest(path)
        if receipt['url'] != url or actual != receipt['sha256'] or (sha256 and actual != sha256):
            raise ValueError(f'기존 파일 검증 실패: {path.name}')
        return receipt
    if shutil.disk_usage(path.parent).free < 5 * 1024**3:
        raise OSError('남은 공간 5 GiB 미만: 다운로드 중단')
    if receipt_path.is_symlink():
        raise ValueError('다운로드 영수증의 심볼릭 링크는 허용하지 않습니다')
    # 단일 연결은 새 임시 폴더에서 처음부터 받는다. 검증 없는 .part 이어붙이기는 금지한다.
    if connections > 1:
        from range_download import fetch_ranges
        partial = path.with_name(path.name + '.ranged')
        transfer = fetch_ranges(url, partial, connections)
        return finish_download(url, path, partial, sha256, receipt_path, range_parts=transfer['parts'])
    else:
        with tempfile.TemporaryDirectory(prefix='.download-', dir=path.parent) as tmp:
            partial = Path(tmp) / 'payload'
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                            '--retry', '3', '--connect-timeout', '30', '--max-time', '3600',
                            '--output', str(partial), url], check=True)
            return finish_download(url, path, partial, sha256, receipt_path)


def finish_download(url, path, partial, sha256, receipt_path, range_parts=None):
    actual = digest(partial)
    if sha256 and actual != sha256:
        raise ValueError(f'배포자 SHA-256 불일치: {path.name}')
    receipt = {'url': url, 'bytes': partial.stat().st_size, 'sha256': actual,
               'publisher_sha256': sha256,
               'downloaded_at': datetime.now(timezone.utc).isoformat()}
    # 링크의 배타 생성으로 기존 완성 파일을 덮어쓰지 않는다.
    os.link(partial, path)
    partial.unlink()
    write_new(receipt_path, json_text(receipt))
    if range_parts is not None:
        # 확인한 조각과 자체 metadata만 정리한다. 알 수 없는 기존 파일은 보존한다.
        parts = partial.with_name(partial.name + '.parts')
        names = ['.lock', 'manifest.json'] + [f'{index:06d}.{suffix}'
                 for index in range(range_parts) for suffix in ('bin', 'sha256')]
        for name in names:
            (parts / name).unlink(missing_ok=True)
        if not any(parts.iterdir()):
            parts.rmdir()
    return receipt


_EXTRACTION_METADATA = {'.archive-sha256', '.archive-manifest.json'}


def _archive_entries(archive, kind):
    """압축 종류별 차이를 숨기되 파일·디렉터리 외 항목은 거부한다."""
    if kind == 'tar':
        with tarfile.open(archive) as stream:
            for member in stream:
                if not (member.isfile() or member.isdir()):
                    raise ValueError('압축 파일의 링크/특수 파일은 허용하지 않습니다')
                if member.isdir():
                    yield member.name, True, 0, None
                else:
                    with stream.extractfile(member) as source:
                        yield member.name, False, member.size, source
    else:
        with zipfile.ZipFile(archive) as stream:
            for member in stream.infolist():
                mode = member.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError('ZIP의 링크/특수 파일은 허용하지 않습니다')
                if member.is_dir():
                    yield member.filename, True, 0, None
                else:
                    with stream.open(member) as source:
                        yield member.filename, False, member.file_size, source


def _extraction_roots(include_roots):
    if include_roots is None:
        return None
    if isinstance(include_roots, str):
        raise ValueError('선택 경로는 최상위 이름의 목록이어야 합니다')
    roots = list(include_roots)
    if not roots or any(not isinstance(name, str) or not name or name in ('.', '..')
                        or '/' in name or '\\' in name or name in _EXTRACTION_METADATA
                        for name in roots):
        raise ValueError('잘못된 압축 해제 선택 경로')
    return sorted(set(roots))


def _archive_manifest(archive, kind, checksum, destination=None, include_roots=None):
    """원본의 파일별 해시를 계산한다. destination이 있을 때만 새 파일을 쓴다."""
    roots = _extraction_roots(include_roots)
    files, directories, selected = {}, set(), set()
    for name, is_directory, size, source in _archive_entries(archive, kind):
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name:
            raise ValueError('압축 파일 경로 탈출')
        key = relative.as_posix()
        if relative.parts and relative.parts[0] in _EXTRACTION_METADATA:
            raise ValueError('압축 파일이 검증 메타데이터 경로를 사용합니다')
        if key == '.':
            if is_directory:
                continue
            raise ValueError('잘못된 압축 파일 경로')
        if roots is not None:
            if relative.parts[0] not in roots:
                continue
            selected.add(relative.parts[0])
        directories.update(p.as_posix() for p in relative.parents if p != Path('.'))
        if is_directory:
            if key in files:
                raise ValueError('압축 파일의 경로가 중복됩니다')
            directories.add(key)
            if destination is not None:
                (destination / relative).mkdir(parents=True, exist_ok=True)
            continue
        if key in files or key in directories:
            raise ValueError('압축 파일의 경로가 중복됩니다')
        output = None
        try:
            if destination is not None:
                if shutil.disk_usage(destination).free < size + 2 * 1024**3:
                    raise OSError('압축 해제 공간 부족')
                dest = destination / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                output = dest.open('xb')
            hasher, actual_size = hashlib.sha256(), 0
            for block in iter(lambda: source.read(1024 * 1024), b''):
                hasher.update(block)
                actual_size += len(block)
                if output is not None:
                    output.write(block)
            if actual_size != size:
                raise ValueError('압축 파일의 선언 크기와 실제 크기가 다릅니다')
            files[key] = {'bytes': size, 'sha256': hasher.hexdigest()}
        finally:
            if output is not None:
                output.close()
    if set(files) & directories:
        raise ValueError('압축 파일과 디렉터리의 경로가 겹칩니다')
    if roots is not None and selected != set(roots):
        raise ValueError('선택한 최상위 경로가 원본 압축 파일에 없습니다')
    return {'schema_version': 1, 'archive_sha256': checksum,
            'include_roots': roots,
            'directories': sorted(directories), 'files': dict(sorted(files.items()))}


def _verify_extracted_tree(target, manifest):
    """추가·누락·변조·링크를 모두 검사하며 실제 자료는 수정하지 않는다."""
    files, directories = {}, set()
    for parent, child_dirs, child_files in os.walk(target, followlinks=False):
        for name in child_dirs + child_files:
            path = Path(parent) / name
            relative = path.relative_to(target).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError('해제 폴더에 링크 또는 특수 파일이 있습니다')
            if relative in _EXTRACTION_METADATA:
                if not stat.S_ISREG(mode):
                    raise ValueError('검증 메타데이터가 일반 파일이 아닙니다')
                continue
            if stat.S_ISDIR(mode):
                directories.add(relative)
            else:
                files[relative] = {'bytes': path.stat().st_size, 'sha256': digest(path)}
    if files != manifest['files'] or sorted(directories) != manifest['directories']:
        raise ValueError('해제 폴더의 파일 목록·크기·SHA-256이 원본과 다릅니다')


def _extract_verified(archive, target, kind, include_roots=None):
    roots = _extraction_roots(include_roots)
    if Path(target).expanduser().is_symlink():
        raise ValueError('해제 폴더는 심볼릭 링크일 수 없습니다')
    target = outside_repo(target)
    checksum = digest(archive)
    marker, manifest_path = (target / name for name in ('.archive-sha256', '.archive-manifest.json'))
    if target.exists():
        if marker.is_symlink() or not marker.is_file() or marker.read_text().strip() != checksum:
            raise FileExistsError('검증되지 않은 기존 해제 폴더입니다')
        if manifest_path.is_symlink():
            raise ValueError('검증 메타데이터는 심볼릭 링크일 수 없습니다')
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if manifest.get('schema_version') != 1 or manifest.get('archive_sha256') != checksum:
                raise ValueError('해제 manifest와 원본이 일치하지 않습니다')
            if manifest.get('include_roots') != roots:
                raise ValueError('기존 해제본과 선택 정책이 다릅니다')
            _verify_extracted_tree(target, manifest)
        else:
            # 이전 실행의 marker-only 자료는 원본과 전수 대조한 뒤 manifest만 추가한다.
            manifest = _archive_manifest(archive, kind, checksum, include_roots=roots)
            _verify_extracted_tree(target, manifest)
            write_new(manifest_path, json_text(manifest))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.extract-', dir=target.parent) as temporary:
        temporary = Path(temporary)
        manifest = _archive_manifest(archive, kind, checksum, temporary, include_roots=roots)
        write_new(temporary / '.archive-sha256', checksum + '\n')
        write_new(temporary / '.archive-manifest.json', json_text(manifest))
        os.rename(temporary, target)


def extract_tar(archive, target, include_roots=None):
    """TAR 전체 또는 지정 최상위 경로만 해제하고 선택 정책과 무결성을 확인한다."""
    _extract_verified(archive, target, 'tar', include_roots)


def extract_zip(archive, target):
    """ZIP CRC와 경로를 검사하고 재사용 전 실제 해제본을 전수 검증한다."""
    _extract_verified(archive, target, 'zip')
