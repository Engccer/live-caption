#!/usr/bin/env python3
"""공개 한국어 원본을 발화 내용이 외부로 출력되지 않는 eval JSONL로 변환한다."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import struct
import subprocess
from public_data import data_root, digest, extract_tar, extract_zip, json_text, write_new
from collect_public import ASSETS


def payload_roots(base, dataset):
    return [base / 'extracted' / name.removesuffix('.tar.gz').removesuffix('.tgz')
            for _, name, _ in ASSETS[dataset] if name.endswith(('.tar.gz', '.tgz'))]


def seoul_archives(base):
    return sorted(p for folder in payload_roots(base, 'seoul') for p in folder.rglob('*.zip'))


def prepared_audio_files(base, dataset):
    roots = ([base / 'unpacked' / p.stem for p in seoul_archives(base)] if dataset == 'seoul'
             else payload_roots(base, dataset))
    return [p for folder in roots for p in folder.rglob('*')
            if p.is_file() and p.suffix.lower() in ('.wav', '.flac') and '__MACOSX' not in p.parts]


def audio_info(path):
    """WAV/FLAC 헤더에서 정확한 샘플 수를 읽는다. 디코드 검증과는 구별한다."""
    with Path(path).open('rb') as f:
        magic = f.read(4)
        if magic == b'fLaC':
            header = f.read(4)
            if len(header) != 4 or header[0] & 127 != 0 or int.from_bytes(header[1:], 'big') != 34:
                raise ValueError('FLAC STREAMINFO 오류')
            block = f.read(34)
            if len(block) != 34:
                raise ValueError('잘린 FLAC STREAMINFO')
            packed = int.from_bytes(block[10:18], 'big')
            sr, channels, samples = packed >> 44, ((packed >> 41) & 7) + 1, packed & ((1 << 36) - 1)
        elif magic == b'RIFF':
            file_size = Path(path).stat().st_size
            riff_size = int.from_bytes(f.read(4), 'little')
            if f.read(4) != b'WAVE' or riff_size + 8 > file_size:
                raise ValueError('잘못된 RIFF/WAVE 길이')
            fmt = None
            data_bytes = 0
            while f.tell() + 8 <= riff_size + 8:
                kind, size = struct.unpack('<4sI', f.read(8))
                end = f.tell() + size
                if end + size % 2 > min(file_size, riff_size + 8):
                    raise ValueError('잘린 WAV chunk')
                if kind == b'fmt ':
                    fmt = f.read(size)
                elif kind == b'data':
                    data_bytes += size
                f.seek(end + size % 2)
            if fmt is None or len(fmt) < 16:
                raise ValueError('WAV fmt 누락')
            tag, channels, sr, _, align, bits = struct.unpack('<HHIIHH', fmt[:16])
            if tag == 65534 and len(fmt) >= 40:
                tag = int.from_bytes(fmt[24:26], 'little')
            if tag not in (1, 3) or align <= 0 or align != channels * ((bits + 7) // 8) or data_bytes % align:
                raise ValueError('WAV PCM/float 형식 오류')
            samples = data_bytes // align
        else:
            raise ValueError('지원하지 않는 오디오 헤더')
    if sr <= 0 or samples <= 0:
        raise ValueError('빈 오디오 또는 잘못된 샘플레이트')
    return {'sample_rate': sr, 'channels': channels, 'samples': samples,
            'duration_seconds': samples / sr}


def case(base, dataset, split, ident, audio, text, cluster, ready=True):
    if not text.strip():
        raise ValueError('빈 정답')
    info = audio_info(audio)
    return {'id': f'{dataset}/{split}/{ident}', 'dataset': dataset, 'split': split,
            'audio': str(audio.relative_to(base)), 'text': text.strip(), 'cluster': cluster,
            **info, 'audio_sha256': digest(audio), 'evaluation_ready': ready,
            'eligible_metrics': ['cer', 'wer']}


def fleurs(base):
    rows = []
    for split in ('train', 'dev', 'test'):
        # TSV의 인용부호는 문장 내용이다. csv 기본 quoting은 필드를 합쳐 버린다.
        for line in (base / 'raw' / f'{split}.tsv').read_text().splitlines():
            fields = line.split('\t')
            if len(fields) != 7:
                raise ValueError('FLEURS TSV 열 수 불일치')
            ident, filename, raw_text, normalized, _, samples, gender = fields
            audio = base / 'extracted' / split / split / filename
            row = case(base, 'fleurs-ko', split, Path(filename).stem, audio, normalized,
                       f'fleurs-ko/sentence/{ident}')
            if row['samples'] != int(samples) or row['sample_rate'] != 16000:
                raise ValueError('FLEURS metadata와 audio header 불일치')
            row.update(raw_text=raw_text, reference_source='human_translated_read_prompt',
                       speaker_id=None, gender=gender)
            rows.append(row)
    return rows


def librispeech_style(base, dataset):
    rows = []
    payload = payload_roots(base, dataset)[0]
    for label in sorted(payload.rglob('*.trans.txt')):
        if '__MACOSX' in label.parts:
            continue
        split = 'all'
        if dataset == 'zeroth':
            split = next(('test' if p == 'test_data_01' else 'train' for p in label.parts
                          if p in ('test_data_01', 'train_data_01')), None)
            # 원본의 LibriSpeech식 분할명도 허용한다.
            if split is None:
                split = next(('test' if p.startswith('test') else 'train' for p in label.parts
                              if p.startswith(('test_', 'test-', 'train_', 'train-'))), None)
            if split is None:
                raise ValueError('Zeroth split 경로를 확인해야 합니다')
        for line in label.read_text().splitlines():
            ident, text = line.split(maxsplit=1)
            audio = label.parent / (ident + '.flac')
            row = case(base, dataset, split, ident, audio, text,
                       f'{dataset}/{"speaker" if dataset == "zeroth" else "session"}/{label.parent.name}')
            if dataset == 'zeroth':
                row['speaker_id'] = label.parent.name
            row['reference_source'] = ('human_subtitles_manual_alignment_asr_screened' if dataset == 'pansori'
                                       else 'crowdsourced_read_speech')
            rows.append(row)
    if not rows:
        raise ValueError('전사 파일을 찾지 못했습니다')
    return rows


def deeply(base):
    labels = list((base / 'raw').glob('Korean_Read_Speech_Corpus_sample.json'))
    if len(labels) != 1:
        raise ValueError('Deeply JSON 경로를 확인해야 합니다')
    data = json.loads(labels[0].read_text())
    audio_index = {}
    for p in payload_roots(base, 'deeply')[0].rglob('*.wav'):
        if '__MACOSX' not in p.parts:
            key = (p.parent.name, p.stem)
            if key in audio_index:
                raise ValueError('Deeply 오디오 ID 중복')
            audio_index[key] = p
    rows = []
    for location, entries in data.items():
        for ident, meta in entries.items():
            audio = audio_index.get((location, ident))
            if audio is None:
                matches = [p for (_, stem), p in audio_index.items() if stem == ident and location in p.parts]
                if len(matches) != 1:
                    raise ValueError('Deeply 음성/정답 대응 실패')
                audio = matches[0]
            row = case(base, 'deeply', 'all', location + '/' + ident, audio, meta['text'],
                       'deeply/script/' + str(meta['text_code']))
            row.update(reference_source='human_read_script', condition=location,
                       speaker_id=str(meta['subjectID']) + '/' + str(meta['speaker']))
            if abs(row['duration_seconds'] - float(meta['length'])) > 0.05:
                raise ValueError('Deeply 길이 metadata 불일치')
            rows.append(row)
    return rows


def textgrid_tier(path, wanted='utt.ortho.'):
    raw = Path(path).read_bytes()
    text = raw.decode('utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig')
    tiers = re.split(r'(?m)^\s*item \[\d+\]:', text)[1:]
    found = []
    for tier in tiers:
        name = re.search(r'name\s*=\s*"([^"]*)"', tier)
        if not name or name.group(1) != wanted:
            continue
        pattern = r'intervals \[\d+\]:\s*xmin\s*=\s*([\d.eE+-]+)\s*xmax\s*=\s*([\d.eE+-]+)\s*text\s*=\s*"((?:[^"]|"")*)"'
        intervals = [(float(a), float(b), s.replace('""', '"')) for a, b, s in re.findall(pattern, tier)]
        expected = int(re.search(r'intervals:\s*size\s*=\s*(\d+)', tier).group(1))
        if len(intervals) != expected:
            raise ValueError('TextGrid interval 파싱 수 불일치')
        found.append(intervals)
    if len(found) != 1:
        raise ValueError('TextGrid 정답 tier를 하나로 특정하지 못했습니다')
    return found[0]


def seoul(base):
    archives = seoul_archives(base)
    for archive in sorted(archives):
        extract_zip(archive, base / 'unpacked' / archive.stem)
    unpacked = [base / 'unpacked' / p.stem for p in archives]
    labels = [p for folder in unpacked for p in folder.rglob('*.TextGrid') if '__MACOSX' not in p.parts]
    audios = {p.stem: p for folder in unpacked for p in folder.rglob('*.flac') if '__MACOSX' not in p.parts}
    if len(labels) != 240 or len(audios) != 240:
        raise ValueError(f'Seoul 배포 개수 불일치: labels={len(labels)}, audio={len(audios)}')
    rows = []
    for label in sorted(labels):
        audio = audios[label.stem]
        info = audio_info(audio)
        intervals = textgrid_tier(label)
        previous = 0.0
        for start, end, _ in intervals:
            if start < previous - 1e-6 or end < start or end > info['duration_seconds'] + 0.05:
                raise ValueError('Seoul 시각 범위/순서 오류')
            previous = end
        lexical = [(a, b, t) for a, b, t in intervals if re.search('[가-힣A-Za-z0-9]', t)]
        row = case(base, 'seoul', 'all', label.stem, audio, '\n'.join(t for _, _, t in lexical),
                   'seoul/interview/' + label.stem[:3], ready=False)
        row.update(segments=[{'start': a, 'end': b, 'text': t} for a, b, t in lexical],
                   reference_source='human_transcription_human_corrected_alignment',
                   provisional_reason='interviewer_coverage_and_markup_policy_need_audit',
                   label_sha256=digest(label), speaker_id=label.stem[:3])
        rows.append(row)
    return rows


BUILDERS = {'fleurs-ko': fleurs, 'pansori': lambda b: librispeech_style(b, 'pansori'),
            'zeroth': lambda b: librispeech_style(b, 'zeroth'), 'deeply': deeply, 'seoul': seoul}


def prepare(root, dataset):
    base = root / 'public' / dataset
    for _, name, _ in ASSETS[dataset]:
        if not name.endswith(('.tar.gz', '.tgz')):
            continue
        payload = base / 'extracted' / name.removesuffix('.tar.gz').removesuffix('.tgz')
        if not (payload / '.archive-sha256').is_file():
            raise ValueError('완료된 압축 해제본이 없습니다. 수집을 먼저 완료하세요')
        extract_tar(base / 'raw' / name, payload,
                    include_roots=('test_data_01', 'train_data_01', 'AUDIO_INFO') if dataset == 'zeroth' else None)
    rows = BUILDERS[dataset](base)
    ids = [r['id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('정답 ID 중복')
    rows.sort(key=lambda r: r['id'])
    referenced = {r['audio'] for r in rows}
    audio_files = prepared_audio_files(base, dataset)
    unpaired = [p for p in audio_files if str(p.relative_to(base)) not in referenced]
    for audio in unpaired:
        audio_info(audio)
    write_new(base / 'pairing-audit.json', json_text({
        'downloaded_audio_files': len(audio_files), 'paired_reference_files': len(rows),
        'unpaired_audio': [{'audio': str(p.relative_to(base)), 'sha256': digest(p)} for p in sorted(unpaired)],
        'unpaired_policy': 'excluded_from_scoring_no_reference_inferred'}))
    # 실제 음성은 stdout/stderr에 출력하지 않고 분할별 결정론적 표본만 디코드한다.
    checked = []
    for split in sorted({r['split'] for r in rows}):
        group = [r for r in rows if r['split'] == split]
        for i in sorted({0, len(group) // 2, len(group) - 1}):
            subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(base / group[i]['audio']),
                            '-f', 'null', '-'], check=True, capture_output=True)
            checked.append(group[i]['id'])
    summary = {'dataset': dataset, 'files': len(rows),
               'duration_seconds': sum(r['duration_seconds'] for r in rows),
               'sample_rates': dict(Counter(r['sample_rate'] for r in rows)),
               'channels': dict(Counter(r['channels'] for r in rows)),
               'evaluation_ready_files': sum(r['evaluation_ready'] for r in rows),
               'clusters': len({r['cluster'] for r in rows}),
               'splits': {s: {'files': sum(r['split'] == s for r in rows),
                               'duration_seconds': sum(r['duration_seconds'] for r in rows if r['split'] == s)}
                          for s in sorted({r['split'] for r in rows})},
               'audio_header_and_sha256_verified': len(rows), 'decode_sample_ids': checked}
    for split in summary['splits']:
        write_new(base / 'ref' / f'{split}.jsonl', ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n'
                  for r in rows if r['split'] == split))
    write_new(base / 'inventory.json', json_text(summary))
    print(json_text(summary), end='')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path)
    ap.add_argument('--datasets', nargs='+', choices=BUILDERS, default=list(BUILDERS))
    args = ap.parse_args()
    root = data_root(args.root)
    for dataset in args.datasets:
        prepare(root, dataset)


if __name__ == '__main__':
    main()
