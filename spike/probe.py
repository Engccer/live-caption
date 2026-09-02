#!/usr/bin/env python3.12
"""실시간 STT 프로바이더 지연·화자분리 측정 하네스 (스파이크용, 폐기 전제).

WAV를 1배속으로 페이싱해 WebSocket으로 흘리고, 도착한 모든 이벤트에
스트림 시작 기준 경과 시각을 찍어 JSON으로 남긴다. 두 프로바이더 모두
raw websocket을 쓰므로 SDK 내부 버퍼링이 측정에 섞이지 않는다.

사용법:
    python probe.py --provider muse     --audio fixture_ko_3spk.wav
    python probe.py --provider deepgram --audio fixture_ko_3spk.wav
"""
import argparse
import asyncio
import base64
import json
import os
import sys
import time
import wave
from pathlib import Path
from urllib.parse import urlencode

import websockets

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHUNK_MS = 80


def load_pcm(path):
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1, "모노만 지원"
        assert w.getsampwidth() == 2, "16-bit PCM만 지원"
        return w.readframes(w.getnframes()), w.getframerate()


class Probe:
    def __init__(self, provider):
        self.provider = provider
        self.events = []
        self.t0 = None

    def now_ms(self):
        return round((time.monotonic() - self.t0) * 1000, 1)

    def log(self, kind, **fields):
        self.events.append({"t_ms": self.now_ms(), "kind": kind, **fields})


# ---------------------------------------------------------------- Meta Muse
async def run_muse(pcm, rate, probe):
    key = os.environ.get("META_API_KEY") or os.environ.get("MODEL_API_KEY")
    if not key:
        print("META_API_KEY가 없습니다.")
        return None
    enc = {24000: "PCM_24KHZ", 16000: "PCM_16KHZ"}.get(rate)
    if not enc:
        print(f"Muse는 16k/24k만 받습니다(입력 {rate}).")
        return None

    url = "wss://api.meta.ai/v1/asr/realtime"
    async with websockets.connect(url, max_size=None, open_timeout=30) as ws:
        await ws.send(json.dumps({
            "authorization": {"accessToken": f"Bearer {key}"},
            "audioEncoding": enc,
            "model": "muse-voice-transcribe-1.0",
            "mode": "DIARIZATION",
            "partialMode": "CUMULATIVE",
            "languageBias": ["Korean"],
            "emitAudioProgress": True,
        }))
        probe.t0 = time.monotonic()
        probe.log("handshake_sent")

        async def sender():
            step = int(rate * CHUNK_MS / 1000) * 2
            for off in range(0, len(pcm), step):
                target = off / 2 / rate
                drift = target - (time.monotonic() - probe.t0)
                if drift > 0:
                    await asyncio.sleep(drift)
                await ws.send(pcm[off:off + step])
            probe.log("audio_sent_all", audio_ms=round(len(pcm) / 2 / rate * 1000))
            await ws.send(json.dumps({"type": "endStream"}))

        async def receiver():
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                t = msg.get("type") or ("session" if "sessionId" in msg else "?")
                if t == "audioProgress":
                    continue
                probe.log(t,
                          text=msg.get("transcript"),
                          final=msg.get("final"),
                          speaker=msg.get("label"),
                          turn=msg.get("turnId"),
                          audio_ms=msg.get("audioProcessedMs"),
                          error=msg.get("message"))

        send_task = asyncio.create_task(sender())
        try:
            await asyncio.wait_for(receiver(), timeout=len(pcm) / 2 / rate + 60)
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            pass
        send_task.cancel()
    return probe.events


# ----------------------------------------------------------------- Deepgram
async def run_deepgram(pcm, rate, probe):
    key = os.environ.get("DEEPGRAM_API_KEY")
    if not key:
        print("DEEPGRAM_API_KEY가 없습니다.")
        return None

    qs = urlencode({
        "model": "nova-3", "language": "ko", "diarize": "true",
        "interim_results": "true", "punctuate": "true",
        "encoding": "linear16", "sample_rate": str(rate), "channels": "1",
    })
    url = f"wss://api.deepgram.com/v1/listen?{qs}"
    async with websockets.connect(
        url, additional_headers={"Authorization": f"Token {key}"},
        max_size=None, open_timeout=30,
    ) as ws:
        probe.t0 = time.monotonic()
        probe.log("connected")

        async def sender():
            step = int(rate * CHUNK_MS / 1000) * 2
            for off in range(0, len(pcm), step):
                target = off / 2 / rate
                drift = target - (time.monotonic() - probe.t0)
                if drift > 0:
                    await asyncio.sleep(drift)
                await ws.send(pcm[off:off + step])
            probe.log("audio_sent_all", audio_ms=round(len(pcm) / 2 / rate * 1000))
            await ws.send(json.dumps({"type": "CloseStream"}))

        async def receiver():
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                if msg.get("type") != "Results":
                    probe.log(msg.get("type", "?"), error=str(msg)[:200])
                    continue
                alt = msg["channel"]["alternatives"][0]
                if not alt.get("transcript"):
                    continue
                spks = sorted({w.get("speaker") for w in alt.get("words", [])
                               if w.get("speaker") is not None})
                probe.log("transcript",
                          text=alt["transcript"],
                          final=msg.get("is_final"),
                          speech_final=msg.get("speech_final"),
                          speaker=",".join(str(s) for s in spks) or None,
                          audio_ms=round((msg.get("start", 0)
                                          + msg.get("duration", 0)) * 1000))

        send_task = asyncio.create_task(sender())
        try:
            await asyncio.wait_for(receiver(), timeout=len(pcm) / 2 / rate + 60)
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            pass
        send_task.cancel()
    return probe.events


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, choices=["muse", "deepgram"])
    ap.add_argument("--audio", default="fixture_ko_3spk.wav")
    ap.add_argument("--out")
    args = ap.parse_args()

    audio = Path(args.audio)
    pcm, rate = load_pcm(audio)
    probe = Probe(args.provider)

    runner = {"muse": run_muse, "deepgram": run_deepgram}[args.provider]
    started = time.time()
    try:
        await runner(pcm, rate, probe)
    except Exception as exc:
        print(f"오류: {type(exc).__name__}: {exc}")
        if probe.t0:
            probe.log("exception", error=f"{type(exc).__name__}: {exc}")

    out = Path(args.out or f"result_{args.provider}.json")
    out.write_text(json.dumps({
        "provider": args.provider,
        "audio": audio.name,
        "sample_rate": rate,
        "audio_ms": round(len(pcm) / 2 / rate * 1000),
        "wall_s": round(time.time() - started, 1),
        "events": probe.events,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    finals = [e for e in probe.events if e.get("final")]
    print(f"{args.provider}: 이벤트 {len(probe.events)}개 (확정 {len(finals)}개) → {out.name}")
    for e in probe.events[:4]:
        print("  ", {k: v for k, v in e.items() if v is not None})


if __name__ == "__main__":
    asyncio.run(main())
