"""엔진 어댑터의 프로토콜 순서를 로컬 가짜 WebSocket 서버로 확인한다.

실제 API를 호출하지 않는다. 가짜 서버는 문서에 적힌 순서를 흉내 낼 뿐이라 실제 서버의
응답 형식까지 보장하지 않는다. 실서버 검증은 첫 실호출이 한다.
"""
import asyncio
import base64
import json
import time
import unittest

import cost
import stream_score

try:
    from websockets.asyncio.server import serve
    import engines
except ImportError:   # websockets가 없으면 이 파일만 건너뛴다
    serve = None

PCM = b'\x10\x00' * 16000          # 1초
ENV = {'META_API_KEY': 'k-muse', 'DEEPGRAM_API_KEY': 'k-dg', 'XAI_API_KEY': 'k-xai',
       'AZURE_MAI_ENDPOINT': 'https://res.services.ai.azure.com', 'AZURE_MAI_API_KEY': 'k-mai',
       'AZURE_MAI_DEPLOYMENT_NAME': 'dep', 'RTZR_CLIENT_ID': 'id', 'RTZR_CLIENT_SECRET': 'sec',
       'GEMINI_API_KEY': 'gem-secret-key-123', 'AI_GATEWAY_API_KEY': 'vck_gateway-secret-456'}


async def with_server(handler, body):
    log = []

    async def wrapped(ws):
        await handler(ws, log)

    async with serve(wrapped, '127.0.0.1', 0) as server:
        port = server.sockets[0].getsockname()[1]
        result = await body(f'ws://127.0.0.1:{port}')
    return result, log


def guard(budget=1e9):
    return cost.BudgetGuard(budget)


@unittest.skipIf(serve is None, 'websockets 미설치')
class MuseTest(unittest.TestCase):
    def test_auth_frame_first_then_audio_then_end(self):
        async def handler(ws, log):
            log.append(('headers', ws.request.headers.get('Authorization')))
            async for msg in ws:
                if isinstance(msg, bytes):
                    log.append(('audio', len(msg)))
                    continue
                data = json.loads(msg)
                log.append(('json', data))
                if 'authorization' in data:
                    await ws.send(json.dumps({'sessionId': 's1'}))
                    await ws.send(json.dumps({'type': 'transcript', 'transcript': '안녕', 'final': False,
                                              'audioProcessedMs': 80}))
                if data.get('type') == 'endStream':
                    await ws.send(json.dumps({'type': 'transcript', 'transcript': '안녕하세요', 'final': True,
                                              'audioProcessedMs': 1000}))
                    await ws.send(json.dumps({'type': 'speechComplete', 'transcript': '안녕하세요'}))
                    await ws.close(1000)

        async def body(url):
            return await engines.Muse(environ=ENV, url=url, pace=0).run(PCM, guard().open_session('muse'))

        result, log = asyncio.run(with_server(handler, body))
        self.assertIsNone(result['error'])
        self.assertEqual(result['text'], '안녕하세요')
        self.assertIsNone(log[0][1])                                   # 헤더 인증 안 씀
        self.assertEqual(log[1][1]['authorization']['accessToken'], 'Bearer k-muse')
        self.assertEqual(log[1][1]['audioEncoding'], 'PCM_16KHZ')
        audio = [n for k, n in log if k == 'audio']
        self.assertEqual(sum(audio), len(PCM))
        self.assertEqual(audio[0], 1280 * 2)                           # 80ms
        self.assertEqual(log[-1], ('json', {'type': 'endStream'}))
        self.assertAlmostEqual(result['sent_seconds'], 1.0)


