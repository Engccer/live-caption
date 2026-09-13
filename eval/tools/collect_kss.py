#!/usr/bin/env python3
"""KSS 원본과 보조 ASR 자료를 저장소 밖에 보존한다. 발화는 출력하지 않는다."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import unicodedata
import wave
import zipfile

from public_data import data_root, digest, download, extract_zip, json_text, write_new

SOURCE = 'https://www.kaggle.com/datasets/bryanpark/korean-single-speaker-speech-dataset'
API = 'https://www.kaggle.com/api/v1/datasets'
SLUG = 'bryanpark/korean-single-speaker-speech-dataset'
VERSION = 4


def collect(root, extract=False):
    base = data_root(root) / 'public' / 'kss'
    raw = base / 'raw'
    metadata = raw / 'kaggle-metadata.json'
    download(f'{API}/view/{SLUG}', metadata)
    archive = raw / 'kss-v4.zip'
    receipt = download(f'{API}/download/{SLUG}?datasetVersionNumber={VERSION}', archive)
    print(f'KSS 원본: {receipt["bytes"]:,} bytes, SHA-256 검증 완료', flush=True)
    target = base / 'extracted' / 'kss-v4'
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        expanded_bytes = sum(m.file_size for m in members)
        bad = zf.testzip()
        if bad is not None:
            raise ValueError('KSS ZIP CRC 검사 실패')
        print(f'KSS CRC: {len(members):,}개 파일 통과', flush=True)
        if extract:
            if not target.exists() and shutil.disk_usage(base).free < expanded_bytes + 10 * 1024**3:
                raise OSError('압축 해제 후 여유 공간 10 GiB를 확보할 수 없습니다')
            extract_zip(archive, target)
        transcripts = [m.filename for m in members if PurePosixPath(m.filename).name == 'transcript.v.1.4.txt']
        if len(transcripts) != 1:
            raise ValueError('KSS v1.4 전사 파일이 정확히 하나여야 합니다')
        lines = zf.read(transcripts[0]).decode('utf-8-sig').splitlines()
        audio_members = {m.filename for m in members if m.filename.lower().endswith('.wav')}
        rows, used, deviations = [], set(), []
        formats = Counter()
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            fields = line.split('|')
            if len(fields) != 6:
                raise ValueError(f'KSS 전사 {number}행 필드 수 오류')
            relative = PurePosixPath(fields[0])
            if relative.is_absolute() or '..' in relative.parts or '\\' in fields[0]:
                raise ValueError(f'KSS 전사 {number}행 경로 오류')
            choices = [v for v in (str(relative), f'kss/{relative}') if v in audio_members]
            if len(choices) != 1 or choices[0] in used:
                raise ValueError(f'KSS 전사 {number}행 음성 대응 오류')
            member = choices[0]
            used.add(member)
            with zf.open(member) as stream, wave.open(stream, 'rb') as wav:
                duration = wav.getnframes() / wav.getframerate()
                spec = (wav.getnchannels(), wav.getframerate(), wav.getsampwidth())
                if spec[0] not in (1, 2) or spec[1] != 44100 or spec[2] != 2:
                    raise ValueError(f'KSS 전사 {number}행 음성 규격 오류')
                formats[spec] += 1
            if abs(duration - float(fields[4])) > .11:
                deviations.append(number)
            text = unicodedata.normalize('NFC', fields[2]).strip()
            if not text:
                raise ValueError(f'KSS 전사 {number}행 빈 정답')
            cluster_text = ' '.join(text.split())
            rows.append({'id': f'kss:{relative.with_suffix("")}', 'dataset': 'kss',
                         'split': 'all', 'cluster': 'kss:' + hashlib.sha256(cluster_text.encode()).hexdigest(),
                         'text': text, 'audio': str(Path('extracted/kss-v4') / member),
                         'duration_seconds': duration, 'eligible_metrics': ['cer', 'wer'],
                         'evaluation_ready': False})
        if used != audio_members:
            raise ValueError('KSS 전사에 대응하지 않는 음성 파일이 있습니다')
    summary = {'dataset': 'kss', 'version': VERSION, 'source': SOURCE,
               'license': json.loads(metadata.read_text())['licenseName'],
               'archive_bytes': receipt['bytes'], 'archive_sha256': receipt['sha256'],
               'expanded_bytes': expanded_bytes, 'crc_verified_files': len(members),
               'audio_files': len(audio_members), 'reference_rows': len(rows),
               'unique_text_clusters': len({r['cluster'] for r in rows}),
               'duration_seconds': sum(r['duration_seconds'] for r in rows),
               'duration_checked_files': len(rows), 'duration_metadata_deviations_over_110ms': len(deviations),
               'audio_formats': [{'channels': c, 'sample_rate_hz': sr, 'sample_width_bytes': sw,
                                  'files': count} for (c, sr, sw), count in sorted(formats.items())],
               'speakers': 1,
               'evaluation_ready': False, 'use': '단일 성우 낭독 보조 자료, 독립 ASR test 아님'}
    if extract:
        content = ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in rows)
        refs = base / 'refs.jsonl'
        write_new(refs, content)
        summary['refs_sha256'] = digest(refs)
        write_new(base / 'reference-summary.json', json_text(summary))
    else:
        write_new(base / 'inventory-summary.json', json_text(summary))
    print(json_text({k: v for k, v in summary.items() if k not in ('source', 'use')}), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--extract', action='store_true')
    args = parser.parse_args()
    collect(args.root, args.extract)


if __name__ == '__main__':
    main()
