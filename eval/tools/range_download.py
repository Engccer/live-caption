#!/usr/bin/env python3
"""HTTP Range 병렬 다운로드. 검증된 조각을 보존하며 완성 파일은 덮어쓰지 않는다."""

from concurrent.futures import ThreadPoolExecutor
import argparse
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import stat
import sys
import urllib.error
import urllib.request

from public_data import outside_repo

CHUNK_BYTES = 32 * 1024 * 1024
READ_BYTES = 1024 * 1024


class RangeError(RuntimeError):
    """원문 URL이나 서버 응답 본문을 포함하지 않는 다운로드 오류."""


def _reject_symlink(path):
    if path.is_symlink():
        raise RangeError('다운로드 경로의 심볼릭 링크는 허용하지 않습니다')


def _open_regular(path, mode):
    """열기 시점에도 링크를 거부하고 일반 파일 확인 뒤에만 내용을 쓴다."""
    _reject_symlink(path)
    flags = os.O_NOFOLLOW
    if mode == 'rb':
        flags |= os.O_RDONLY
    elif mode == 'xb':
        flags |= os.O_WRONLY | os.O_CREAT | os.O_EXCL
    else:
        flags |= os.O_RDWR | os.O_CREAT
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (mode != 'rb' and info.st_nlink != 1):
            raise RangeError('다운로드 내부 경로는 독립된 일반 파일이어야 합니다')
        if mode == 'wb':
            os.ftruncate(fd, 0)
        return os.fdopen(fd, mode)
    except BaseException:
        os.close(fd)
        raise


def _read_text(path):
    with _open_regular(path, 'rb') as stream:
        return stream.read().decode('utf-8')


def _request(url, start, end, validator=None):
    headers = {'Range': f'bytes={start}-{end}', 'Accept-Encoding': 'identity'}
    if validator:
        headers['If-Range'] = validator[1]
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90)


def _headers(response, start, end, total=None):
    if response.status != 206:
        raise RangeError('서버가 HTTP Range 요청을 지원하지 않거나 원본이 변경되었습니다')
    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
    if not match:
        raise RangeError('Content-Range 응답이 잘못되었습니다')
    actual_start, actual_end, actual_total = map(int, match.groups())
    if (actual_start, actual_end) != (start, end) or actual_total <= end:
        raise RangeError('요청 범위와 응답 범위가 다릅니다')
    if total is not None and actual_total != total:
        raise RangeError('다운로드 중 원본 크기가 변경되었습니다')
    length = response.headers.get('Content-Length')
    if length is not None and length != str(end - start + 1):
        raise RangeError('Content-Length와 요청 크기가 다릅니다')
    encoding = response.headers.get('Content-Encoding', 'identity')
    if encoding.lower() != 'identity':
        raise RangeError('압축된 범위 응답은 허용하지 않습니다')
    return actual_total


def _probe(url):
    with _request(url, 0, 0) as response:
        total = _headers(response, 0, 0)
        if len(response.read(2)) != 1:
            raise RangeError('크기 확인 응답 길이가 잘못되었습니다')
        etag = response.headers.get('ETag')
        modified = response.headers.get('Last-Modified')
        validator = ['ETag', etag] if etag and not etag.startswith('W/') else (
            ['Last-Modified', modified] if modified else None)
        return total, validator


def _sha256(path):
    digest = hashlib.sha256()
    with _open_regular(path, 'rb') as stream:
        for block in iter(lambda: stream.read(READ_BYTES), b''):
            digest.update(block)
    return digest.hexdigest()


def _fetch_part(url, parts, index, start, end, total, validator):
    chunk = parts / f'{index:06d}.bin'
    receipt = parts / f'{index:06d}.sha256'
    for candidate in (chunk, receipt, parts / f'{index:06d}.tmp'):
        _reject_symlink(candidate)
    size = end - start + 1
    if chunk.exists():
        if not receipt.is_file() or chunk.stat().st_size != size or _sha256(chunk) != _read_text(receipt).strip():
            raise RangeError('기존 조각의 크기 또는 SHA-256 검증에 실패했습니다')
        return chunk
    temporary = parts / f'{index:06d}.tmp'
    # 미완성 조각만 다시 받는다. 검증된 .bin과 영수증은 유지한다.
    for attempt in range(3):
        try:
            with _request(url, start, end, validator) as response:
                _headers(response, start, end, total)
                if validator and response.headers.get(validator[0]) != validator[1]:
                    raise RangeError('다운로드 중 원본 식별자가 변경되었습니다')
                received = 0
                digest = hashlib.sha256()
                with _open_regular(temporary, 'wb') as stream:
                    while True:
                        block = response.read(min(READ_BYTES, size - received + 1))
                        if not block:
                            break
                        received += len(block)
                        if received > size:
                            raise RangeError('범위 응답이 요청 크기를 초과했습니다')
                        digest.update(block)
                        stream.write(block)
                    if received != size:
                        raise RangeError('범위 응답이 요청 크기보다 짧습니다')
                    stream.flush()
                    os.fsync(stream.fileno())
            # 영수증을 먼저 남겨 중단 직후 완성 조각이 검증 불능이 되는 것을 막는다.
            with _open_regular(receipt, 'wb') as stream:
                stream.write((digest.hexdigest() + '\n').encode('ascii'))
            _reject_symlink(chunk)
            os.replace(temporary, chunk)
            return chunk
        except (OSError, urllib.error.URLError, http.client.HTTPException, RangeError) as exc:
            if isinstance(exc, RangeError) or attempt == 2:
                if isinstance(exc, RangeError):
                    raise
                raise RangeError('범위 다운로드 네트워크 오류가 반복되었습니다') from None