@unittest.skipIf(serve is None, 'websockets 미설치')
class DeepgramTest(unittest.TestCase):
    def test_token_header_and_close_stream(self):
        async def handler(ws, log):
            log.append(('headers', ws.request.headers.get('Authorization'), ws.request.path))
            async for msg in ws:
                if isinstance(msg, bytes):
                    continue
                log.append(('json', json.loads(msg)))
                await ws.send(json.dumps({'type': 'Results', 'is_final': True, 'start': 0, 'duration': 1,
                                          'channel': {'alternatives': [{'transcript': '하나'}]}}))
                await ws.close(1000)

        async def body(url):
            return await engines.Deepgram(environ=ENV, url=url, pace=0).run(PCM, guard().open_session('deepgram'))

        result, log = asyncio.run(with_server(handler, body))
        self.assertEqual(log[0][1], 'Token k-dg')
        self.assertIn('language=ko', log[0][2])
        self.assertIn('sample_rate=16000', log[0][2])
        self.assertEqual(log[1][1], {'type': 'CloseStream'})
        self.assertEqual(result['text'], '하나')


@unittest.skipIf(serve is None, 'websockets 미설치')
class GrokTest(unittest.TestCase):
    def test_waits_for_created_before_audio(self):
        async def handler(ws, log):
            log.append(('headers', ws.request.headers.get('Authorization'), ws.request.path))
            # created 전에 오디오가 오면 실패로 기록
            try:
                early = await asyncio.wait_for(ws.recv(), timeout=0.2)
                log.append(('early', early))
            except asyncio.TimeoutError:
                pass
            await ws.send(json.dumps({'type': 'transcript.created'}))
            async for msg in ws:
                if isinstance(msg, bytes):
                    log.append(('audio', len(msg)))
                    continue
                data = json.loads(msg)
                log.append(('json', data))
                if data.get('type') == 'audio.done':
                    await ws.send(json.dumps({'type': 'transcript.partial', 'text': '하나', 'is_final': False,
                                              'speech_final': False, 'start': 0.0, 'duration': 0.5}))
                    await ws.send(json.dumps({'type': 'transcript.partial', 'text': '하나 둘', 'is_final': True,
                                              'speech_final': True, 'start': 0.0, 'duration': 1.0}))
                    await ws.send(json.dumps({'type': 'transcript.done', 'text': '하나 둘', 'duration': 1.0}))
                    await ws.close(1000)

        async def body(url):
            return await engines.Grok(environ=ENV, url=url, pace=0).run(PCM, guard().open_session('grok'))

        result, log = asyncio.run(with_server(handler, body))
        self.assertNotIn('early', [k for k, *_ in log])
        self.assertEqual(log[0][1], 'Bearer k-xai')
        for q in ('model=grok-voice-transcribe-2.0', 'encoding=pcm', 'interim_results=true', 'language=ko'):
            self.assertIn(q, log[0][2])
        self.assertEqual([e[1] for e in log if e[0] == 'audio'][0], 3200)  # 100ms
        self.assertEqual(log[-1], ('json', {'type': 'audio.done'}))
        self.assertEqual(result['text'], '하나 둘')
        partial = [e for e in result['events'] if e['kind'] == 'transcript' and not e['final']]
        self.assertEqual(partial[0]['audio_ms'], 500)

    def test_error_before_created(self):
        async def handler(ws, log):
            await ws.send(json.dumps({'type': 'error', 'message': 'bad key'}))
            await asyncio.sleep(0.1)

        async def body(url):
            return await engines.Grok(environ=ENV, url=url, pace=0).run(PCM, guard().open_session('grok'))

        result, _ = asyncio.run(with_server(handler, body))
        self.assertIn('bad key', result['error'])
        self.assertEqual(result['sent_seconds'], 0)


