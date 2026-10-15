#!/usr/bin/env python3
"""실시간 STT 엔진 어댑터. 16kHz mono PCM16을 실시간 속도로 보내고 이벤트를 기록한다.

모든 엔진이 같은 계약을 따른다.
- 입력: PCM16 바이트, 예산 세션(cost._Session). 청크를 보내기 전에 charge()로 비용을 청구한다.
- 기록: 이벤트마다 첫 오디오 전송 기준 경과 ms(t_ms)와 엔진이 알린 오디오 위치(audio_ms).
  partial 지연 = t_ms - audio_ms (spike/score.py와 같은 정의).
- 반환: 최종 텍스트, 이벤트, 전송 초, 예산 중단 여부, 오류.

⚠ meta-muse·deepgram은 spike/probe.py에서 실호출로 확인한 순서를 옮겼다. grok·mai·rtzr는
문서만 보고 짰고 실호출로 확인하지 않았다. **다음 세션의 첫 실호출이 검증 게이트다.**
로컬 가짜 서버 테스트(test_engines.py)는 메시지 순서만 보장하고 서버의 실제 응답 형식은
보장하지 않는다.
"""
import asyncio
import base64
import json
import os
import time
import urllib.parse
import urllib.request
from array import array

from cost import BudgetExceeded

RATE = 16000


class Recorder:
    def __init__(self):
        self.events = []
        self.t0 = None

    def start(self):
        self.t0 = time.monotonic()

    def now_ms(self):
        return round((time.monotonic() - self.t0) * 1000, 1) if self.t0 else 0.0

    def log(self, kind, **fields):
        self.events.append({'t_ms': self.now_ms(), 'kind': kind,
                            **{k: v for k, v in fields.items() if v is not None}})


class Engine:
    name = ''
    env = ()
    chunk_ms = 100
    drain_timeout = 30.0

    def __init__(self, environ=None, url=None, pace=1.0, connect=None):
        self.environ = os.environ if environ is None else environ
        self.url_override = url
        self.pace = pace            # 1.0=실시간. 테스트에서만 0으로 둔다
        self._connect = connect

    def missing_env(self):
        return [k for k in self.env if not self.environ.get(k, '').strip()]

    def connect(self, url, headers=None):
        if self._connect:
            return self._connect(url, headers)
        import websockets
        return websockets.connect(url, additional_headers=headers or {}, max_size=None,
                                  open_timeout=30)

    async def paced_send(self, pcm, rec, budget, send_chunk, after_chunk=None):
        """청크마다 비용을 먼저 청구하고 실시간 위치에 맞춰 보낸다. 예산이 닿으면 True."""
        step = int(RATE * self.chunk_ms / 1000) * 2
        rec.start()
        for off in range(0, len(pcm), step):
            chunk = pcm[off:off + step]
            drift = off / 2 / RATE * self.pace - (time.monotonic() - rec.t0)
            if drift > 0:
                await asyncio.sleep(drift)
            try:
                budget.charge(len(chunk) / 2 / RATE)
            except BudgetExceeded as exc:
                rec.log('budget_stop', error=str(exc), audio_ms=round(off / 2 / RATE * 1000))
                return True
            await send_chunk(chunk)
            if after_chunk:
                await after_chunk(chunk)
        rec.log('audio_sent_all', audio_ms=round(len(pcm) / 2 / RATE * 1000))
        return False

    async def run(self, pcm, budget):
        rec = Recorder()
        state = {'aborted': False, 'error': None, 'text': ''}
        try:
            state['text'] = await self.session(pcm, rec, budget, state)
        except Exception as exc:     # 엔진 하나의 실패가 다른 엔진을 멈추지 않게 한다
            state['error'] = f'{type(exc).__name__}: {exc}'
            rec.log('exception', error=state['error'])
        return {'text': state['text'] or '', 'events': rec.events, 'aborted': state['aborted'],
                'error': state['error'], 'sent_seconds': budget.sent}

    async def session(self, pcm, rec, budget, state):
        raise NotImplementedError

    async def _drain(self, task):
        """송신이 끝난 뒤 수신 종료를 기다린다. 상한을 넘으면 끊는다."""
        try:
            await asyncio.wait_for(task, timeout=self.drain_timeout)
        except asyncio.TimeoutError:
            task.cancel()


async def _recv_json(ws, timeout):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        if isinstance(raw, str):
            return json.loads(raw)


def _closed_types():
    import websockets
    return (websockets.ConnectionClosed,)


