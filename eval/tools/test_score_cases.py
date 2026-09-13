"""공개 정답 채점의 분모, 누락 실패, 입력 경계 회귀 검증."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from score_cases import main


def reference(id='one', text='가 나', **changes):
    row = dict(id=id, dataset='synthetic', split='test', cluster='unit', text=text,
               audio='/synthetic.wav', duration_seconds=1.0,
               evaluation_ready=True, eligible_metrics=['cer', 'wer'])
    row.update(changes)
    return row


class ScoreCasesTests(unittest.TestCase):
    def run_score(self, refs, hyps, *args, raw_ref=None):
        with tempfile.TemporaryDirectory() as tmp:
            ref_path, hyp_path = Path(tmp) / 'ref.jsonl', Path(tmp) / 'hyp.jsonl'
            ref_path.write_text(raw_ref if raw_ref is not None else ''.join(
                json.dumps(row, ensure_ascii=False) + '\n' for row in refs), encoding='utf-8')
            hyp_path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in hyps),
                                encoding='utf-8')
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(['--ref', str(ref_path), '--hyp', str(hyp_path), *args])
            return code, stdout.getvalue(), stderr.getvalue()

    def assert_failure(self, refs, hyps, *args, raw_ref=None):
        code, stdout, stderr = self.run_score(refs, hyps, *args, raw_ref=raw_ref)
        self.assertEqual(code, 2)
        self.assertEqual(stdout, '')
        self.assertIn('오류:', stderr)
        return stderr

    def test_insertions_and_micro_denominators(self):
        refs = [reference(text='가'), reference('two', '가 나 다', dataset='second', split='dev')]
        hyps = [dict(id='one', text='가 나 다'), dict(id='two', text='가 나 다')]
        code, stdout, _ = self.run_score(refs, hyps)
        self.assertEqual(code, 0)
        result = json.loads(stdout)
        self.assertEqual(result['overall']['character_errors'], 2)
        self.assertEqual(result['overall']['reference_characters'], 4)
        self.assertEqual(result['overall']['cer'], 0.5)
        self.assertEqual(result['overall']['wer'], 0.5)
        self.assertEqual(result['by_dataset_split'][1]['cer'], 2.0)

    def test_empty_hyp_is_deletion_not_missing(self):
        code, stdout, _ = self.run_score([reference()], [dict(id='one', text='')])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)['overall']['cer'], 1.0)

    def test_missing_and_extra_ids_are_rejected_without_values(self):
        for hyps in ([dict(id='secret-id', text='비공개발화')],
                     [dict(id='one', text=''), dict(id='secret-id', text='비공개발화')]):
            stderr = self.assert_failure([reference(text='비공개정답')], hyps)
            self.assertNotIn('secret-id', stderr)
            self.assertNotIn('비공개', stderr)

    def test_duplicate_ids_fail_on_both_sides(self):
        hyp = dict(id='one', text='가 나')
        self.assert_failure([reference(), reference()], [hyp])
        self.assert_failure([reference()], [hyp, hyp])

    def test_train_requires_explicit_selection(self):
        refs = [reference(split='train')]
        hyps = [dict(id='one', text='가 나')]
        self.assert_failure(refs, hyps)
        self.assertEqual(self.run_score(refs, hyps, '--split', 'train')[0], 0)

    def test_split_selection_requires_only_selected_hyp_ids(self):
        refs = [reference(), reference('two', split='train')]
        hyps = [dict(id='one', text='가 나')]
        self.assertEqual(self.run_score(refs, hyps, '--split', 'test')[0], 0)
        self.assert_failure(refs, hyps + [dict(id='two', text='가 나')], '--split', 'test')
        self.assert_failure(refs, hyps, '--split', 'dev')

    def test_empty_reference_and_empty_files_fail(self):
        for text in ('', '  ', '...!?'):
            self.assert_failure([reference(text=text)], [dict(id='one', text='')])
        self.assert_failure([], [dict(id='one', text='')])
        self.assert_failure([reference()], [])

    def test_normalization_preserves_numbers_and_fillers(self):
        refs = [reference(text='가,\t나! 음 123')]
        code, stdout, _ = self.run_score(refs, [dict(id='one', text='가 나 음 123')])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)['overall']['cer'], 0)
        _, stdout, _ = self.run_score(refs, [dict(id='one', text='가 나')])
        self.assertEqual(json.loads(stdout)['overall']['character_errors'], 4)
        self.assertNotIn('가', stdout)

    def test_provisional_gate_is_explicit_and_reported(self):
        for changes in (dict(evaluation_ready=False), dict(eligible_metrics=['der']),
                        dict(eligible_metrics=['cer']), dict(eligible_metrics=['wer'])):
            refs, hyps = [reference(**changes)], [dict(id='one', text='가 나')]
            self.assert_failure(refs, hyps)
            code, stdout, _ = self.run_score(refs, hyps, '--allow-provisional')
            self.assertEqual(code, 0)
            result = json.loads(stdout)
            self.assertFalse(result['evaluation_ready'])
            self.assertEqual(result['provisional_cases'], 1)

    def test_invalid_field_types_and_nonfinite_numbers_fail(self):
        invalid = [('id', 7), ('text', None), ('dataset', []), ('split', 'validation'),
                   ('cluster', False), ('audio', {}), ('duration_seconds', True),
                   ('duration_seconds', 0), ('duration_seconds', float('nan')),
                   ('duration_seconds', float('inf')), ('evaluation_ready', 1),
                   ('eligible_metrics', 'cer'), ('eligible_metrics', [True]),
                   ('extra', {'nested': float('nan')})]
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                self.assert_failure([reference(**{field: value})], [dict(id='one', text='')],
                                    '--allow-provisional')
        self.assert_failure([reference()], [dict(id='one', text=8)])

    def test_malformed_json_duplicate_keys_and_overflow_are_private(self):
        for raw in ('{"text":"비공개발화", broken}\n',
                    '{"id":"비공개", "id":"중복"}\n',
                    json.dumps(reference()).replace('1.0', '1e999') + '\n', '\n'):
            stderr = self.assert_failure([], [dict(id='one', text='')], raw_ref=raw)
            self.assertNotIn('비공개', stderr)

    def test_cli_missing_file_has_no_traceback_or_path(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('score_cases.py')),
                                 '--ref', '/비공개경로/없음', '--hyp', '/없음'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn('비공개', result.stderr)


if __name__ == '__main__':
    unittest.main()