@unittest.skipIf(serve is None, 'websockets 미설치')
class MaiTest(unittest.TestCase):
    def test_session_update_then_appends_and_commits(self):
        async def handler(ws, log):
            log.append(('headers', ws.request.headers.get('api-key'), ws.request.path))
            await ws.send(json.dumps({'type': 'session.created', 'session': {'id': 'x'}}))
            async for msg in ws:
                data = json.loads(msg)
                kind = data['type']
                if kind == 'input_audio_buffer.append':
                    log.append(('append', len(base64.b64decode(data['audio']))))
                    continue
                log.append((kind, data))
                if kind == 'session.update':
                    await ws.send(json.dumps({'type': 'session.updated'}))
                elif kind == 'input_audio_buffer.commit':
                    n = sum(1 for k, *_ in log if k == 'input_audio_buffer.commit')
                    ev = 'conversation.item.input_audio_transcription.'
                    await ws.send(json.dumps({'type': ev + 'intermediate', 'intermediate': '임시'}))
                    await ws.send(json.dumps({'type': ev + 'delta', 'delta': f'조각{n} '}))
                    await ws.send(json.dumps({'type': 'input_audio_buffer.committed'}))
                    await ws.send(json.dumps({'type': ev + 'completed', 'transcript': f'조각{n} '}))

        pcm = b'\x00\x00' * 16000 * 4      # 4초 무음: 3초 + 조용 300ms에서 commit, 끝에 한 번 더

        async def body(url):
            return await engines.Mai(environ=ENV, url=url, pace=0).run(pcm, guard().open_session('mai'))

        result, log = asyncio.run(with_server(handler, body))
        self.assertIsNone(result['error'])
        self.assertEqual(log[0][1], 'k-mai')
        kinds = [k for k, *_ in log[1:]]
        self.assertEqual(kinds[0], 'session.update')
        update = log[1][1]['session']
        self.assertEqual(update['type'], 'transcription')
        self.assertEqual(update['audio']['input']['format'], {'type': 'audio/pcm', 'rate': 16000})
        self.assertEqual(update['audio']['input']['transcription'], {'model': 'dep', 'language': 'ko'})
        self.assertIsNone(update['audio']['input']['turn_detection'])
        self.assertEqual(kinds[1], 'append')
        self.assertEqual(log[2][1], 640)                               # 20ms
        self.assertEqual(kinds.count('input_audio_buffer.commit'), 2)
        self.assertEqual(kinds[-1], 'input_audio_buffer.commit')
        self.assertEqual(result['text'], '조각1 조각2 ')                 # delta를 그대로 이어 붙임

    def test_endpoint_url(self):
        self.assertEqual(engines.Mai(environ=ENV).url(),
                         'wss://res.services.ai.azure.com/mai/v1/realtime?intent=transcription')
        bad = dict(ENV, AZURE_MAI_ENDPOINT='https://res.services.ai.azure.com/openai')
        with self.assertRaises(ValueError):
            engines.Mai(environ=bad).url()


@unittest.skipIf(serve is None, 'websockets 미설치')
class RtzrTest(unittest.TestCase):
    def test_token_then_bearer_then_eos(self):
        async def handler(ws, log):
            log.append(('headers', ws.request.headers.get('Authorization'), ws.request.path))
            async for msg in ws:
                if isinstance(msg, bytes):
                    continue
                log.append(('text', msg))
                await ws.send(json.dumps({'seq': 0, 'start_at': 0, 'duration': 0, 'final': False,
                                          'alternatives': [{'text': '하'}]}))
                await ws.send(json.dumps({'seq': 0, 'start_at': 100, 'duration': 800, 'final': True,
                                          'alternatives': [{'text': '하나'}]}))
                await ws.close(1000)

        async def body(url):
            eng = engines.Rtzr(environ=ENV, url=url, pace=0, fetch_token=lambda: 'tok')
            return await eng.run(PCM, guard().open_session('rtzr'))

        result, log = asyncio.run(with_server(handler, body))
        self.assertEqual(log[0][1], 'Bearer tok')
        for q in ('sample_rate=16000', 'encoding=LINEAR16', 'model_name=sommers_ko'):
            self.assertIn(q, log[0][2])
        self.assertEqual(log[1], ('text', 'EOS'))
        self.assertEqual(result['text'], '하나')
        finals = [e for e in result['events'] if e['kind'] == 'transcript' and e['final']]
        self.assertEqual(finals[0]['audio_ms'], 900)


