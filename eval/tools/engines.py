#!/usr/bin/env python3
"""실시간 STT 엔진 어댑터. 16kHz mono PCM16을 실시간 속도로 보내고 이벤트를 기록한다.

모든 엔진이 같은 계약을 따른다.
- 입력: PCM16 바이트, 예산 세션(cost._Session). 청크를 보내기 전에 charge()로 비용을 청구한다.
- 기록: 이벤트마다 첫 오디오 전송 기준 경과 ms(t_ms)와 엔진이 알린 오디오 위치(audio_ms).
  partial 지연 = t_ms - audio_ms (spike/score.py와 같은 정의).
- 반환: 최종 텍스트, 이벤트, 전송 초, 예산 중단 여부, 오류.

⚠ meta-muse·deepgram은 spike/probe.py에서 실호출로 확인한 순서를 옮겼다. grok·mai·rtzr·gemini는
문서만 보고, mai-vercel은 AI SDK 소스만 보고 짰고 실호출로 확인하지 않았다. **다음 세션의 첫 실호출이 검증 게이트다.**
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


ERROR_MAX = 300


class Recorder:
    def __init__(self, redact=None):
        self.events = []
        self.t0 = None
        self.redact = redact or (lambda text: text)

    def start(self):
        self.t0 = time.monotonic()

    def now_ms(self):
        return round((time.monotonic() - self.t0) * 1000, 1) if self.t0 else 0.0

    def log(self, kind, **fields):
        for k, v in fields.items():           # 모든 문자열 필드에서 키를 지운다(방어)
            if isinstance(v, str):
                fields[k] = self.redact(v)
        if fields.get('error') is not None:   # 키를 먼저 지우고 나서 자른다
            fields['error'] = self.redact(str(fields['error']))[:ERROR_MAX]
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

    def connect(self, url, headers=None, subprotocols=None):
        if self._connect:
            return self._connect(url, headers, subprotocols) if subprotocols else self._connect(url, headers)
        import websockets
        return websockets.connect(url, additional_headers=headers or {}, subprotocols=subprotocols,
                                  max_size=None, open_timeout=30)

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
        """세션을 돌리고 어떤 경로로 끝나도 수신 태스크를 정리한다.

        세션은 state['tasks']에 수신 태스크를, state['collect']에 지금까지 모은 확정 텍스트를
        돌려주는 함수를 등록한다. 송신 중 연결이 끊겨도 그때까지의 확정 텍스트를 남긴다.
        """
        rec = Recorder(self.redact)
        state = {'aborted': False, 'error': None, 'text': '', 'tasks': [], 'collect': None}
        try:
            state['text'] = await self.session(pcm, rec, budget, state)
        except Exception as exc:     # 엔진 하나의 실패가 다른 엔진을 멈추지 않게 한다
            state['error'] = self.redact(f'{type(exc).__name__}: {exc}')[:ERROR_MAX]
            rec.log('exception', error=state['error'])
            if state['collect']:
                state['text'] = state['collect']()
        finally:
            await self._reap(state, rec)
        result = {'text': state['text'] or '', 'events': rec.events, 'aborted': state['aborted'],
                  'error': state['error'], 'sent_seconds': budget.sent}
        if state.get('usage'):
            result['usage'] = state['usage']
        return result

    def redact(self, text):
        """오류 문구에 키가 섞여 나오지 않게 지운다(쿼리 문자열 인증 엔진 대비).

        url()과 같은 strip()된 값과 URL 인코딩된 형태를 모두 지운다. 긴 값부터 지운다.
        """
        forms = set()
        for name in self.env:
            value = self.environ.get(name, '').strip()
            if len(value) >= 8:
                forms.update({value, urllib.parse.quote(value, safe=''), urllib.parse.quote_plus(value)})
        for form in sorted(forms, key=len, reverse=True):
            text = text.replace(form, '***')
        return text

    def receiver_task(self, coro, state):
        task = asyncio.create_task(coro)
        state['tasks'].append(task)
        return task

    async def _reap(self, state, rec):
        """남은 수신 태스크를 끊고, 연결 종료가 아닌 수신 예외는 오류로 회수한다."""
        tasks = state['tasks']
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for task in tasks:
            if task.cancelled():
                continue
            exc = task.exception()
            if exc is None or isinstance(exc, _closed_types()):
                continue
            message = self.redact(f'수신 {type(exc).__name__}: {exc}')[:ERROR_MAX]
            rec.log('exception', error=message)
            if not state['error']:
                state['error'] = message
                if state['collect'] and not state['text']:
                    state['text'] = state['collect']()

    async def session(self, pcm, rec, budget, state):
        raise NotImplementedError

    async def _drain(self, task):
        """송신이 끝난 뒤 수신 종료를 기다린다. 상한을 넘으면 끊는다. 수신 예외는 _reap이 회수한다."""
        await asyncio.wait({task}, timeout=self.drain_timeout)


async def _recv_json(ws, timeout, rec=None):
    """JSON 메시지 하나를 받는다. Gemini Live처럼 JSON을 바이너리 프레임으로 보내는 서버도 받는다.

    JSON 객체가 아닌 프레임은 건너뛰고, 건너뛴 수를 rec에 남긴다.
    """
    skipped = 0
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        try:
            msg = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            msg = None
        if isinstance(msg, dict):
            if skipped and rec is not None:
                rec.log('skipped_frames', count=skipped)
            return msg
        skipped += 1


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
        state['collect'] = lambda: ' '.join(completes or finals)
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

            task = self.receiver_task(receiver(), state)
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
        state['collect'] = lambda: ' '.join(finals)
        headers = {'Authorization': f'Token {self.environ["DEEPGRAM_API_KEY"]}'}
        async with self.connect(self.url(), headers) as ws:
            async def receiver():
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        msg = json.loads(raw)
                        if msg.get('type') != 'Results':
                            rec.log(msg.get('type', '?'), error=str(msg))
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

            task = self.receiver_task(receiver(), state)
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
        state['collect'] = lambda: ' '.join(finals)
        headers = {'Authorization': f'Bearer {self.environ["XAI_API_KEY"]}'}
        async with self.connect(self.url(), headers) as ws:
            # transcript.created 전에는 오디오를 보내지 않는다
            while True:
                msg = await _recv_json(ws, 15, rec)
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

            task = self.receiver_task(receiver(), state)
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

    async def _wait(self, ws, kind, rec=None):
        while True:
            msg = await _recv_json(ws, 30, rec)
            if msg.get('type') in ('error', self.EV + 'failed'):
                raise RuntimeError(f'mai 오류: {msg.get("error", msg.get("type"))}')
            if msg.get('type') == kind:
                return msg

    async def session(self, pcm, rec, budget, state):
        deltas, completed = [], []
        state['collect'] = lambda: ''.join(deltas)
        commits = {'sent': 0, 'done': 0}
        all_done = asyncio.Event()
        headers = {'api-key': self.environ['AZURE_MAI_API_KEY'].strip()}
        async with self.connect(self.url(), headers) as ws:
            await self._wait(ws, 'session.created', rec)
            await ws.send(json.dumps({'type': 'session.update', 'session': {
                'type': 'transcription',
                'audio': {'input': {
                    'format': {'type': 'audio/pcm', 'rate': RATE},
                    'transcription': {'model': self.environ['AZURE_MAI_DEPLOYMENT_NAME'].strip(),
                                      'language': 'ko'},
                    'turn_detection': None}}}}))
            await self._wait(ws, 'session.updated', rec)

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
                            rec.log(kind, error=str(msg.get('error', msg)))
                        else:
                            rec.log(kind)
                except _closed_types():
                    pass
                all_done.set()

            task = self.receiver_task(receiver(), state)
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
        state['collect'] = lambda: ' '.join(finals)
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

            task = self.receiver_task(receiver(), state)
            state['aborted'] = await self.paced_send(pcm, rec, budget, ws.send)
            await ws.send('EOS')
            await self._drain(task)
        return ' '.join(finals)


# ------------------------------------------------------------------ Google Gemini Live
def _offset_ms(value):
    """protobuf Duration('1.500s' 또는 {seconds, nanos})를 ms로."""
    if value is None:
        return None
    if isinstance(value, str) and value.endswith('s'):
        return round(float(value[:-1]) * 1000)
    if isinstance(value, dict):
        return round(float(value.get('seconds', 0)) * 1000 + value.get('nanos', 0) / 1e6)
    return None


class Gemini(Engine):
    """Gemini Live 전사 전용 모델. ai.google.dev live-transcribe·api/live 문서(2026-10-16 확인) 기준. 실호출 미확인.

    인증은 문서대로 URL 쿼리 key다. URL을 기록하지 않고, 오류 문구의 키는 redact()가 지운다.
    세션 상한이 약 10분이라 stream_plan.SESSION_LIMITS가 540초로 나눈다.
    종료 이벤트가 문서에 없어, audioStreamEnd 뒤 IDLE_END초 동안 메시지가 없으면 끝난 것으로 본다.
    """
    name, env, chunk_ms = 'gemini', ('GEMINI_API_KEY',), 100
    MODEL = 'models/gemini-3.5-transcribe-live'
    URL = ('wss://generativelanguage.googleapis.com/ws/'
           'google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent')
    IDLE_END = 8.0

    def url(self):
        qs = urllib.parse.urlencode({'key': self.environ['GEMINI_API_KEY'].strip()})
        return f'{self.url_override or self.URL}?{qs}'

    async def session(self, pcm, rec, budget, state):
        finals = []
        state['collect'] = lambda: ' '.join(finals)
        async with self.connect(self.url()) as ws:
            await ws.send(json.dumps({'setup': {
                'model': self.MODEL,
                'generationConfig': {'responseModalities': ['TEXT']},
                'inputAudioTranscription': {'languageCodes': ['ko-KR'], 'mode': 'VERBATIM'}}}))
            while True:                          # setupComplete 전에는 오디오를 보내지 않는다
                msg = await _recv_json(ws, 30, rec)
                if 'error' in msg:
                    raise RuntimeError(f'gemini 오류: {msg["error"]}')   # 자르기는 run()이 redact 뒤에 한다
                if 'setupComplete' in msg:
                    break
            last = {'t': time.monotonic()}

            async def receiver():
                try:
                    async for raw in ws:
                        last['t'] = time.monotonic()
                        try:
                            msg = json.loads(raw)       # 바이너리 프레임의 JSON도 받는다
                        except (ValueError, UnicodeDecodeError):
                            rec.log('skipped_frames', count=1)
                            continue
                        if 'usageMetadata' in msg:
                            state['usage'] = msg['usageMetadata']   # 누적 값이라는 가정. 첫 실호출에서 확인
                        content = msg.get('serverContent') or {}
                        for key, final in (('interimInputTranscription', False), ('inputTranscription', True)):
                            part = content.get(key)
                            if part and part.get('text'):
                                rec.log('transcript', text=part['text'], final=final,
                                        audio_ms=_offset_ms(part.get('endOffset')))
                                if final:
                                    finals.append(part['text'])
                        if 'goAway' in msg:
                            rec.log('goAway', time_left=str(msg['goAway'].get('timeLeft')))
                        if content.get('turnComplete'):
                            rec.log('turnComplete')
                except _closed_types():
                    pass

            async def send(chunk):
                await ws.send(json.dumps({'realtimeInput': {'audio': {
                    'data': base64.b64encode(chunk).decode('ascii'),
                    'mimeType': f'audio/pcm;rate={RATE}'}}}))

            task = self.receiver_task(receiver(), state)
            state['aborted'] = await self.paced_send(pcm, rec, budget, send)
            await ws.send(json.dumps({'realtimeInput': {'audioStreamEnd': True}}))
            last['t'] = time.monotonic()
            deadline = time.monotonic() + self.drain_timeout
            while not task.done() and time.monotonic() < deadline:
                if time.monotonic() - last['t'] >= self.IDLE_END:
                    break
                await asyncio.sleep(0.05)
        return ' '.join(finals)


# ------------------------------------------------------------------ Vercel AI Gateway 경유 MAI
class MaiVercel(Engine):
    """Vercel AI Gateway의 microsoft/mai-transcribe-2-streaming. 실호출 미확인.

    와이어 프로토콜은 문서에 없어 AI SDK 소스에서 옮겼다(@ai-sdk/gateway 4.0.115
    gateway-transcription-model.ts·gateway-realtime-auth.ts, @ai-sdk/provider-utils 5.0.61
    transcription-stream-envelope.ts). 서버 키로 바로 연결한다. getToken(client secret 발급)은
    브라우저에 키를 주지 않으려는 단계라 서버 측 평가에는 필요 없다.
    - 인증: 서브프로토콜 `ai-gateway-auth.<키>`(게이트웨이가 Authorization으로 바꿔 읽는다).
      SDK가 헤더를 보낼 수 있는 런타임에서 함께 보내는 Authorization 헤더도 같이 보낸다.
    - 첫 텍스트 프레임 transcription-stream.start, 오디오는 raw PCM 바이너리 프레임(64KiB 이하),
      끝은 transcription-stream.audio-done. 서버는 finish 파트 뒤 1000으로 닫는다.
    - error 파트는 종결이다. 받으면 오디오를 멈춘다. finish 없이 닫히면 오류다.
    ⚠ 게이트웨이에는 commit 프레임이 없다. AI SDK의 Azure MAI 어댑터(@ai-sdk/azure 4.0.103)는
    오디오 끝에서 한 번만 commit한다. 게이트웨이도 그렇다면 확정 전사가 세션 끝에야 온다.
    """
    name, env, chunk_ms = 'mai-vercel', ('AI_GATEWAY_API_KEY',), 100
    drain_timeout = 120.0      # 끝에서 한 번 commit이면 세션 전체를 audio-done 뒤에 전사할 수 있다
    MODEL = 'microsoft/mai-transcribe-2-streaming'
    URL = 'wss://ai-gateway.vercel.sh/v4/ai/transcription-model'
    MARKER = 'ai-gateway-transcription.v1'
    AUTH_PREFIX = 'ai-gateway-auth.'

    def url(self):
        qs = urllib.parse.urlencode({'ai-model-id': self.MODEL})
        return f'{self.url_override or self.URL}?{qs}'

    def auth(self):
        key = self.environ['AI_GATEWAY_API_KEY'].strip()
        headers = {'Authorization': f'Bearer {key}', 'ai-gateway-protocol-version': '0.0.1',
                   'ai-gateway-auth-method': 'api-key', 'ai-model-id': self.MODEL,
                   'ai-transcription-model-specification-version': '4'}
        return headers, [self.MARKER, self.AUTH_PREFIX + key]

    async def session(self, pcm, rec, budget, state):
        deltas, finals, done = [], [], {}
        state['collect'] = lambda: ''.join(deltas) or ' '.join(finals)
        headers, protocols = self.auth()
        async with self.connect(self.url(), headers, protocols) as ws:
            await ws.send(json.dumps({
                'type': 'transcription-stream.start',
                'inputAudioFormat': {'type': 'audio/pcm', 'rate': RATE},
                'providerOptions': {'azure': {'language': 'ko'}}}))

            async def receiver():
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            rec.log('skipped_frames', count=1)
                            continue
                        msg = json.loads(raw)
                        kind = msg.get('type', '?')
                        if kind == 'transcript-delta':      # 오디오 위치가 없어 지연 집계에서 뺀다
                            deltas.append(msg.get('delta', ''))
                            rec.log('delta', text=msg.get('delta'))
                        elif kind == 'transcript-partial':
                            pos = None
                            if msg.get('startSecond') is not None and msg.get('durationInSeconds') is not None:
                                pos = round((msg['startSecond'] + msg['durationInSeconds']) * 1000)
                            rec.log('transcript', text=msg.get('text'), final=False, audio_ms=pos)
                        elif kind == 'transcript-final':
                            finals.append(msg.get('text', ''))
                            pos = msg.get('endSecond')
                            rec.log('transcript', text=msg.get('text'), final=True,
                                    audio_ms=round(pos * 1000) if pos is not None else None)
                        elif kind == 'finish':
                            done['text'] = msg.get('text') if isinstance(msg.get('text'), str) else ''
                            if msg.get('usage'):
                                state['usage'] = msg['usage']
                            rec.log('finish', duration=msg.get('durationInSeconds'))
                            return
                        elif kind == 'error':
                            err = msg.get('error')
                            done['error'] = err.get('message', err) if isinstance(err, dict) else err
                            rec.log('error', error=str(err))
                            return                      # error 파트는 종결이다. _drain도 바로 끝난다
                        elif kind == 'stream-start':
                            rec.log('stream-start', error=str(msg['warnings']) if msg.get('warnings') else None)
                        else:
                            rec.log(kind)
                except _closed_types():
                    pass

            async def send(chunk):
                if 'error' in done:             # error 파트는 종결이다(envelope rule 5)
                    raise RuntimeError(f'mai-vercel 오류: {done["error"]}')
                await ws.send(chunk)

            task = self.receiver_task(receiver(), state)
            try:
                state['aborted'] = await self.paced_send(pcm, rec, budget, send)
                if 'error' not in done:
                    await ws.send(json.dumps({'type': 'transcription-stream.audio-done'}))
                await self._drain(task)
            except Exception:
                if 'error' in done:     # error 파트 뒤 서버가 닫아 생긴 ConnectionClosed보다 서버 사유를 앞세운다
                    raise RuntimeError(f'mai-vercel 오류: {done["error"]}') from None
                raise
        if 'error' in done:
            raise RuntimeError(f'mai-vercel 오류: {done["error"]}')
        if 'text' not in done:
            raise RuntimeError('finish 파트 없이 연결이 끝남')
        collected = ''.join(deltas) or ' '.join(finals)
        if not done['text']:
            if collected:
                rec.log('check', error='finish 텍스트가 비어 모은 delta·final로 대체')
                return collected
            rec.log('empty', error='finish·delta·final 모두 비어 있음')
            return ''
        if collected and done['text'] != collected:
            rec.log('check', error='finish 텍스트가 delta 합과 다름(finish를 채택)')
        return done['text']


ENGINES = {cls.name: cls for cls in (Muse, Deepgram, Grok, Mai, Rtzr, Gemini, MaiVercel)}
