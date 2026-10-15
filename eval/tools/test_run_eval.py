import argparse
import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import run_eval
import stream_plan
from test_stream_plan import make_root

try:
    from websockets.asyncio.server import serve
except ImportError:
    serve = None


def call_main(argv, environ=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = run_eval.main(argv, environ=environ)
    return code, out.getvalue(), err.getvalue()


class DryRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(Path(self.tmp.name) / 'eval')

    def tearDown(self):
        self.tmp.cleanup()

    def runs(self):
        return Path(self.tmp.name) / 'runs'

    def test_dry_run_prints_table_and_writes_nothing(self):
        code, out, _ = call_main(['--stage', 'taste', '--root', str(self.root)], environ={})
        self.assertEqual(code, 0)
        self.assertIn('dry-run', out)
        for engine in run_eval.ALL_ENGINES:
            self.assertIn(engine, out)
        self.assertFalse(self.runs().exists())
        self.assertNotIn('하나', out)                       # 정답 텍스트를 내지 않는다

    def test_budget_without_confirm_refused(self):
        code, _, err = call_main(['--stage', 'taste', '--root', str(self.root), '--budget-krw', '1000'],
                                 environ={'META_API_KEY': 'k'})
        self.assertEqual(code, 2)
        self.assertIn('--confirm', err)
        self.assertFalse(self.runs().exists())

    def test_confirm_without_budget_refused(self):
        code, _, err = call_main(['--stage', 'taste', '--root', str(self.root), '--confirm'],
                                 environ={'META_API_KEY': 'k'})
        self.assertEqual(code, 2)
        self.assertFalse(self.runs().exists())

    def test_over_budget_refused(self):
        code, _, err = call_main(['--stage', 'taste', '--root', str(self.root), '--engines', 'muse',
                                  '--budget-krw', '1', '--confirm'], environ={'META_API_KEY': 'k'})
        self.assertEqual(code, 2)
        self.assertIn('넘어', err)
        self.assertFalse(self.runs().exists())

    def test_missing_keys_skipped(self):
        code, out, err = call_main(['--stage', 'taste', '--root', str(self.root), '--engines', 'meta-muse,mai-streaming',
                                    '--budget-krw', '1000', '--confirm'], environ={})
        self.assertEqual(code, 2)
        self.assertIn('META_API_KEY', out)
        self.assertIn('AZURE_MAI_ENDPOINT', out)
        self.assertIn('키가 있는 엔진이 없어', err)

    def test_unknown_engine(self):
        code, _, err = call_main(['--stage', 'taste', '--root', str(self.root), '--engines', 'whisper'])
        self.assertEqual(code, 2)

    def test_ledger_empty(self):
        code, out, _ = call_main(['--ledger', '--root', str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn('합계', out)

    def test_dry_run_shows_cumulative_cap(self):
        code, out, _ = call_main(['--stage', 'taste', '--root', str(self.root)], environ={})
        self.assertIn('누적 지출 0원 / 한도 20,000원', out)

    def test_invalid_numbers_rejected(self):
        for flag in ('--budget-krw', '--krw-per-usd', '--total-cap-krw'):
            for bad in ('nan', 'inf', '-inf', '0', '-5', 'abc'):
                with self.subTest(flag=flag, value=bad), self.assertRaises(SystemExit) as cm:
                    call_main(['--stage', 'taste', '--root', str(self.root), flag, bad])
                self.assertEqual(cm.exception.code, 2)

    def test_total_cap_blocks_start(self):
        import cost
        cost.append_ledger(self.runs(), {'engine': 'muse', 'sent_seconds': 1, 'spent_krw': 19990, 'spent_usd': 14.2})
        code, out, err = call_main(['--stage', 'taste', '--root', str(self.root), '--engines', 'muse',
                                    '--budget-krw', '1000', '--confirm'], environ={'META_API_KEY': 'k'})
        self.assertEqual(code, 2)
        self.assertIn('누적 지출 19,990원 / 한도 20,000원', out)
        self.assertIn('남은 누적 한도', err)
        self.assertEqual(len(list(self.runs().iterdir())), 1)          # 장부만 있고 실행 폴더 없음

    def test_usage_totals(self):
        pairs = [(None, {'usage': {'promptTokenCount': 10, 'responseTokenCount': 2, 'totalTokenCount': 12}}),
                 (None, {}),
                 (None, {'usage': {'promptTokenCount': 5, 'totalTokenCount': 5}})]
        self.assertEqual(run_eval.usage_totals(pairs),
                         {'tokens': {'promptTokenCount': 15, 'responseTokenCount': 2, 'totalTokenCount': 17}})
        self.assertEqual(run_eval.usage_totals([(None, {})]), {})

    def test_common_split_dry_run(self):
        code, out, _ = call_main(['--stage', 'taste', '--root', str(self.root), '--engines', 'muse,gemini'],
                                 environ={})
        self.assertIn('별도 분할: gemini (세션 상한 540초', out)
        code, out, _ = call_main(['--stage', 'taste', '--root', str(self.root), '--engines', 'muse,gemini',
                                  '--common-split'], environ={})
        self.assertEqual(code, 0)
        self.assertNotIn('별도 분할', out)
        rows = [line.split() for line in out.splitlines() if line.startswith(('muse ', 'gemini '))]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1], rows[1][1])            # 같은 세션 수
        self.assertEqual(rows[0][1], '3')                   # 총회 590초가 540초 상한으로 둘 + 장날

    def test_parse_aliases(self):
        self.assertEqual(run_eval.parse_engines('meta-muse, xai,mai-streaming,muse'), ['muse', 'grok', 'mai'])


@unittest.skipIf(serve is None, 'websockets 미설치')
class EndToEndTest(unittest.TestCase):
    def test_fake_muse_run_writes_outputs_outside_and_ledger(self):
        async def handler(ws):
            async for msg in ws:
                if isinstance(msg, bytes):
                    continue
                data = json.loads(msg)
                if data.get('type') == 'endStream':
                    await ws.send(json.dumps({'type': 'transcript', 'transcript': '하나 둘', 'final': True,
                                              'audioProcessedMs': 1000}))
                    await ws.send(json.dumps({'type': 'speechComplete', 'transcript': '하나 둘'}))
                    await ws.close(1000)

        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp) / 'eval')
            units = stream_plan.stage_units(root, 'taste')
            args = argparse.Namespace(stage='taste', budget_krw=1000.0, krw_per_usd=1400, parallel=True, jobs=2)

            async def go():
                async with serve(handler, '127.0.0.1', 0) as server:
                    url = f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'
                    kwargs = {'muse': {'environ': {'META_API_KEY': 'k'}, 'url': url, 'pace': 0}}
                    return await run_eval.execute(args, root, {'muse': units}, {'muse': 1.0}, 1000.0,
                                                  decode=stream_plan.decode_pcm,
                                                  engine_kwargs=kwargs)

            run_dir, summary = asyncio.run(go())
            self.assertEqual(run_dir.parent, Path(tmp).resolve() / 'runs')
            files = sorted(p.name for p in (run_dir / 'muse').iterdir())
            self.assertEqual(files, ['chonghoe-2026__first.json', 'jangnal-2026__all.json'])
            sets = summary['muse']['sets']
            self.assertEqual(sets['chonghoe-2026']['cer'], 0.0)
            self.assertIsNone(sets['jangnal-2026']['cer'])
            # 합성 WAV를 실제 디코더로 읽는다: 총회 앞 590초 + 장날 30초
            self.assertAlmostEqual(sets['chonghoe-2026']['sent_seconds'], 590.0)
            ledger = (Path(tmp) / 'runs' / 'ledger.jsonl').read_text().splitlines()
            self.assertEqual(len(ledger), 1)
            row = json.loads(ledger[0])
            self.assertEqual(row['engine'], 'muse')
            self.assertAlmostEqual(row['sent_seconds'], 620.0)
            self.assertEqual(row['status'], 'completed')
            self.assertNotIn('하나', (run_dir / 'summary.json').read_text())
            text = run_eval.format_summary(summary)
            self.assertIn('0.00%', text)


