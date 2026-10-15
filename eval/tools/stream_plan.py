#!/usr/bin/env python3
"""2단계 실시간 평가의 실행 단위(스트리밍 세션)를 만든다.

- taste: 총회 앞 600초(그 안의 마지막 속기록 줄 시작점에서 자름) + 장날 전체
- core: FLEURS 한국어 test + Zeroth test + 총회 전체 + 장날 전체

짧은 공개 클립은 무음(기본 1초)을 끼워 한 스트림으로 묶는다(기본 상한 600초).
긴 회의 녹음은 세션 상한을 넘지 않도록 속기록 줄 경계에서 나눈다(기본 상한 3000초).
모든 엔진이 같은 단위를 받으므로 엔진 간 비교 조건이 같다.

음성 길이는 WAV 헤더 또는 정답 JSONL의 samples/sample_rate로 잰다. 디코드는 실제
실행에서만 한다. 정답 텍스트는 화면에 내지 않는다.
"""
import json
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path

from score import strip_markup

RATE = 16000
SILENCE_GAP = 1.0
BUNDLE_MAX = 600.0
LONG_SEGMENT_MAX = 3000.0
TASTE_CUTOFF = 600.0
PCM_TOLERANCE = 0.01      # 디코드 길이와 계획 길이의 허용 차이(초)

# 엔진별 세션 상한(초). None은 문서에 상한이 없거나 확인하지 못한 경우다.
# gemini는 문서상 연결 약 10분이라 여유를 두고 540초로 둔다.
SESSION_LIMITS = {'muse': 3600, 'mai': 3600, 'deepgram': None, 'grok': None, 'rtzr': None, 'gemini': 540}


@dataclass
class Piece:
    audio: Path
    start: float
    end: float

    @property
    def seconds(self):
        return self.end - self.start


@dataclass
class Unit:
    """스트리밍 세션 하나. 조각 사이에 gap초 무음을 넣어 이어 보낸다."""
    id: str
    set: str
    pieces: list
    gap: float = 0.0
    ref: str = field(default=None, repr=False)   # 이어 붙인 정답. 없으면 CER을 내지 않는다
    scoring: str = None                           # 'standard'(삽입 포함) | 'del_sub'(삽입 제외)
    clip_ids: list = field(default_factory=list, repr=False)

    @property
    def seconds(self):
        return sum(p.seconds for p in self.pieces) + self.gap * max(len(self.pieces) - 1, 0)


# ------------------------------------------------------------------ 길이
def wav_seconds(path):
    with wave.open(str(path), 'rb') as w:
        return w.getnframes() / w.getframerate()