# ------------------------------------------------------------------ Meta Muse
class Muse(Engine):
    """spike/probe.py run_muse 이식. 인증은 첫 JSON 프레임이며 헤더는 무시된다."""
    name, env, chunk_ms = 'muse', ('META_API_KEY',), 80
    URL = 'wss://api.meta.ai/v1/asr/realtime'

    async def session(self, pcm, rec, budget, state):
        finals, completes = [], []
        async with self.connect(self.url_override or self.URL) as ws:
            await ws.send(json.dumps({
                'authorization': {'accessToken': f'Bearer {self.environ["META_API_KEY"]}'},
                'audioEncoding': 'PCM_16KHZ', 'model': 'muse-voice-transcribe-1.0',
                'mode': 'DIARIZATION', 'partialMode': 'CUMULATIVE',
                'languageBias': ['Korean'], 'emitAudioProgress': True}))

            async def receiver():
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        msg = json.loads(raw)
                        kind = msg.get('type') or ('session' if 'sessionId' in msg else '?')
                        if kind == 'audioProgress':
                            continue
                        if kind == 'transcript':
                            rec.log('transcript', text=msg.get('transcript'), final=bool(msg.get('final')),
                                    audio_ms=msg.get('audioProcessedMs'))
                            if msg.get('final') and msg.get('transcript'):
                                finals.append(msg['transcript'])
                        elif kind == 'speechComplete':
                            rec.log('speechComplete')
                            if msg.get('transcript'):
                                completes.append(msg['transcript'])
                        else:
                            rec.log(kind, speaker=msg.get('label'), error=msg.get('message'))
                except _closed_types():
                    pass

            task = asyncio.create_task(receiver())
            state['aborted'] = await self.paced_send(pcm, rec, budget, ws.send)
            await ws.send(json.dumps({'type': 'endStream'}))
            await self._drain(task)
        return ' '.join(completes or finals)


# ------------------------------------------------------------------ Deepgram
class Deepgram(Engine):
    """spike/probe.py run_deepgram 이식."""
    name, env, chunk_ms = 'deepgram', ('DEEPGRAM_API_KEY',), 80
    URL = 'wss://api.deepgram.com/v1/listen'

    def url(self):
        qs = urllib.parse.urlencode({
            'model': 'nova-3', 'language': 'ko', 'diarize': 'true', 'interim_results': 'true',
            'punctuate': 'true', 'encoding': 'linear16', 'sample_rate': str(RATE), 'channels': '1'})
        return f'{self.url_override or self.URL}?{qs}'

    async def session(self, pcm, rec, budget, state):
        finals = []
        headers = {'Authorization': f'Token {self.environ["DEEPGRAM_API_KEY"]}'}
        async with self.connect(self.url(), headers) as ws:
            async def receiver():
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        msg = json.loads(raw)
                        if msg.get('type') != 'Results':
                            rec.log(msg.get('type', '?'), error=str(msg)[:200])
                            continue
                        text = msg['channel']['alternatives'][0].get('transcript')
                        if not text:
                            continue
                        rec.log('transcript', text=text, final=bool(msg.get('is_final')),
                                audio_ms=round((msg.get('start', 0) + msg.get('duration', 0)) * 1000))
                        if msg.get('is_final'):
                            finals.append(text)
                except _closed_types():
                    pass

            task = asyncio.create_task(receiver())
            state['aborted'] = await self.paced_send(pcm, rec, budget, ws.send)
            await ws.send(json.dumps({'type': 'CloseStream'}))
            await self._drain(task)
        return ' '.join(finals)