@unittest.skipIf(serve is None, 'websockets 미설치')
class GeminiTest(unittest.TestCase):
    def setUp(self):
        self.idle = engines.Gemini.IDLE_END
        engines.Gemini.IDLE_END = 0.3

    def tearDown(self):
        engines.Gemini.IDLE_END = self.idle

    def test_setup_complete_then_audio_then_stream_end(self):
        async def handler(ws, log):
            log.append(('path', ws.request.path))
            try:
                early = await asyncio.wait_for(ws.recv(), timeout=0.2)    # setup 메시지
                log.append(('setup', json.loads(early)))
                extra = await asyncio.wait_for(ws.recv(), timeout=0.2)   # setupComplete 전 오디오가 오면 기록
                log.append(('early', extra))
            except asyncio.TimeoutError:
                pass
            await ws.send(json.dumps({'setupComplete': {}}).encode())   # 바이너리 프레임 JSON
            async for msg in ws:
                data = json.loads(msg)
                ri = data.get('realtimeInput', {})
                if 'audio' in ri:
                    log.append(('audio', len(base64.b64decode(ri['audio']['data'])), ri['audio']['mimeType']))
                    continue
                log.append(('json', data))
                if ri.get('audioStreamEnd'):
                    await ws.send(json.dumps({'serverContent': {'interimInputTranscription': {
                        'text': '하나', 'endOffset': '0.400s'}}}).encode())
                    await ws.send(json.dumps({'serverContent': {'inputTranscription': {
                        'text': '하나 둘', 'endOffset': {'seconds': 1, 'nanos': 0}}}}))
                    await ws.send(json.dumps({'usageMetadata': {'promptTokenCount': 32,
                                                                'responseTokenCount': 4, 'totalTokenCount': 36}}))

        async def body(url):
            return await engines.Gemini(environ=ENV, url=url, pace=0).run(PCM, guard().open_session('gemini'))

        result, log = asyncio.run(with_server(handler, body))
        self.assertIsNone(result['error'])
        self.assertNotIn('early', [e[0] for e in log])
        self.assertIn('key=gem-secret-key-123', log[0][1])
        setup = log[1][1]['setup']
        self.assertEqual(setup['model'], 'models/gemini-3.5-transcribe-live')
        self.assertEqual(setup['generationConfig'], {'responseModalities': ['TEXT']})
        self.assertEqual(setup['inputAudioTranscription'], {'languageCodes': ['ko-KR'], 'mode': 'VERBATIM'})
        audio = [e for e in log if e[0] == 'audio']
        self.assertEqual(audio[0][1:], (3200, 'audio/pcm;rate=16000'))      # 100ms
        self.assertEqual(sum(e[1] for e in audio), len(PCM))
        self.assertEqual(log[-1], ('json', {'realtimeInput': {'audioStreamEnd': True}}))
        self.assertEqual(result['text'], '하나 둘')
        lags = [(e['final'], e['audio_ms']) for e in result['events'] if e['kind'] == 'transcript']
        self.assertEqual(lags, [(False, 400), (True, 1000)])
        self.assertEqual(result['usage']['totalTokenCount'], 36)
        self.assertNotIn('gem-secret-key-123', json.dumps(result))       # 결과·이벤트에 키 없음

    def test_key_redacted_from_errors(self):
        async def handler(ws, log):
            await ws.recv()
            await ws.send(json.dumps({'error': {'message': 'bad request for key gem-secret-key-123'}}))

        async def body(url):
            return await engines.Gemini(environ=ENV, url=url, pace=0).run(PCM, guard().open_session('gemini'))

        result, _ = asyncio.run(with_server(handler, body))
        self.assertIn('gemini 오류', result['error'])
        self.assertNotIn('gem-secret-key-123', result['error'])
        self.assertIn('***', result['error'])
        self.assertEqual(result['sent_seconds'], 0)

    def run_gemini(self, handler):
        async def body(url):
            return await engines.Gemini(environ=ENV, url=url, pace=0).run(PCM, guard().open_session('gemini'))
        return asyncio.run(with_server(handler, body))

    def test_key_straddling_truncation_boundary(self):
        key = ENV['GEMINI_API_KEY']
        for pad in range(150, 230, 7):          # 키가 200자 경계 앞뒤에 걸치도록 위치를 옮긴다
            async def handler(ws, log, pad=pad):
                await ws.recv()
                await ws.send(json.dumps({'error': {'message': 'x' * pad + key + ' 뒤'}}))

            result, _ = self.run_gemini(handler)
            dumped = json.dumps(result, ensure_ascii=False)
            for k in range(6, len(key) + 1):
                self.assertNotIn(key[:k], dumped, (pad, k))
            self.assertLessEqual(len(result['error']), engines.ERROR_MAX)

    def test_connection_drop_mid_send_keeps_finals(self):
        async def handler(ws, log):
            await ws.recv()
            await ws.send(json.dumps({'setupComplete': {}}))
            await ws.recv()
            await ws.send(json.dumps({'serverContent': {'inputTranscription': {'text': '하나'}}}))
            await asyncio.sleep(0.05)
            await ws.close(1011)                 # goAway 뒤 끊김을 흉내 낸다

        async def body(url):
            eng = engines.Gemini(environ=ENV, url=url, pace=0.5)   # 송신 중에 끊기도록 천천히 보낸다
            return await eng.run(PCM, guard().open_session('gemini'))

        result, _ = asyncio.run(with_server(handler, body))
        self.assertIn('ConnectionClosed', result['error'])
        self.assertEqual(result['text'], '하나')
        self.assertLess(result['sent_seconds'], 1.0)

    def test_receiver_exception_recorded(self):
        async def handler(ws, log):
            await ws.recv()
            await ws.send(json.dumps({'setupComplete': {}}))
            await ws.send(json.dumps({'serverContent': {'inputTranscription': {'text': '하나'}}}))
            await ws.send(json.dumps({'serverContent': {'inputTranscription': 'not-an-object'}}))
            async for _ in ws:
                pass

        result, _ = self.run_gemini(handler)
        self.assertIn('수신 AttributeError', result['error'])
        self.assertEqual(result['text'], '하나')

    def test_offset_parsing(self):
        self.assertEqual(engines._offset_ms('12.345s'), 12345)
        self.assertEqual(engines._offset_ms({'seconds': '2', 'nanos': 500000000}), 2500)
        self.assertIsNone(engines._offset_ms(None))