# ------------------------------------------------------------------ 공개 자료
def public_clips(root, dataset, split='test'):
    """정답 JSONL에서 (id, 경로, 길이, 정답)을 ID 순으로 읽는다."""
    base = Path(root) / 'public' / dataset
    rows = []
    with (base / 'ref' / f'{split}.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if row['split'] != split:
                raise ValueError(f'{dataset}: split이 섞여 있습니다')
            if not row.get('evaluation_ready'):
                raise ValueError(f'{dataset}: 평가 미준비 정답이 있습니다')
            seconds = row['samples'] / row['sample_rate']
            rows.append((row['id'], base / row['audio'], seconds, row['text']))
    rows.sort(key=lambda r: r[0])
    return rows


def bundle(set_name, clips, gap=SILENCE_GAP, max_seconds=BUNDLE_MAX):
    """클립을 순서대로 채워 묶음 길이(무음 포함)가 상한을 넘지 않게 나눈다."""
    units, current = [], []

    def flush():
        if current:
            units.append(Unit(
                id=f'{set_name}/bundle-{len(units) + 1:03d}', set=set_name,
                pieces=[Piece(p, 0.0, s) for _, p, s, _ in current], gap=gap,
                ref=' '.join(t for _, _, _, t in current), scoring='standard',
                clip_ids=[i for i, _, _, _ in current]))

    total = 0.0
    for clip in clips:
        seconds = clip[2]
        if seconds > max_seconds:
            raise ValueError(f'{set_name}: 묶음 상한보다 긴 클립이 있습니다')
        added = seconds + (gap if current else 0.0)
        if current and total + added > max_seconds:
            flush()
            current, total, added = [], 0.0, seconds
        current.append(clip)
        total += added
    flush()
    return units


# ------------------------------------------------------------------ 회의 녹음
def aligned_lines(path):
    """aligned.tsv에서 (시작 초, 텍스트)를 읽는다. 녹음 범위 밖 줄은 버린다."""
    lines = []
    for raw in Path(path).read_text(encoding='utf-8').splitlines():
        if not raw.strip() or raw.startswith('#'):
            continue
        cols = raw.split('\t')
        if len(cols) != 6:
            raise ValueError('aligned.tsv 열 수가 6이 아닙니다')
        if cols[3] == 'out-of-range' or not cols[1]:
            continue
        lines.append((float(cols[1]), strip_markup(cols[5])))
    starts = [s for s, _ in lines]
    if starts != sorted(starts):
        raise ValueError('aligned.tsv 시각이 역행합니다')
    return lines


def nearest_boundary(starts, target):
    return min(starts, key=lambda s: (abs(s - target), s))


def meeting_units(set_name, audio, lines, end=None, max_segment=LONG_SEGMENT_MAX, label='all'):
    """회의 녹음을 줄 경계에서 나눈다. 각 줄은 시작 시각이 속한 세션의 정답이 된다."""
    end = end or wav_seconds(audio)
    starts = [s for s, _ in lines if 0 < s < end]
    # 가장 적은 조각 수부터 늘려 가며, 균등 목표점에 가장 가까운 줄 경계로 잘라 모두 상한 안에 드는 첫 분할을 쓴다
    for n in range(max(1, int(-(-end // max_segment))), len(starts) + 2):
        cuts = [0.0] + [nearest_boundary(starts, end * k / n) for k in range(1, n)] + [end]
        if all(0 < b - a <= max_segment for a, b in zip(cuts, cuts[1:])):
            break
    else:
        raise ValueError(f'{set_name}: 줄 경계로 세션 상한 안에서 나눌 수 없습니다')
    units = []
    for k, (a, b) in enumerate(zip(cuts, cuts[1:]), 1):
        ref = ' '.join(t for s, t in lines if a <= s < b)
        if n == 1:
            suffix = label
        else:
            suffix = f'seg-{k}' if label == 'all' else f'{label}-seg-{k}'
        units.append(Unit(id=f'{set_name}/{suffix}', set=set_name, pieces=[Piece(Path(audio), a, b)],
                          ref=ref or None, scoring='del_sub' if ref else None))
    return units


def chonghoe_units(root, cutoff=None, max_segment=LONG_SEGMENT_MAX):
    base = Path(root) / 'chonghoe-2026'
    audio = base / 'audio' / 'chonghoe_16k.wav'
    lines = aligned_lines(base / 'ref' / 'aligned.tsv')
    end = None
    if cutoff is not None:
        # 앞 cutoff초 안에서 마지막으로 시작하는 줄 앞에서 자른다. 줄 중간을 자르지 않기 위해서다.
        end = max(s for s, _ in lines if s <= cutoff)
    return meeting_units('chonghoe-2026', audio, lines, end=end, max_segment=max_segment,
                         label='all' if cutoff is None else 'first')


def jangnal_units(root, max_segment=LONG_SEGMENT_MAX):
    """장날은 축어 정답이 없다(MANIFEST 판정). 지연과 전송만 재고 CER은 내지 않는다.

    줄 경계 정보가 없으므로 상한을 넘으면 같은 길이로 나눈다.
    """
    audio = Path(root) / 'jangnal-2026' / 'audio' / 'jangnal_1bu_16k.wav'
    end = wav_seconds(audio)
    n = int(-(-end // max_segment))
    cuts = [end * k / n for k in range(n + 1)]
    return [Unit(id='jangnal-2026/all' if n == 1 else f'jangnal-2026/seg-{k}', set='jangnal-2026',
                 pieces=[Piece(audio, a, b)]) for k, (a, b) in enumerate(zip(cuts, cuts[1:]), 1)]


def stage_units(root, stage, session_limit=None):
    """session_limit이 있으면 묶음·분할 상한을 그 값 이하로 낮춘다."""
    bundle_max = min(BUNDLE_MAX, session_limit or BUNDLE_MAX)
    segment_max = min(LONG_SEGMENT_MAX, session_limit or LONG_SEGMENT_MAX)
    if stage == 'taste':
        return (chonghoe_units(root, cutoff=TASTE_CUTOFF, max_segment=segment_max)
                + jangnal_units(root, segment_max))
    if stage == 'core':
        return (bundle('fleurs-ko', public_clips(root, 'fleurs-ko'), max_seconds=bundle_max)
                + bundle('zeroth', public_clips(root, 'zeroth'), max_seconds=bundle_max)
                + chonghoe_units(root, max_segment=segment_max) + jangnal_units(root, segment_max))
    raise ValueError(f'알 수 없는 단계: {stage}')


def engine_units(root, stage, engines, common=False):
    """엔진별 세션 단위.

    기본: 모든 엔진이 공통 분할(묶음 600초, 회의 3000초)을 받고, 세션 상한이 그보다 짧은
    엔진만 자기 상한으로 다시 나눈 단위를 받는다. 다른 엔진의 분할은 바뀌지 않는다.
    common=True: 고른 엔진들의 상한 중 최솟값으로 한 번 나눠 모든 엔진이 같은 단위를 받는다.
    """
    limits = [SESSION_LIMITS[e] for e in engines if SESSION_LIMITS[e] is not None]
    if common:
        units = stage_units(root, stage, min(limits) if limits else None)
        return {e: units for e in engines}
    default = stage_units(root, stage)
    out = {}
    for e in engines:
        limit = SESSION_LIMITS[e]
        if limit is not None and any(u.seconds > limit for u in default):
            out[e] = stage_units(root, stage, limit)
        else:
            out[e] = default
    return out


def check_session_limits(units, engines):
    for engine in engines:
        limit = SESSION_LIMITS[engine]
        if limit is None:
            continue
        over = [u.id for u in units if u.seconds > limit]
        if over:
            raise ValueError(f'{engine}: 세션 상한 {limit}초를 넘는 단위 {len(over)}개')


# ------------------------------------------------------------------ PCM
def decode_pcm(path):
    """16kHz mono PCM16으로 읽는다. 이미 그 형식인 WAV만 직접 읽고 나머지는 ffmpeg로 변환한다."""
    try:
        with wave.open(str(path), 'rb') as w:
            if (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (RATE, 1, 2):
                return w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        pass
    out = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path),
                          '-f', 's16le', '-ac', '1', '-ar', str(RATE), '-'],
                         check=True, capture_output=True)
    return out.stdout


def unit_pcm(unit, decode=decode_pcm):
    gap = b'\x00\x00' * int(round(unit.gap * RATE))
    parts = []
    for piece in unit.pieces:
        pcm = decode(piece.audio)
        a = int(round(piece.start * RATE)) * 2
        b = int(round(piece.end * RATE)) * 2
        parts.append(pcm[a:b])
    return gap.join(parts)


def check_pcm_length(unit, pcm, tolerance=PCM_TOLERANCE):
    """디코드한 길이가 계획과 다르면 사유 문자열. 잘린 파일·잘못된 메타데이터를 시작 전에 잡는다."""
    expected = unit.seconds * RATE
    actual = len(pcm) / 2
    if abs(actual - expected) > tolerance * RATE:
        return f'PCM 길이 불일치: 기대 {expected / RATE:.3f}초, 실제 {actual / RATE:.3f}초'
    return None
