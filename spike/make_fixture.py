#!/usr/bin/env python3.12
"""한국어 3화자 대화 픽스처 생성 (정답 전사·화자·경계 시각 확정).

각 턴을 서로 다른 Gemini TTS 음성으로 따로 만든 뒤 무음을 끼워 이어붙인다.
합성 음원이므로 실제 회의실 녹음보다 쉬운 조건이며, 측정값은 상한(ceiling)으로 읽어야 한다.

의존: ffmpeg/ffprobe, GEMINI_API_KEY, speech-toolkit의 TTS/gemini_tts.py
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TURNS_DIR = HERE / "turns"

RATE = 24000
GAP_MS = 400  # 턴 사이 무음. 400ms는 엔드포인팅을 방해하므로 900ms 판도 함께 볼 것.


def find_toolkit():
    """speech-toolkit(https://github.com/Engccer/speech-toolkit) 위치를 찾는다.

    SPEECH_TOOLKIT 환경변수가 있으면 그것을, 없으면 흔한 위치를 훑는다.
    """
    env = os.environ.get("SPEECH_TOOLKIT")
    cands = [Path(env)] if env else []
    cands += [
        HERE.parents[1] / "speech-toolkit",
        Path.home() / "Mac-Projects" / "speech-toolkit",
    ]
    for c in cands:
        if (c / "TTS" / "gemini_tts.py").exists():
            return c
    print("speech-toolkit을 찾지 못했습니다. SPEECH_TOOLKIT 환경변수로 경로를 지정하세요.")
    sys.exit(1)


# (화자, 음성, 대사) — 2026-11-16은 월요일(결정론적 검증 완료)
TURNS = [
    ("A", "Kore",   "네, 그럼 이학기 영어과 평가 계획 회의를 시작하겠습니다."),
    ("B", "Puck",   "지난번에 수행평가 비중을 사십 퍼센트로 올리자고 하셨는데, 그대로 갈까요?"),
    ("C", "Charon", "저는 조금 조심스럽습니다. 학생들 부담이 커질 것 같아서요."),
    ("A", "Kore",   "그 부분은 저도 고민했습니다. 대신 지필 평가를 한 번 줄이면 어떨까요?"),
    ("B", "Puck",   "그러면 총괄 평가가 한 번뿐인데 변별력이 떨어지지 않을까요?"),
    ("C", "Charon", "동아출판 교과서 기준으로 보면 오 단원까지가 적정한 범위입니다."),
    ("A", "Kore",   "좋습니다. 그럼 수행평가는 말하기와 쓰기 두 영역으로 나누겠습니다."),
    ("B", "Puck",   "말하기 평가는 신명중학교 방송실을 쓰면 녹음이 수월할 것 같습니다."),
    ("C", "Charon", "일정은 십일월 셋째 주가 어떨까요? 그때가 비교적 여유가 있습니다."),
    ("A", "Kore",   "네, 십일월 십육일 월요일로 잡겠습니다. 이의 없으시죠?"),
    ("B", "Puck",   "동의합니다."),
    ("C", "Charon", "저도 동의합니다."),
]


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", **kw)
    if p.returncode != 0:
        print(f"실패: {' '.join(str(c) for c in cmd)}\n{p.stdout}\n{p.stderr}")
        sys.exit(1)
    return p


def duration_ms(path):
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return int(round(float(p.stdout.strip()) * 1000))


def main():
    if not shutil.which("ffmpeg"):
        print("ffmpeg가 PATH에 없습니다.")
        sys.exit(1)
    gemini_tts = find_toolkit() / "TTS" / "gemini_tts.py"
    TURNS_DIR.mkdir(parents=True, exist_ok=True)

    parts, ground_truth, cursor_ms = [], [], 0

    silence = TURNS_DIR / "_gap.wav"
    run(["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"anullsrc=r={RATE}:cl=mono", "-t", f"{GAP_MS / 1000}",
         "-c:a", "pcm_s16le", str(silence)])

    for i, (speaker, voice, text) in enumerate(TURNS, 1):
        stem = TURNS_DIR / f"t{i:02d}"
        txt = stem.with_suffix(".txt")
        txt.write_text(text, encoding="utf-8")

        raw = stem.parent / f"t{i:02d}_gemini_tts.wav"
        if not raw.exists():
            print(f"[{i:02d}/{len(TURNS)}] {speaker}({voice}) 합성 중...")
            run([sys.executable, str(gemini_tts), str(txt),
                 "--voice", voice, "--language-code", "ko-KR"])
        if not raw.exists():
            cands = list(stem.parent.glob(f"t{i:02d}*.wav"))
            if not cands:
                print(f"턴 {i} 음성 파일을 찾지 못했습니다.")
                sys.exit(1)
            raw = cands[0]

        norm = stem.parent / f"t{i:02d}_norm.wav"
        run(["ffmpeg", "-y", "-i", str(raw), "-ac", "1", "-ar", str(RATE),
             "-c:a", "pcm_s16le", str(norm)])

        dur = duration_ms(norm)
        ground_truth.append({
            "index": i, "speaker": speaker, "voice": voice, "text": text,
            "start_ms": cursor_ms, "end_ms": cursor_ms + dur,
        })
        parts.append(norm)
        cursor_ms += dur + GAP_MS

    concat_list = HERE / "_concat.txt"
    lines = []
    for idx, part in enumerate(parts):
        lines.append(f"file '{part.as_posix()}'")
        if idx != len(parts) - 1:
            lines.append(f"file '{silence.as_posix()}'")
    concat_list.write_text("\n".join(lines), encoding="utf-8")

    out = HERE / "fixture_ko_3spk.wav"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(out)])

    meta = {
        "audio": out.name,
        "sample_rate": RATE,
        "channels": 1,
        "encoding": "pcm_s16le",
        "total_ms": duration_ms(out),
        "speakers": sorted({t["speaker"] for t in ground_truth}),
        "gap_ms": GAP_MS,
        "note": "Gemini TTS 합성 음원. 실제 회의실 녹음보다 쉬운 조건이며 상한 측정용.",
        "turns": ground_truth,
    }
    (HERE / "ground_truth.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n생성 완료: {out}")
    print(f"길이 {meta['total_ms'] / 1000:.1f}초, 턴 {len(ground_truth)}개, 화자 {len(meta['speakers'])}명")


if __name__ == "__main__":
    main()