@unittest.skipIf(serve is None, 'websockets 미설치')
class MaiVercelTest(unittest.TestCase):
    KEY = 'vck_gateway-secret-456'

    def run_engine(self, handler, pcm=PCM, budget=1e9):
        async def wrapped(ws, log):
            log.append(('handshake', ws.request.path, ws.request.headers.get('Sec-WebSocket-Protocol'),
                        ws.request.headers.get('Authorization'), ws.subprotocol))
            await handler(ws, log)

        async def body(url):
            return await engines.MaiVercel(environ=ENV, url=url, pace=0).run(
                pcm, guard(budget).open_session('mai-vercel'))

        async def go():
            log = []

            async def h(ws):
                await wrapped(ws, log)

            async with serve(h, '127.0.0.1', 0, subprotocols=['ai-gateway-transcription.v1']) as server:
                port = server.sockets[0].getsockname()[1]
                result = await body(f'ws://127.0.0.1:{port}')
            return result, log
        return asyncio.run(go())

    def test_start_frame_binary_audio_then_audio_done(self):
        async def handler(ws, log):
            async for msg in ws:
                if isinstance(msg, bytes):
                    log.append(('audio', len(msg)))
                    continue
                data = json.loads(msg)
                log.append(('json', data))
                if data['type'] == 'transcription-stream.start':
                    await ws.send(json.dumps({'type': 'stream-start', 'warnings': []}))
                    await ws.send(json.dumps({'type': 'transcript-partial', 'text': '하',
                                              'startSecond': 0, 'durationInSeconds': 0.4}))
                elif data['type'] == 'transcription-stream.audio-done':
                    await ws.send(json.dumps({'type': 'transcript-delta', 'id': 'i1', 'delta': '하나 '}))
                    await ws.send(json.dumps({'type': 'transcript-delta', 'id': 'i1', 'delta': '둘'}))
                    await ws.send(json.dumps({'type': 'transcript-final', 'id': 'i1', 'text': '하나 둘',
                                              'endSecond': 1.0}))
                    await ws.send(json.dumps({'type': 'finish', 'text': '하나 둘', 'segments': [],
                                              'language': 'ko', 'durationInSeconds': 1}))
                    await ws.close(1000)

        result, log = self.run_engine(handler)
        self.assertIsNone(result['error'])
        path, protocols, authz, chosen = log[0][1:]
        self.assertTrue(path.startswith('/?'))
        self.assertIn('ai-model-id=microsoft%2Fmai-transcribe-2-streaming', path)
        self.assertNotIn(self.KEY, path)                                  # 키는 URL에 없다
        self.assertEqual([p.strip() for p in protocols.split(',')],
                         ['ai-gateway-transcription.v1', 'ai-gateway-auth.' + self.KEY])
        self.assertEqual(authz, 'Bearer ' + self.KEY)
        self.assertEqual(chosen, 'ai-gateway-transcription.v1')
        self.assertEqual(log[1], ('json', {'type': 'transcription-stream.start',
                                           'inputAudioFormat': {'type': 'audio/pcm', 'rate': 16000},
                                           'providerOptions': {'azure': {'language': 'ko'}}}))
        audio = [e[1] for e in log if e[0] == 'audio']
        self.assertEqual(audio[0], 3200)                                  # 100ms, 64KiB 이하
        self.assertEqual(sum(audio), len(PCM))
        self.assertEqual(log[-1], ('json', {'type': 'transcription-stream.audio-done'}))
        self.assertEqual(result['text'], '하나 둘')
        lags = [(e['final'], e['audio_ms']) for e in result['events'] if e['kind'] == 'transcript']
        self.assertEqual(lags, [(False, 400), (True, 1000)])          # final 지연도 집계된다
        self.assertEqual([e['text'] for e in result['events'] if e['kind'] == 'delta'], ['하나 ', '둘'])
        stats = stream_score.latency_stats(result['events'])
        self.assertEqual((stats['partial']['n'], stats['final']['n']), (1, 1))
        self.assertNotIn(self.KEY, json.dumps(result, ensure_ascii=False))

    def test_error_part_stops_audio_and_key_redacted(self):
        pcm = PCM * 4                                                     # 4초를 0.8초에 걸쳐 보낸다

        async def handler(ws, log):
            await ws.recv()                                               # start
            await ws.recv()                                               # 첫 오디오
            await ws.send(json.dumps({'type': 'error', 'error': {
                'type': 'authentication_error', 'message': 'invalid key ' + self.KEY}}))
            async for msg in ws:
                if isinstance(msg, str):
                    log.append(('text', json.loads(msg)['type']))
            # 오류 뒤 닫지 않는다. 클라이언트가 스스로 멈추고 닫아야 한다

        async def body(url):
            eng = engines.MaiVercel(environ=ENV, url=url, pace=0.2)
            return await eng.run(pcm, guard().open_session('mai-vercel'))

        result, log = asyncio.run(with_server(handler, body))
        self.assertTrue(result['error'].startswith('RuntimeError: mai-vercel 오류'), result['error'])
        self.assertIn('***', result['error'])
        self.assertNotIn(('text', 'transcription-stream.audio-done'), log)   # 오류 뒤 끝 신호를 보내지 않는다
        self.assertLess(result['sent_seconds'], 2.0)                     # 4초 중 절반 전에 멈춘다(여유 큼)
        self.assertNotIn(self.KEY, json.dumps(result, ensure_ascii=False))

    def test_error_then_server_close_reports_server_reason(self):
        async def handler(ws, log):
            await ws.recv()
            await ws.recv()
            await ws.send(json.dumps({'type': 'error', 'error': {'type': 'rate_limit_exceeded',
                                                                  'message': 'slow down'}}))
            await ws.close(1008)

        async def body(url):
            eng = engines.MaiVercel(environ=ENV, url=url, pace=0.5)
            return await eng.run(PCM * 2, guard().open_session('mai-vercel'))

        result, _ = asyncio.run(with_server(handler, body))
        self.assertIn('mai-vercel 오류: slow down', result['error'])
        self.assertNotIn('ConnectionClosed', result['error'])

    def test_error_after_audio_done_without_close_returns_fast(self):
        async def handler(ws, log):
            async for msg in ws:
                if isinstance(msg, str) and json.loads(msg)['type'] == 'transcription-stream.audio-done':
                    await ws.send(json.dumps({'type': 'error', 'error': {'message': 'upstream failed'}}))
                    await ws.wait_closed()                                # 서버는 닫지 않는다
                    return

        async def body(url):
            eng = engines.MaiVercel(environ=ENV, url=url, pace=0)
            eng.drain_timeout = 60.0
            start = time.monotonic()
            result = await eng.run(PCM, guard().open_session('mai-vercel'))
            return result, time.monotonic() - start

        (result, elapsed), _ = asyncio.run(with_server(handler, body))
        self.assertIn('upstream failed', result['error'])
        self.assertLess(elapsed, 10.0)                                    # drain 60초를 기다리지 않는다

    def finish_with(self, parts):
        async def handler(ws, log):
            async for msg in ws:
                if isinstance(msg, str) and json.loads(msg)['type'] == 'transcription-stream.audio-done':
                    for part in parts:
                        await ws.send(json.dumps(part))
                    await ws.close(1000)
                    return
        return self.run_engine(handler)[0]

    def test_empty_finish_falls_back_to_collected(self):
        result = self.finish_with([{'type': 'transcript-delta', 'delta': '하나 둘'},
                                   {'type': 'finish', 'text': '', 'segments': []}])
        self.assertEqual(result['text'], '하나 둘')
        self.assertTrue(any(e['kind'] == 'check' and '대체' in e['error'] for e in result['events']))
        result = self.finish_with([{'type': 'transcript-final', 'text': '셋'},
                                   {'type': 'finish', 'segments': []}])     # text 없음
        self.assertEqual(result['text'], '셋')
        self.assertIsNone(result['error'])

    def test_all_empty_marked(self):
        result = self.finish_with([{'type': 'finish', 'text': '', 'segments': []}])
        self.assertEqual(result['text'], '')
        self.assertIsNone(result['error'])
        self.assertEqual([e['kind'] for e in result['events'] if e['kind'] in ('empty', 'check')], ['empty'])

    def test_close_without_finish_is_error(self):
        async def handler(ws, log):
            async for msg in ws:
                if isinstance(msg, str) and json.loads(msg)['type'] == 'transcription-stream.audio-done':
                    await ws.send(json.dumps({'type': 'transcript-delta', 'delta': '하나'}))
                    await ws.close(1011)
                    return

        result, _ = self.run_engine(handler)
        self.assertIn('finish 파트 없이', result['error'])
        self.assertEqual(result['text'], '하나')                          # 그때까지의 delta는 남긴다

    def test_budget_stop_still_sends_audio_done(self):
        async def handler(ws, log):
            async for msg in ws:
                if isinstance(msg, bytes):
                    log.append(('audio', len(msg)))
                elif json.loads(msg)['type'] == 'transcription-stream.audio-done':
                    log.append(('done',))
                    await ws.send(json.dumps({'type': 'finish', 'text': '', 'segments': []}))
                    await ws.close(1000)

        # 시간당 0.54*1400=756원. 0.1원이면 0.476초까지만 보낸다
        result, log = self.run_engine(handler, budget=0.1)
        self.assertTrue(result['aborted'])
        self.assertEqual(sum(e[1] for e in log if e[0] == 'audio'), 4 * 3200)
        self.assertEqual(log[-1], ('done',))