def fetch_ranges(url, path, connections=8):
    """새 path를 생성한다. 실패 뒤 같은 인자로 실행하면 *.parts를 검증해 재사용한다.

    원본 식별자를 제공하지 않는 서버의 조각은 재실행에서 재사용하지 않는다.
    이 경우 *.parts를 따로 보존하고 새 출력 경로로 다시 실행해야 한다.
    """
    if type(connections) is not int or not 1 <= connections <= 32:
        raise RangeError('connections는 1~32 정수여야 합니다')
    path = Path(path).expanduser()
    _reject_symlink(path)
    try:
        path = outside_repo(path)
    except ValueError:
        raise RangeError('다운로드 자료는 저장소 밖에 두어야 합니다') from None
    if path.exists() or path.is_symlink():
        raise RangeError('최종 경로에 기존 파일이 있어 덮어쓰지 않습니다')
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = path.with_name(path.name + '.parts')
    _reject_symlink(parts)
    parts.mkdir(exist_ok=True)
    for existing in parts.iterdir():
        _reject_symlink(existing)
    with _open_regular(parts / '.lock', 'ab') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RangeError('같은 출력 경로의 다운로드가 이미 실행 중입니다') from None
        if path.exists() or path.is_symlink():
            raise RangeError('최종 경로에 기존 파일이 있어 덮어쓰지 않습니다')
        try:
            total, validator = _probe(url)
        except (OSError, urllib.error.URLError, http.client.HTTPException):
            raise RangeError('HTTP Range 크기 확인에 실패했습니다') from None
        metadata = {'url': url, 'bytes': total, 'validator': validator, 'chunk_bytes': CHUNK_BYTES}
        manifest = parts / 'manifest.json'
        if manifest.exists():
            try:
                previous = json.loads(_read_text(manifest))
            except (OSError, ValueError):
                raise RangeError('기존 다운로드 명세를 읽을 수 없습니다') from None
            if previous != metadata:
                raise RangeError('기존 조각과 URL, 크기 또는 원본 식별자가 다릅니다')
            if validator is None:
                raise RangeError('원본 식별자가 없는 서버의 조각은 재실행에서 재사용할 수 없습니다')
        else:
            with _open_regular(manifest, 'xb') as stream:
                stream.write(json.dumps(metadata, ensure_ascii=False).encode('utf-8'))
        jobs = [(index, start, min(start + CHUNK_BYTES, total) - 1)
                for index, start in enumerate(range(0, total, CHUNK_BYTES))]
        with ThreadPoolExecutor(max_workers=connections) as executor:
            futures = [executor.submit(_fetch_part, url, parts, index, start, end, total, validator)
                       for index, start, end in jobs]
            chunks = [future.result() for future in futures]
        assembled = parts / 'assembled.tmp'
        with _open_regular(assembled, 'wb') as output:
            for chunk in chunks:
                with _open_regular(chunk, 'rb') as source:
                    for block in iter(lambda: source.read(READ_BYTES), b''):
                        output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if assembled.stat().st_size != total:
            raise RangeError('합친 파일의 크기가 원본 크기와 다릅니다')
        try:
            os.link(assembled, path)
        except FileExistsError:
            raise RangeError('최종 경로에 기존 파일이 있어 덮어쓰지 않습니다') from None
        assembled.unlink()
        return {'bytes': total, 'parts': len(chunks), 'validator': validator,
                'sha256': _sha256(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('path')
    parser.add_argument('--connections', type=int, default=8)
    args = parser.parse_args()
    try:
        result = fetch_ranges(args.url, args.path, args.connections)
    except RangeError as exc:
        print(f'범위 다운로드 실패: {exc}', file=sys.stderr)
        return 2
    except OSError:
        print('범위 다운로드 파일 작업 실패. 기존 파일과 검증된 조각을 보존했습니다.', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
