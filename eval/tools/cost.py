#!/usr/bin/env python3
"""실시간 STT 평가의 비용 계산·예산 차단·지출 장부.

네트워크를 쓰지 않는다. 같은 계획에 같은 금액을 내는 deterministic 계산만 둔다.
단가는 이 파일의 PRICES 한 곳에만 둔다. 바뀌면 여기만 고치고 출처 주석을 갱신한다.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

KRW_PER_USD = 1400
TOTAL_CAP_KRW = 20000    # 장부 기준 누적 지출 한도 기본값


@dataclass(frozen=True)
class Price:
    usd_per_hour: float
    min_billed_seconds: float = 0.0   # 연결(세션)당 최소 과금
    source: str = ''


# 단가 표. 모두 2026-10-16 기준 문서·보도 값이며 실청구서로 확인한 값이 아니다.
PRICES = {
    # Meta Muse Voice Transcribe: 오디오 시간당 $0.18 (docs/spike-2026-09-03-realtime-stt.md 부록)
    'muse': Price(0.18, 0, 'Meta Muse 문서, 스파이크 부록'),
    # Deepgram Nova-3 스트리밍: 분당 $0.0077 = 시간당 $0.462 (Deepgram 요금표)
    'deepgram': Price(0.0077 * 60, 0, 'Deepgram 요금표 분당 $0.0077'),
    # xAI Grok Voice Transcribe 2.0 스트리밍: 시간당 $0.20 (x.ai/news, docs/research/2026-09-21-grok-voice-transcribe-2.md)
    'grok': Price(0.20, 0, 'x.ai 발표 스트리밍 시간당 $0.20'),
    # MAI-Transcribe-2-Streaming: 시간당 $0.54 도입가 (2차 보도, docs/research/2026-10-16-transcription-releases-sep-oct.md)
    'mai': Price(0.54, 0, 'TestingCatalog 보도 시간당 $0.54'),
    # 리턴제로 스트리밍 T1: 시간당 1,000원(VAT 별도), 스트리밍 세션당 최소 10초 (developers.rtzr.ai/docs/pricing)
    'rtzr': Price(1000 / KRW_PER_USD, 10, '리턴제로 요금표 시간당 1,000원, 세션당 최소 10초'),
}


class BudgetExceeded(RuntimeError):
    """예산을 넘기 직전에 전송을 멈출 때 쓴다."""


def billed_seconds(engine, seconds):
    """세션 하나의 과금 초. 최소 과금보다 짧으면 최소 과금으로 올린다."""
    return max(float(seconds), PRICES[engine].min_billed_seconds)


def usd(engine, seconds):
    return billed_seconds(engine, seconds) / 3600 * PRICES[engine].usd_per_hour


def estimate(engine, session_seconds, krw_per_usd=KRW_PER_USD):
    """세션 길이 목록으로 예상 비용을 낸다. 세션마다 최소 과금을 따로 올린다."""
    audio = sum(session_seconds)
    billed = sum(billed_seconds(engine, s) for s in session_seconds)
    cost = sum(usd(engine, s) for s in session_seconds)
    return {'engine': engine, 'sessions': len(session_seconds), 'audio_seconds': audio,
            'billed_seconds': billed, 'usd': cost, 'krw': cost * krw_per_usd}


def check_budget(total_krw, budget_krw, confirm):
    """실행 전 판정. 통과하면 None, 막히면 사유 문자열."""
    if budget_krw is None or not confirm:
        return '실제 실행에는 --budget-krw와 --confirm이 모두 필요합니다'
    if budget_krw <= 0:
        return '예산은 양수여야 합니다'
    if total_krw > budget_krw:
        return f'예상 비용 {total_krw:,.0f}원이 예산 {budget_krw:,.0f}원을 넘어 시작하지 않습니다'
    return None


def check_total_cap(total_krw, spent_krw, cap_krw):
    """장부 누적 지출에 이번 예상 비용을 더해 누적 한도를 넘으면 사유 문자열."""
    remaining = cap_krw - spent_krw
    if remaining <= 0:
        return f'누적 지출 {spent_krw:,.0f}원이 누적 한도 {cap_krw:,.0f}원에 닿아 시작하지 않습니다'
    if total_krw > remaining:
        return (f'예상 비용 {total_krw:,.0f}원이 남은 누적 한도 {remaining:,.0f}원'
                f'(한도 {cap_krw:,.0f}원 - 누적 {spent_krw:,.0f}원)을 넘어 시작하지 않습니다')
    return None


class BudgetGuard:
    """실행 중 누적 전송 음성으로 비용을 추적한다.

    전송 전에 charge()를 부르고, 예산을 넘게 되면 BudgetExceeded로 그 청크를 보내지 않는다.
    세션을 열 때 최소 과금분을 먼저 잡아 둔다. 여러 엔진이 같은 객체를 공유한다
    (asyncio 단일 스레드라 잠금이 필요 없다).
    """

    def __init__(self, budget_krw, krw_per_usd=KRW_PER_USD):
        self.budget_krw = budget_krw
        self.krw_per_usd = krw_per_usd
        self.spent_krw = 0.0
        self.sent = {}          # 엔진별 전송 초
        self.billed = {}        # 엔진별 과금 초

    def _krw(self, engine, seconds):
        return seconds / 3600 * PRICES[engine].usd_per_hour * self.krw_per_usd

    def _take(self, engine, seconds):
        cost = self._krw(engine, seconds)
        if self.spent_krw + cost > self.budget_krw + 1e-9:
            raise BudgetExceeded(f'예산 {self.budget_krw:,.0f}원 도달 직전에 멈춥니다'
                                 f'(누적 {self.spent_krw:,.2f}원)')
        self.spent_krw += cost
        self.billed[engine] = self.billed.get(engine, 0.0) + seconds

    def open_session(self, engine):
        """세션 시작 시 최소 과금분을 선점한다. 돌려주는 객체로 전송분을 청구한다."""
        self._take(engine, PRICES[engine].min_billed_seconds)
        return _Session(self, engine)


class _Session:
    def __init__(self, guard, engine):
        self.guard, self.engine, self.sent = guard, engine, 0.0

    def charge(self, seconds):
        floor = PRICES[self.engine].min_billed_seconds
        extra = max(self.sent + seconds, floor) - max(self.sent, floor)
        if extra > 0:
            self.guard._take(self.engine, extra)
        self.sent += seconds
        self.guard.sent[self.engine] = self.guard.sent.get(self.engine, 0.0) + seconds


# ------------------------------------------------------------------ 지출 장부
def ledger_path(runs_root):
    return Path(runs_root) / 'ledger.jsonl'


def append_ledger(runs_root, entry):
    """실행마다 한 줄씩 덧붙인다. 지운 적 없는 장부여야 누적 합계가 맞다."""
    path = ledger_path(runs_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(entry, recorded_at=datetime.now(timezone.utc).isoformat())
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
    return row


def ledger_totals(runs_root):
    path = ledger_path(runs_root)
    totals = {}
    if not path.exists():
        return totals
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        t = totals.setdefault(row['engine'], {'runs': 0, 'sent_seconds': 0.0, 'krw': 0.0, 'usd': 0.0})
        t['runs'] += 1
        t['sent_seconds'] += row.get('sent_seconds', 0.0)
        t['krw'] += row.get('spent_krw', 0.0)
        t['usd'] += row.get('spent_usd', 0.0)
    return totals


def ledger_spent_krw(runs_root):
    return sum(t['krw'] for t in ledger_totals(runs_root).values())


def format_ledger(totals):
    lines = [f'{"엔진":<10} {"실행":>4} {"전송 시간":>10} {"추정 지출(원)":>14} {"추정 지출($)":>12}']
    all_s = all_krw = all_usd = 0.0
    for engine in sorted(totals):
        t = totals[engine]
        lines.append(f'{engine:<10} {t["runs"]:>4} {t["sent_seconds"] / 3600:>9.3f}h '
                     f'{t["krw"]:>14,.0f} {t["usd"]:>12.3f}')
        all_s += t['sent_seconds']
        all_krw += t['krw']
        all_usd += t['usd']
    lines.append(f'{"합계":<10} {"":>4} {all_s / 3600:>9.3f}h {all_krw:>14,.0f} {all_usd:>12.3f}')
    return '\n'.join(lines)