@unittest.skipIf(serve is None, 'websockets 미설치')
class GeminiLedgerKeyTest(unittest.TestCase):
    def test_key_never_written(self):
        import engines
        key = 'gemini-ledger-secret-999'

        async def handler(ws):
            await ws.recv()
            await ws.send(json.dumps({'setupComplete': {}}))
            async for msg in ws:
                if json.loads(msg).get('realtimeInput', {}).get('audioStreamEnd'):
                    await ws.send(json.dumps({'serverContent': {'inputTranscription': {'text': '하나 둘'}}}))
                    await ws.send(json.dumps({'usageMetadata': {'totalTokenCount': 9}}))

        idle = engines.Gemini.IDLE_END
        engines.Gemini.IDLE_END = 0.2
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = make_root(Path(tmp) / 'eval')
                plan = stream_plan.engine_units(root, 'taste', ['gemini'])
                args = argparse.Namespace(stage='taste', krw_per_usd=1400, parallel=False, jobs=1)

                async def go():
                    async with serve(handler, '127.0.0.1', 0) as server:
                        url = f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'
                        kwargs = {'gemini': {'environ': {'GEMINI_API_KEY': key}, 'url': url, 'pace': 0}}
                        return await run_eval.execute(args, root, plan, {'gemini': 1.0}, 1000.0,
                                                      decode=stream_plan.decode_pcm, engine_kwargs=kwargs)

                run_dir, summary = asyncio.run(go())
                ledger = (Path(tmp) / 'runs' / 'ledger.jsonl').read_text()
                self.assertEqual(json.loads(ledger)['tokens']['totalTokenCount'], 9 * len(plan['gemini']))
                for path in Path(tmp, 'runs').rglob('*'):
                    if path.is_file():
                        self.assertNotIn(key, path.read_text(encoding='utf-8'), path.name)
        finally:
            engines.Gemini.IDLE_END = idle