@unittest.skipIf(serve is None, 'websockets 미설치')
class BudgetStopTest(unittest.TestCase):
    def test_stops_sending_at_budget(self):
        async def handler(ws, log):
            async for msg in ws:
                if isinstance(msg, bytes):
                    log.append(len(msg))
                elif json.loads(msg).get('type') == 'CloseStream':
                    await ws.close(1000)

        # deepgram 시간당 0.462*1400=646.8원. 0.1원이면 약 0.557초만 보낸다
        async def body(url):
            return await engines.Deepgram(environ=ENV, url=url, pace=0).run(
                PCM, guard(0.1).open_session('deepgram'))

        result, log = asyncio.run(with_server(handler, body))
        self.assertTrue(result['aborted'])
        self.assertEqual(sum(log), 6 * 2560)                       # 80ms 청크 6개
        self.assertLess(result['sent_seconds'], 0.6)


@unittest.skipIf(serve is None, 'websockets 미설치')
class RedactTest(unittest.TestCase):
    def test_strip_and_url_encoded_forms(self):
        env = {'GEMINI_API_KEY': '  ab/cd+ef=gh ij  '}
        eng = engines.Gemini(environ=env)
        self.assertIn('ab%2Fcd%2Bef%3Dgh+ij', eng.url())
        text = 'raw ab/cd+ef=gh ij, quote ab%2Fcd%2Bef%3Dgh%20ij, plus ab%2Fcd%2Bef%3Dgh+ij'
        self.assertEqual(eng.redact(text), 'raw ***, quote ***, plus ***')

    def test_recorder_redacts_every_string_field(self):
        key = 'k' * 20
        rec = engines.Recorder(engines.Gemini(environ={'GEMINI_API_KEY': key}).redact)
        rec.log('transcript', text='말한 ' + key, other=f'x{key}', audio_ms=5)
        self.assertEqual(rec.events[0]['text'], '말한 ***')
        self.assertEqual(rec.events[0]['other'], 'x***')
        self.assertEqual(rec.events[0]['audio_ms'], 5)

    def test_recorder_redacts_before_truncating(self):
        key = 'k' * 20
        rec = engines.Recorder(engines.Gemini(environ={'GEMINI_API_KEY': key}).redact)
        rec.log('error', error='x' * (engines.ERROR_MAX - 5) + key)
        self.assertNotIn('kkkk', rec.events[0]['error'])


