import tempfile
import unittest

import cost


class EstimateTest(unittest.TestCase):
    def test_hourly_rate(self):
        est = cost.estimate('muse', [1800, 1800])
        self.assertAlmostEqual(est['usd'], 0.18)
        self.assertAlmostEqual(est['krw'], 0.18 * 1400)

    def test_deepgram_per_minute(self):
        self.assertAlmostEqual(cost.estimate('deepgram', [60])['usd'], 0.0077)

    def test_minimum_billing_per_session(self):
        # 리턴제로는 세션당 최소 10초. 3초 세션 두 개는 20초로 과금된다
        est = cost.estimate('rtzr', [3, 3])
        self.assertEqual(est['audio_seconds'], 6)
        self.assertEqual(est['billed_seconds'], 20)
        self.assertAlmostEqual(est['krw'], 20 / 3600 * 1000)

    def test_exchange_rate_override(self):
        self.assertAlmostEqual(cost.estimate('grok', [3600], krw_per_usd=1000)['krw'], 200)


class BudgetCheckTest(unittest.TestCase):
    def test_requires_both_flags(self):
        self.assertIsNotNone(cost.check_budget(10, None, True))
        self.assertIsNotNone(cost.check_budget(10, 100, False))

    def test_over_budget_refused(self):
        self.assertIn('넘어', cost.check_budget(101, 100, True))

    def test_within_budget(self):
        self.assertIsNone(cost.check_budget(100, 100, True))


class TotalCapTest(unittest.TestCase):
    def test_within_remaining(self):
        self.assertIsNone(cost.check_total_cap(500, 19000, 20000))

    def test_over_remaining(self):
        self.assertIn('남은 누적 한도', cost.check_total_cap(1500, 19000, 20000))

    def test_cap_reached(self):
        self.assertIn('닿아', cost.check_total_cap(0, 20000, 20000))

    def test_ledger_spent(self):
        with tempfile.TemporaryDirectory() as tmp:
            cost.append_ledger(tmp, {'engine': 'muse', 'sent_seconds': 1, 'spent_krw': 7, 'spent_usd': 0.005})
            cost.append_ledger(tmp, {'engine': 'mai', 'sent_seconds': 1, 'spent_krw': 5, 'spent_usd': 0.004})
            self.assertEqual(cost.ledger_spent_krw(tmp), 12)


class GuardTest(unittest.TestCase):
    def test_stops_before_exceeding(self):
        # muse 시간당 0.18*1400=252원. 예산 1원이면 약 14.3초까지만 보낸다
        guard = cost.BudgetGuard(1.0)
        session = guard.open_session('muse')
        sent = 0
        with self.assertRaises(cost.BudgetExceeded):
            for _ in range(100):
                session.charge(1.0)
                sent += 1
        self.assertEqual(sent, 14)
        self.assertLessEqual(guard.spent_krw, 1.0)

    def test_minimum_reserved_at_open(self):
        guard = cost.BudgetGuard(100)
        session = guard.open_session('rtzr')
        self.assertAlmostEqual(guard.spent_krw, 10 / 3600 * 1000)
        session.charge(5)                       # 최소 과금 안이라 추가 청구 없음
        self.assertAlmostEqual(guard.spent_krw, 10 / 3600 * 1000)
        session.charge(10)                      # 15초가 되어 5초분 추가
        self.assertAlmostEqual(guard.spent_krw, 15 / 3600 * 1000)
        self.assertEqual(guard.sent['rtzr'], 15)
        self.assertEqual(guard.billed['rtzr'], 15)

    def test_open_refused_when_minimum_does_not_fit(self):
        guard = cost.BudgetGuard(1.0)
        with self.assertRaises(cost.BudgetExceeded):
            guard.open_session('rtzr')   # 10초 = 2.8원

    def test_shared_across_engines(self):
        guard = cost.BudgetGuard(1.0)
        guard.open_session('muse').charge(10)
        with self.assertRaises(cost.BudgetExceeded):
            guard.open_session('mai').charge(10)   # 10초 = 2.1원


class LedgerTest(unittest.TestCase):
    def test_append_and_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            cost.append_ledger(tmp, {'engine': 'muse', 'sent_seconds': 100, 'spent_krw': 7, 'spent_usd': 0.005})
            cost.append_ledger(tmp, {'engine': 'muse', 'sent_seconds': 50, 'spent_krw': 3, 'spent_usd': 0.002})
            cost.append_ledger(tmp, {'engine': 'grok', 'sent_seconds': 10, 'spent_krw': 1, 'spent_usd': 0.001})
            totals = cost.ledger_totals(tmp)
            self.assertEqual(totals['muse']['runs'], 2)
            self.assertEqual(totals['muse']['sent_seconds'], 150)
            self.assertEqual(totals['muse']['krw'], 10)
            self.assertIn('합계', cost.format_ledger(totals))

    def test_empty_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cost.ledger_totals(tmp), {})


if __name__ == '__main__':
    unittest.main()