class FakeEngine:
    """make_engine을 대신한다. 네트워크 없이 청구·결과·예외 경로를 흉내 낸다."""
    def __init__(self, name, behavior):
        self.name, self.behavior = name, behavior

    async def run(self, pcm, session):
        seconds = len(pcm) / 2 / 16000
        if self.behavior == 'raise':
            session.charge(1.0)
            raise RuntimeError('boom')
        if self.behavior == 'slow':
            session.charge(0.5)
            await asyncio.sleep(10)
        if self.behavior == 'abort_first':
            session.charge(seconds / 2)
            self.behavior = 'ok'
            return {'text': '하나', 'events': [], 'aborted': True, 'error': None, 'sent_seconds': seconds / 2}
        session.charge(seconds)
        return {'text': '하나 둘', 'events': [], 'aborted': False, 'error': None, 'sent_seconds': seconds}


class ExecutePathsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(Path(self.tmp.name) / 'eval')
        self.units = stream_plan.stage_units(self.root, 'taste')
        self.orig = run_eval.make_engine

    def tearDown(self):
        run_eval.make_engine = self.orig
        self.tmp.cleanup()

    def ledger(self):
        path = Path(self.tmp.name) / 'runs' / 'ledger.jsonl'
        return [json.loads(x) for x in path.read_text().splitlines()]

    def execute(self, behaviors, parallel=True, decode=None):
        run_eval.make_engine = lambda name, kw=None: FakeEngine(name, behaviors[name])
        args = argparse.Namespace(stage='taste', budget_krw=1000.0, krw_per_usd=1400, parallel=parallel, jobs=1)
        units = self.units
        decode = decode or (lambda p: b'\x00\x00' * 16000 * 700)
        return asyncio.run(run_eval.execute(args, self.root, {n: units for n in behaviors}, {}, 1000.0,
                                            decode=decode))

    def test_exception_records_every_engine_once(self):
        with self.assertRaises(RuntimeError):
            self.execute({'muse': 'raise', 'grok': 'slow'})
        rows = {r['engine']: r for r in self.ledger()}
        self.assertEqual(len(self.ledger()), 2)
        self.assertEqual(rows['muse']['status'], 'exception')
        self.assertEqual(rows['muse']['sent_seconds'], 1.0)
        self.assertEqual(rows['grok']['status'], 'interrupted')    # 함께 돌던 엔진은 멈추고 기록
        self.assertEqual(rows['grok']['sent_seconds'], 0.5)

    def test_sequential_exception_records_unstarted_engine(self):
        with self.assertRaises(RuntimeError):
            self.execute({'muse': 'raise', 'grok': 'ok'}, parallel=False)
        rows = {r['engine']: r for r in self.ledger()}
        self.assertEqual(rows['grok']['sent_seconds'], 0.0)
        self.assertEqual(len(self.ledger()), 2)

    def test_completed_engine_recorded_once(self):
        run_dir, summary = self.execute({'muse': 'ok'})
        self.assertEqual([r['status'] for r in self.ledger()], ['completed'])
        self.assertEqual(summary['muse']['coverage']['ratio'], 1.0)

    def test_budget_abort_excluded_from_cer(self):
        run_dir, summary = self.execute({'muse': 'abort_first'}, parallel=False)
        cov = summary['muse']['coverage']
        self.assertEqual(cov['included_chars'], 0)       # 중단된 총회 단위는 합산에서 빠진다
        self.assertEqual(cov['total_chars'], 3)
        self.assertIsNone(summary['muse']['sets']['chonghoe-2026']['cer'])
        self.assertEqual(self.ledger()[0]['status'], 'budget')
        self.assertIn('채점 포함 0.0% (0/3자)', run_eval.format_summary(summary))

    def test_pcm_mismatch_skips_unit(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            run_dir, summary = self.execute({'muse': 'ok'}, decode=lambda p: b'\x00\x00' * 16000 * 10)
        self.assertIn('PCM 길이 불일치', err.getvalue())
        self.assertEqual(self.ledger()[0]['sent_seconds'], 0.0)   # 두 단위 모두 짧아 하나도 보내지 않음
        self.assertEqual(self.ledger()[0]['error_units'], 2)
        self.assertEqual(summary['muse']['coverage']['included_chars'], 0)


if __name__ == '__main__':
    unittest.main()
