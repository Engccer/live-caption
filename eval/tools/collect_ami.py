#!/usr/bin/env python3
"""AMI 공식 scenario-only dev/test 음원과 사람이 검토한 전사 경계를 수집한다.

자료는 저장소 밖에만 저장한다. 단어 시각의 강제정렬 값을 발화 경계로 쓰지 않는다.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import re
import wave
import xml.etree.ElementTree as ET
import zipfile

from public_data import data_root, digest, download, json_text, write_new

ANNOTATION_URL = 'https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/ami_public_manual_1.6.2.zip'
AUDIO_BASE = 'https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus'
SPLITS = {
    'dev': ['ES2003', 'ES2011', 'IS1008', 'TS3004', 'TS3006'],
    'test': ['ES2004', 'ES2014', 'IS1009', 'TS3003', 'TS3007'],
}
NITE = '{http://nite.sourceforge.net/}'
HREF = re.compile(r'([^/#]+)#id\(([^)]+)\)(?:\.\.id\(([^)]+)\))?\Z')


def meeting_ids(split):
    return [base + suffix for base in SPLITS[split] for suffix in 'abcd']


def parse_speaker(words_xml, segments_xml, meeting, speaker):
    """NXT 단어 참조를 해석하되 시간은 transcriber 경계만 채택한다."""
    words = list(ET.fromstring(words_xml))
    indices = {}
    for index, word in enumerate(words):
        word_id = word.get(NITE + 'id')
        if not word_id or word_id in indices:
            raise ValueError('단어 ID 누락 또는 중복')
        indices[word_id] = index
    output = []
    for segment in ET.fromstring(segments_xml):
        if segment.tag != 'segment':
            continue
        start = float(segment.attrib['transcriber_start'])
        end = float(segment.attrib['transcriber_end'])
        finite_bounds = math.isfinite(start) and math.isfinite(end) and start >= 0 and end >= 0
        if not finite_bounds:
            raise ValueError('잘못된 전사 경계')
        selected = []
        selected_ids = set()
        for child in segment:
            if child.tag != NITE + 'child':
                continue
            match = HREF.fullmatch(child.attrib['href'])
            if not match or match[1] != f'{meeting}.{speaker}.words.xml':
                raise ValueError('예상하지 않은 NXT 단어 참조')
            first, last = match[2], match[3] or match[2]
            if first not in indices or last not in indices or indices[first] > indices[last]:
                raise ValueError('단어 참조 범위가 유효하지 않습니다')
            for index in range(indices[first], indices[last] + 1):
                if index in selected_ids:
                    raise ValueError('세그먼트 안 단어 중복 참조')
                selected_ids.add(index)
                selected.append(words[index])
        if not selected:
            raise ValueError('단어 참조 없는 세그먼트')
        events = Counter(w.tag for w in selected if w.tag != 'w')
        lexical = [w for w in selected if w.tag == 'w' and w.get('punc') != 'true']
        speech = bool(lexical or events.get('gap'))
        if speech and start >= end:
            raise ValueError('잘못된 전사 경계')
        # 문장부호를 포함한 원래 어순을 보존하며 철자와 간투사를 바꾸지 않는다.
        text = ' '.join((w.text or '').strip() for w in selected if w.tag == 'w').strip()
        output.append({
            'speaker': speaker, 'start': start, 'end': end, 'text': text,
            'lexical_word_count': len(lexical), 'event_counts': dict(sorted(events.items())),
            'speech': speech, 'boundary_valid': start < end,
        })
    return output


def parse_meeting(archive, meeting):
    segments = []
    for speaker in 'ABCD':
        segments.extend(parse_speaker(
            archive.read(f'words/{meeting}.{speaker}.words.xml'),
            archive.read(f'segments/{meeting}.{speaker}.segments.xml'), meeting, speaker))
    return sorted(segments, key=lambda x: (x['start'], x['end'], x['speaker']))


def audio_info(path):
    with wave.open(str(path), 'rb') as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 16000, 'NONE'):
            raise ValueError('예상하지 않은 AMI PCM 형식')
        frames = audio.getnframes()
        if frames <= 0:
            raise ValueError('빈 음원')
        # WAV 헤더뿐 아니라 실제 PCM 전부를 읽어 잘린 파일을 검출한다.
        seen = 0
        for block in iter(lambda: audio.readframes(65536), b''):
            seen += len(block)
        if seen != frames * 2:
            raise ValueError('잘린 PCM 파일')
        return {'duration_seconds': frames / 16000, 'frames': frames,
                'sample_rate': 16000, 'channels': 1, 'sample_width': 2}


def rttm_text(meeting, segments):
    return ''.join(f"SPEAKER {meeting} 1 {s['start']:.6f} {s['end'] - s['start']:.6f} <NA> <NA> {s['speaker']} <NA> <NA>\n"
                   for s in segments if s['speech'])


def out_of_audio_segments(segments, duration):
    """음원과 맞지 않는 경계를 잘라내거나 추정하지 않는다."""
    return sum(s['start'] > duration or s['end'] > duration for s in segments)


def collect(root, workers=3):
    root = data_root(root) / 'public' / 'ami'
    annotation = root / 'raw' / 'ami_public_manual_1.6.2.zip'
    annotation_receipt = download(ANNOTATION_URL, annotation)
    rows = [(split, meeting) for split in SPLITS for meeting in meeting_ids(split)]

    def fetch(row):
        split, meeting = row
        relative = Path('raw/audio') / f'{meeting}.Mix-Headset.wav'
        url = f'{AUDIO_BASE}/{meeting}/audio/{meeting}.Mix-Headset.wav'
        receipt = download(url, root / relative)
        info = audio_info(root / relative)
        print(json.dumps({'meeting': meeting, 'split': split, 'audio_verified': True}), flush=True)
        return {'id': meeting, 'split': split, 'audio': relative.as_posix(),
                'bytes': receipt['bytes'], 'sha256': receipt['sha256'], 'url': url, **info}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        inventory = list(pool.map(fetch, rows))
    with zipfile.ZipFile(annotation) as archive:
        if archive.testzip() is not None:
            raise ValueError('AMI annotation ZIP CRC 오류')
        for item in inventory:
            meeting = item['id']
            segments = parse_meeting(archive, meeting)
            outside = out_of_audio_segments(segments, item['duration_seconds'])
            payload = {'meeting_id': meeting, 'language': 'en', 'split': item['split'],
                       'boundary_source': 'human_reviewed_transcriber_segments',
                       'word_timing_source': 'forced_alignment_not_used', 'segments': segments}
            if outside:
                payload.update({'eligible_for_evaluation': False, 'out_of_audio_segments': outside,
                                'audio_duration_seconds': item['duration_seconds']})
            ref_file = root / 'ref' / f'{meeting}.segments.json'
            rttm_file = root / 'ref' / f'{meeting}.rttm'
            write_new(ref_file, json_text(payload))
            if not outside:
                write_new(rttm_file, rttm_text(meeting, segments))
            item.update({'reference': str(ref_file.relative_to(root)),
                         'reference_sha256': digest(ref_file),
                         'rttm': str(rttm_file.relative_to(root)) if not outside else None,
                         'rttm_sha256': digest(rttm_file) if not outside else None,
                         'eligible_for_evaluation': not outside, 'out_of_audio_segments': outside,
                         'segments': len(segments), 'speech_segments': sum(s['speech'] for s in segments),
                         'lexical_words': sum(s['lexical_word_count'] for s in segments),
                         'invalid_non_speech_boundaries': sum(not s['boundary_valid'] for s in segments),
                         'speakers': len({s['speaker'] for s in segments if s['speech']})})
    summary = {'dataset': 'AMI', 'partition': 'scenario-only', 'audio_condition': 'Mix-Headset',
               'annotation_version': '1.6.2', 'license': 'CC-BY-4.0',
               'annotation_sha256': annotation_receipt['sha256'],
               'meetings': len(inventory), 'bytes_audio': sum(x['bytes'] for x in inventory),
               'eligible_meetings': sum(x['eligible_for_evaluation'] for x in inventory),
               'excluded_recordings': [x['id'] for x in inventory if not x['eligible_for_evaluation']],
               'eligible_duration_seconds': sum(x['duration_seconds'] for x in inventory if x['eligible_for_evaluation']),
               'duration_seconds': sum(x['duration_seconds'] for x in inventory),
               'invalid_non_speech_boundaries': sum(x['invalid_non_speech_boundaries'] for x in inventory),
               'splits': {split: {'meetings': sum(x['split'] == split for x in inventory),
                                  'eligible_meetings': sum(x['split'] == split and x['eligible_for_evaluation'] for x in inventory),
                                  'eligible_duration_seconds': sum(x['duration_seconds'] for x in inventory if x['split'] == split and x['eligible_for_evaluation']),
                                  'duration_seconds': sum(x['duration_seconds'] for x in inventory if x['split'] == split),
                                  'speech_segments': sum(x['speech_segments'] for x in inventory if x['split'] == split),
                                  'lexical_words': sum(x['lexical_words'] for x in inventory if x['split'] == split)}
                          for split in SPLITS}}
    write_new(root / 'inventory.json', json_text({'summary': summary, 'recordings': inventory}))
    write_new(root / 'summary.json', json_text(summary))
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', help='저장소 밖 eval 자료 최상위 폴더')
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=3)
    args = parser.parse_args()
    collect(args.data_root, args.workers)
