"""엔진 어댑터의 프로토콜 순서를 로컬 가짜 WebSocket 서버로 확인한다.

실제 API를 호출하지 않는다. 가짜 서버는 문서에 적힌 순서를 흉내 낼 뿐이라 실제 서버의
응답 형식까지 보장하지 않는다. 실서버 검증은 첫 실호출이 한다.
"""
import asyncio
import base64
import json
import unittest

import cost

try:
    from websockets.asyncio.server import serve
    import engines
except ImportError:   # websockets가 없으면 이 파일만 건너뛴다
    serve = None

PCM = b'\x10\x00' * 16000          # 1초
ENV = {'META_API_KEY': 'k-muse', 'DEEPGRAM_API_KEY': 'k-dg', 'XAI_API_KEY': 'k-xai',
       'AZURE_MAI_ENDPOINT': 'https://res.services.ai.azure.com', 'AZURE_MAI_API_KEY': 'k-mai',
       'AZURE_MAI_DEPLOYMENT_NAME': 'dep', 'RTZR_CLIENT_ID': 'id', 'RTZR_CLIENT_SECRET': 'sec'}


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


class MissingEnvTest(unittest.TestCase):
    @unittest.skipIf(serve is None, 'websockets 미설치')
    def test_reports_missing_variables(self):
        self.assertEqual(engines.Mai(environ={'AZURE_MAI_API_KEY': 'x'}).missing_env(),
                         ['AZURE_MAI_ENDPOINT', 'AZURE_MAI_DEPLOYMENT_NAME'])
        self.assertEqual(engines.Muse(environ=ENV).missing_env(), [])


if __name__ == '__main__':
    unittest.main()