# ------------------------------------------------------------------ xAI Grok
class Grok(Engine):
    """docs.x.ai 음성 인식 문서(2026-10-16 확인) 기준. 실호출 미확인."""
    name, env, chunk_ms = 'grok', ('XAI_API_KEY',), 100
    URL = 'wss://api.x.ai/v1/stt'

    def url(self):
        qs = urllib.parse.urlencode({
            'model': 'grok-voice-transcribe-2.0', 'sample_rate': str(RATE), 'encoding': 'pcm',
            'interim_results': 'true', 'language': 'ko', 'diarize': 'true'})
        return f'{self.url_override or self.URL}?{qs}'

    async def session(self, pcm, rec, budget, state):
        finals, done = [], {}
        headers = {'Authorization': f'Bearer {self.environ["XAI_API_KEY"]}'}
        async with self.connect(self.url(), headers) as ws:
            # transcript.created 전에는 오디오를 보내지 않는다
            while True:
                msg = await _recv_json(ws, 15)
                if msg.get('type') == 'error':
                    raise RuntimeError(f'grok 오류: {msg.get("message")}')
                if msg.get('type') == 'transcript.created':
                    break

            async def receiver():
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        msg = json.loads(raw)
                        kind = msg.get('type')
                        if kind == 'transcript.partial':
                            pos = None
                            if msg.get('start') is not None and msg.get('duration') is not None:
                                pos = round((msg['start'] + msg['duration']) * 1000)
                            rec.log('transcript', text=msg.get('text'), final=bool(msg.get('is_final')),
                                    speech_final=msg.get('speech_final'), audio_ms=pos)
                            if msg.get('is_final') and msg.get('text'):
                                finals.append(msg['text'])
                        elif kind == 'transcript.done':
                            rec.log('transcript.done', duration=msg.get('duration'))
                            done['text'] = msg.get('text')
                            return
                        else:
                            rec.log(kind or '?', error=msg.get('message'))
                except _closed_types():
                    pass

            task = asyncio.create_task(receiver())
            state['aborted'] = await self.paced_send(pcm, rec, budget, ws.send)
            await ws.send(json.dumps({'type': 'audio.done'}))
            await self._drain(task)
        joined = ' '.join(finals)
        if done.get('text') is not None and done['text'] != joined:
            rec.log('check', error='transcript.done 텍스트가 확정 조각 합과 다름(done을 채택)')
        return done.get('text') if done.get('text') is not None else joined


# ------------------------------------------------------------------ Azure MAI
class Mai(Engine):
    """MAI-Transcribe-2-Streaming Realtime API(Microsoft Learn 2026-10-07 갱신본) 기준. 실호출 미확인.

    서버 VAD가 없어 클라이언트가 commit을 보낸다. 마지막 commit 뒤 COMMIT_MIN초가 지났고
    직전 QUIET_MS 동안 조용하면 commit, 조용한 자리가 없으면 COMMIT_MAX초에 강제 commit.
    """
    name, env, chunk_ms = 'mai', ('AZURE_MAI_ENDPOINT', 'AZURE_MAI_API_KEY', 'AZURE_MAI_DEPLOYMENT_NAME'), 20
    COMMIT_MIN, COMMIT_MAX, QUIET_MS, QUIET_RMS = 3.0, 10.0, 300, 300.0
    EV = 'conversation.item.input_audio_transcription.'

    def url(self):
        if self.url_override:
            return self.url_override
        parts = urllib.parse.urlsplit(self.environ['AZURE_MAI_ENDPOINT'].strip())
        if parts.scheme not in ('https', 'wss') or not parts.hostname or parts.path not in ('', '/'):
            raise ValueError('AZURE_MAI_ENDPOINT는 https://<리소스>.services.ai.azure.com 형식이어야 합니다')
        return parts._replace(scheme='wss', path='/mai/v1/realtime', query='intent=transcription').geturl()

    async def _wait(self, ws, kind):
        while True:
            msg = await _recv_json(ws, 30)
            if msg.get('type') in ('error', self.EV + 'failed'):
                raise RuntimeError(f'mai 오류: {msg.get("error", msg.get("type"))}')
            if msg.get('type') == kind:
                return msg

    async def session(self, pcm, rec, budget, state):
        deltas, completed = [], []
        commits = {'sent': 0, 'done': 0}
        all_done = asyncio.Event()
        headers = {'api-key': self.environ['AZURE_MAI_API_KEY'].strip()}
        async with self.connect(self.url(), headers) as ws:
            await self._wait(ws, 'session.created')
            await ws.send(json.dumps({'type': 'session.update', 'session': {
                'type': 'transcription',
                'audio': {'input': {
                    'format': {'type': 'audio/pcm', 'rate': RATE},
                    'transcription': {'model': self.environ['AZURE_MAI_DEPLOYMENT_NAME'].strip(),
                                      'language': 'ko'},
                    'turn_detection': None}}}}))
            await self._wait(ws, 'session.updated')

            async def receiver():
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        msg = json.loads(raw)
                        kind = msg.get('type', '?')
                        pos = msg.get('audio_end_ms')
                        if kind == self.EV + 'delta':
                            deltas.append(msg.get('delta', ''))
                            rec.log('transcript', text=msg.get('delta'), final=True, audio_ms=pos)
                        elif kind == self.EV + 'intermediate':
                            rec.log('transcript', text=msg.get('intermediate'), final=False, audio_ms=pos)
                        elif kind == self.EV + 'completed':
                            completed.append(msg.get('transcript', ''))
                            commits['done'] += 1
                            rec.log('completed')
                            if commits['done'] >= commits['sent']:
                                all_done.set()
                        elif kind in ('error', self.EV + 'failed'):
                            rec.log(kind, error=str(msg.get('error', msg))[:200])
                        else:
                            rec.log(kind)
                except _closed_types():
                    pass
                all_done.set()

            task = asyncio.create_task(receiver())
            since = {'audio': 0.0, 'quiet_ms': 0.0}

            async def commit():
                commits['sent'] += 1
                all_done.clear()
                since['audio'] = since['quiet_ms'] = 0.0
                await ws.send(json.dumps({'type': 'input_audio_buffer.commit'}))
                rec.log('commit')

            async def send(chunk):
                await ws.send(json.dumps({'type': 'input_audio_buffer.append',
                                          'audio': base64.b64encode(chunk).decode('ascii')}))

            async def after(chunk):
                seconds = len(chunk) / 2 / RATE
                since['audio'] += seconds
                since['quiet_ms'] = since['quiet_ms'] + seconds * 1000 if rms(chunk) < self.QUIET_RMS else 0.0
                if since['audio'] >= self.COMMIT_MAX or (
                        since['audio'] >= self.COMMIT_MIN and since['quiet_ms'] >= self.QUIET_MS):
                    await commit()

            state['aborted'] = await self.paced_send(pcm, rec, budget, send, after)
            if since['audio'] > 0:
                await commit()
            try:
                await asyncio.wait_for(all_done.wait(), timeout=self.drain_timeout)
            except asyncio.TimeoutError:
                rec.log('check', error=f'completed {commits["done"]}/{commits["sent"]}에서 대기 종료')
            task.cancel()
        text = ''.join(deltas)
        if completed and ''.join(completed) != text:
            rec.log('check', error='completed 합이 delta 합과 다름(delta를 채택)')
        return text