@unittest.skipIf(serve is None, 'websockets 미설치')
class SkippedFrameTest(unittest.TestCase):
    def test_non_json_frames_counted(self):
        async def handler(ws, log):
            await ws.send('hello')
            await ws.send(b'\x00\x01')
            await ws.send(json.dumps([1, 2]))
            await ws.send(json.dumps({'type': 'transcript.created'}))
            async for msg in ws:
                if isinstance(msg, str) and json.loads(msg).get('type') == 'audio.done':
                    await ws.send(json.dumps({'type': 'transcript.done', 'text': '', 'duration': 1}))

        async def body(url):
            return await engines.Grok(environ=ENV, url=url, pace=0).run(PCM, guard().open_session('grok'))

        result, _ = asyncio.run(with_server(handler, body))
        skipped = [e for e in result['events'] if e['kind'] == 'skipped_frames']
        self.assertEqual(skipped[0]['count'], 3)


class MissingEnvTest(unittest.TestCase):
    @unittest.skipIf(serve is None, 'websockets 미설치')
    def test_reports_missing_variables(self):
        self.assertEqual(engines.Mai(environ={'AZURE_MAI_API_KEY': 'x'}).missing_env(),
                         ['AZURE_MAI_ENDPOINT', 'AZURE_MAI_DEPLOYMENT_NAME'])
        self.assertEqual(engines.Muse(environ=ENV).missing_env(), [])


if __name__ == '__main__':
    unittest.main()