def rms(chunk):
    samples = array('h')
    samples.frombytes(chunk[: len(chunk) // 2 * 2])
    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


# ------------------------------------------------------------------ 리턴제로
class Rtzr(Engine):
    """developers.rtzr.ai 스트리밍 WebSocket 문서(2026-10-16 확인) 기준. 실호출 미확인."""
    name, env, chunk_ms = 'rtzr', ('RTZR_CLIENT_ID', 'RTZR_CLIENT_SECRET'), 100
    URL = 'wss://openapi.vito.ai/v1/transcribe:streaming'
    AUTH_URL = 'https://openapi.vito.ai/v1/authenticate'

    def __init__(self, *args, fetch_token=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._fetch_token = fetch_token

    def fetch_token(self):
        if self._fetch_token:
            return self._fetch_token()
        body = urllib.parse.urlencode({'client_id': self.environ['RTZR_CLIENT_ID'],
                                       'client_secret': self.environ['RTZR_CLIENT_SECRET']}).encode()
        req = urllib.request.Request(self.AUTH_URL, data=body, method='POST',
                                     headers={'Content-Type': 'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())['access_token']

    def url(self):
        qs = urllib.parse.urlencode({
            'sample_rate': str(RATE), 'encoding': 'LINEAR16', 'model_name': 'sommers_ko',
            'domain': 'MEETING', 'use_itn': 'true', 'use_disfluency_filter': 'false',
            'use_profanity_filter': 'false', 'use_punctuation': 'false'})
        return f'{self.url_override or self.URL}?{qs}'

    async def session(self, pcm, rec, budget, state):
        finals = []
        token = await asyncio.to_thread(self.fetch_token)
        async with self.connect(self.url(), {'Authorization': f'Bearer {token}'}) as ws:
            async def receiver():
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        msg = json.loads(raw)
                        alts = msg.get('alternatives') or [{}]
                        text = alts[0].get('text')
                        final = bool(msg.get('final'))
                        pos = None
                        if final and msg.get('start_at') is not None:
                            pos = msg['start_at'] + msg.get('duration', 0)
                        rec.log('transcript', text=text, final=final, audio_ms=pos, seq=msg.get('seq'))
                        if final and text:
                            finals.append(text)
                except _closed_types():
                    pass

            task = asyncio.create_task(receiver())
            state['aborted'] = await self.paced_send(pcm, rec, budget, ws.send)
            await ws.send('EOS')
            await self._drain(task)
        return ' '.join(finals)


ENGINES = {cls.name: cls for cls in (Muse, Deepgram, Grok, Mai, Rtzr)}
