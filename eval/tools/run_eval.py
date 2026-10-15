#!/usr/bin/env python3
"""실시간 STT 2단계 평가 실행기. 기본은 dry-run(네트워크 0)이다.

    python3 eval/tools/run_eval.py --stage taste                       # 예상 비용표만
    python3 eval/tools/run_eval.py --stage taste --engines muse,grok \\
        --budget-krw 1000 --confirm                                     # 실제 실행
    python3 eval/tools/run_eval.py --ledger                            # 누적 지출

실제 실행은 --budget-krw와 --confirm이 모두 있어야 하고, 키가 있는 엔진들의 예상 비용이
이번 실행 예산과 남은 누적 한도(--total-cap-krw, 장부 기준) 이하일 때만 시작한다.
실행 중에는 둘 중 작은 값으로 청크마다 누적 비용을 확인해 넘기 직전에 멈춘다.
전사 텍스트가 든 산출물은 저장소 밖 $LIVE_CAPTION_EVAL_DATA/../runs/에만 쓴다.
화면에는 집계 수치만 낸다.
"""
import argparse
import asyncio
import json
import math
import sys
from datetime import date
from pathlib import Path

import cost
import stream_plan
import stream_score
from public_data import data_root, outside_repo

ALIASES = {'meta-muse': 'muse', 'muse': 'muse', 'deepgram': 'deepgram', 'grok': 'grok', 'xai': 'grok',
           'mai': 'mai', 'mai-streaming': 'mai', 'rtzr': 'rtzr', 'returnzero': 'rtzr'}
ALL_ENGINES = ['muse', 'deepgram', 'grok', 'mai', 'rtzr']


def parse_engines(text):
    names = []
    for raw in text.split(','):
        raw = raw.strip().lower()
        if not raw:
            continue
        if raw not in ALIASES:
            raise ValueError(f'알 수 없는 엔진: {raw} (가능: {", ".join(sorted(ALIASES))})')
        if ALIASES[raw] not in names:
            names.append(ALIASES[raw])
    if not names:
        raise ValueError('엔진을 하나 이상 지정해야 합니다')
    return names


def positive_finite(text):
    """argparse type. nan·inf·0 이하를 거른다."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f'숫자가 아닙니다: {text}') from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f'유한한 양수여야 합니다: {text}')
    return value


def runs_root(root):
    return outside_repo(Path(root).parent / 'runs')


# ------------------------------------------------------------------ 계획표
def plan_estimates(units, engines, krw_per_usd):
    seconds = [u.seconds for u in units]
    return [cost.estimate(e, seconds, krw_per_usd) for e in engines]


def format_plan(stage, units, estimates):
    audio = sum(u.seconds for u in units)
    gaps = sum(u.gap * max(len(u.pieces) - 1, 0) for u in units)
    out = [f'단계 {stage}: 세션 {len(units)}개, 엔진당 전송 {audio:,.1f}초 ({audio / 3600:.3f}h), '
           f'그중 묶음 무음 {gaps:,.1f}초', '',
           f'{"세트":<16} {"세션":>4} {"클립":>5} {"전송(초)":>10} {"채점":>10}']
    sets = {}
    for u in units:
        s = sets.setdefault(u.set, [0, 0, 0.0, u.scoring])
        s[0] += 1
        s[1] += max(len(u.clip_ids), 1)
        s[2] += u.seconds
    labels = {'standard': '표준 CER', 'del_sub': '삭제+치환', None: '정답 없음'}
    for name, (n, clips, sec, scoring) in sets.items():
        out.append(f'{name:<16} {n:>4} {clips:>5} {sec:>10,.1f} {labels[scoring]:>10}')
    out += ['', f'{"엔진":<10} {"세션":>4} {"과금(초)":>10} {"단가($/h)":>10} {"예상($)":>9} {"예상(원)":>9}']
    total_usd = total_krw = 0.0
    for est in estimates:
        out.append(f'{est["engine"]:<10} {est["sessions"]:>4} {est["billed_seconds"]:>10,.1f} '
                   f'{cost.PRICES[est["engine"]].usd_per_hour:>10.3f} {est["usd"]:>9.3f} {est["krw"]:>9,.0f}')
        total_usd += est['usd']
        total_krw += est['krw']
    out.append(f'{"합계":<10} {"":>4} {"":>10} {"":>10} {total_usd:>9.3f} {total_krw:>9,.0f}')
    return '\n'.join(out), total_krw


# ------------------------------------------------------------------ 실행
def new_run_dir(root, stage, today=None):
    base = runs_root(root)
    stem = f'{(today or date.today()).isoformat()}-{stage}'
    for n in range(1, 1000):
        path = base / (stem if n == 1 else f'{stem}-{n}')
        if not path.exists():
            path.mkdir(parents=True)
            return path
    raise RuntimeError('실행 폴더 이름을 만들 수 없습니다')


def unit_file(unit):
    return unit.id.replace('/', '__') + '.json'


async def run_engine(engine, units, guard, out_dir, jobs, decode, state):
    """한 엔진의 모든 세션을 돈다. 예산이 닿으면 남은 세션을 열지 않는다.

    state['pairs']에 끝난 세션을 바로 쌓는다. 중간에 예외가 나도 장부가 그만큼을 기록할 수 있다.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(jobs)

    async def one(unit):
        async with sem:
            if state['budget']:
                return
            try:
                pcm = await asyncio.to_thread(stream_plan.unit_pcm, unit, decode)
                reason = stream_plan.check_pcm_length(unit, pcm)
            except Exception as exc:     # 디코드 실패는 그 단위만 건너뛴다
                reason = f'디코드 실패 {type(exc).__name__}'
            if reason:
                print(f'건너뜀: {engine.name} {unit.id} ({reason})', file=sys.stderr)
                state['pairs'].append((unit, {'text': '', 'events': [], 'aborted': False,
                                              'error': reason, 'sent_seconds': 0.0}))
                return
            try:
                session = guard.open_session(engine.name)
            except cost.BudgetExceeded:
                state['budget'] = True
                return
            result = await engine.run(pcm, session)
            if result['aborted']:
                state['budget'] = True
            (out_dir / unit_file(unit)).write_text(json.dumps(
                dict(result, unit=unit.id, set=unit.set, clip_ids=unit.clip_ids,
                     audio_seconds=unit.seconds), ensure_ascii=False, indent=1), encoding='utf-8')
            state['pairs'].append((unit, result))

    await asyncio.gather(*(one(u) for u in units))


def score_results(pairs):
    """스트리밍이 모두 끝난 뒤 채점한다. 무거운 DP가 실시간 페이싱을 방해하지 않게 하려는 것이다.

    예산 중단·오류 단위는 CER 합산에서 뺀다(채점 포함 비율로 따로 알린다).
    """
    rows = []
    for unit, result in pairs:
        counts = None
        if unit.ref and unit.scoring and not result['error'] and not result['aborted']:
            counts = stream_score.char_counts(unit.ref, result['text'], unit.scoring)
        rows.append({'set': unit.set, 'sent_seconds': result['sent_seconds'], 'events': result['events'],
                     'aborted': result['aborted'], 'counts': counts, 'error': bool(result['error'])})
    return rows


def coverage(units, rows):
    """채점에 들어간 정답 글자 / 계획된 전체 정답 글자. 실행하지 못한 단위도 분모에 남는다."""
    total = sum(stream_score.ref_chars(u.ref, u.scoring) for u in units if u.ref and u.scoring)
    included = sum(r['counts']['ref_chars'] for r in rows if r['counts'])
    return {'included_chars': included, 'total_chars': total,
            'ratio': included / total if total else None}


def format_summary(summary):
    out = [f'{"엔진":<10} {"세트":<16} {"세션":>4} {"CER":>7} {"partial 중앙/최대(ms)":>22} '
           f'{"final 중앙(ms)":>14} {"전송(초)":>10} {"중단":>4} {"오류":>4}']
    for engine, data in summary.items():
        for name, s in data['sets'].items():
            lat = s['latency']
            cer = f'{s["cer"]:.2%}' if s['cer'] is not None else '-'
            partial = (f'{lat["partial"]["median_ms"]}/{lat["partial"]["max_ms"]}'
                       if lat['partial']['n'] else '-')
            final = str(lat['final']['median_ms']) if lat['final']['n'] else '-'
            out.append(f'{engine:<10} {name:<16} {s["units"]:>4} {cer:>7} {partial:>22} {final:>14} '
                       f'{s["sent_seconds"]:>10,.1f} {s["aborted"]:>4} {s["errors"]:>4}')
        cov = data['coverage']
        ratio = f'{cov["ratio"]:.1%}' if cov['ratio'] is not None else '-'
        out.append(f'{engine:<10} 채점 포함 {ratio} ({cov["included_chars"]:,}/{cov["total_chars"]:,}자), '
                   f'추정 지출 {data["spent_krw"]:,.0f}원 (${data["spent_usd"]:.3f}), 종료 {data["status"]}')
    return '\n'.join(out)


def interrupt_reason(exc):
    if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
        return 'interrupted'
    return 'exception'


async def execute(args, root, units, engines, planned, budget_krw, decode=stream_plan.decode_pcm,
                  engine_kwargs=None):
    """엔진마다 끝나는 즉시 장부에 남긴다. 예외·Ctrl-C에서도 finally가 남은 엔진을 기록한다."""
    run_dir = new_run_dir(root, args.stage)
    guard = cost.BudgetGuard(budget_krw, args.krw_per_usd)
    instances = {name: make_engine(name, engine_kwargs) for name in engines}
    states = {name: {'pairs': [], 'budget': False} for name in engines}
    recorded, summary = set(), {}

    def record(name, status):
        if name in recorded:
            return
        recorded.add(name)
        pairs = states[name]['pairs']
        billed = guard.billed.get(name, 0.0)
        spent_usd = billed / 3600 * cost.PRICES[name].usd_per_hour
        cost.append_ledger(runs_root(root), {
            'run': run_dir.name, 'stage': args.stage, 'engine': name, 'status': status,
            'units': len(pairs), 'sent_seconds': guard.sent.get(name, 0.0), 'billed_seconds': billed,
            'spent_usd': spent_usd, 'spent_krw': spent_usd * args.krw_per_usd,
            'planned_krw': planned.get(name), 'budget_krw': budget_krw,
            'aborted_units': sum(bool(r['aborted']) for _, r in pairs),
            'error_units': sum(bool(r['error']) for _, r in pairs)})
        summary[name] = {'status': status, 'spent_usd': spent_usd, 'spent_krw': spent_usd * args.krw_per_usd}

    async def go(name):
        try:
            await run_engine(instances[name], units, guard, run_dir / name, args.jobs, decode, states[name])
        except BaseException as exc:
            record(name, interrupt_reason(exc))
            raise
        record(name, 'budget' if states[name]['budget'] else 'completed')

    tasks = []
    try:
        if args.parallel:
            tasks = [asyncio.create_task(go(n)) for n in engines]
            await asyncio.gather(*tasks)
        else:
            for n in engines:
                await go(n)
    except BaseException as exc:
        # 다른 엔진이 계속 돌며 장부 밖에서 지출하지 않도록 멈추고 기다린 뒤 기록한다
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for n in engines:
            record(n, interrupt_reason(exc))   # 시작도 못 한 엔진은 0초로 남는다
        raise

    for name in engines:
        rows = score_results(states[name]['pairs'])
        sets = stream_score.aggregate(rows)
        for set_name in sets:
            sets[set_name]['errors'] = sum(r['error'] for r in rows if r['set'] == set_name)
        summary[name].update(sets=sets, coverage=coverage(units, rows))
    (run_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2,
                                                     default=lambda o: None), encoding='utf-8')
    return run_dir, summary


def make_engine(name, engine_kwargs=None):
    from engines import ENGINES
    return ENGINES[name](**(engine_kwargs or {}).get(name, {}))


def main(argv=None, environ=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--stage', choices=('taste', 'core'))
    ap.add_argument('--engines', default=','.join(ALL_ENGINES), help='쉼표 구분. 기본 5종 전부')
    ap.add_argument('--budget-krw', type=positive_finite, help='이번 실행 예산(원). --confirm과 함께 써야 한다')
    ap.add_argument('--total-cap-krw', type=positive_finite, default=cost.TOTAL_CAP_KRW,
                    help=f'장부 기준 누적 지출 한도(원, 기본 {cost.TOTAL_CAP_KRW:,.0f})')
    ap.add_argument('--confirm', action='store_true', help='실제 API를 호출한다')
    ap.add_argument('--parallel', action='store_true', help='엔진들을 동시에 돌린다')
    ap.add_argument('--jobs', type=int, default=1, help='엔진마다 동시에 여는 세션 수(기본 1)')
    ap.add_argument('--krw-per-usd', type=positive_finite, default=cost.KRW_PER_USD)
    ap.add_argument('--root', help='자료 루트. 기본 $LIVE_CAPTION_EVAL_DATA')
    ap.add_argument('--ledger', action='store_true', help='지출 장부 누적 합계를 보고 끝낸다')
    args = ap.parse_args(argv)

    root = data_root(args.root)
    if args.ledger:
        print(cost.format_ledger(cost.ledger_totals(runs_root(root))))
        return 0
    if not args.stage:
        ap.error('--stage가 필요합니다')
    if args.jobs < 1:
        ap.error('--jobs는 1 이상이어야 합니다')
    try:
        engines = parse_engines(args.engines)
        units = stream_plan.stage_units(root, args.stage)
        stream_plan.check_session_limits(units, engines)
    except (ValueError, OSError) as exc:
        print(f'오류: {exc}', file=sys.stderr)
        return 2

    estimates = plan_estimates(units, engines, args.krw_per_usd)
    table, _ = format_plan(args.stage, units, estimates)
    print(table)
    spent_total = cost.ledger_spent_krw(runs_root(root))
    print(f'\n누적 지출 {spent_total:,.0f}원 / 한도 {args.total_cap_krw:,.0f}원')

    if args.budget_krw is None and not args.confirm:
        print('\ndry-run: 네트워크 호출 없음. 실제 실행은 --budget-krw N --confirm.')
        return 0

    from engines import ENGINES
    runnable = []
    for name in engines:
        missing = ENGINES[name](environ=environ).missing_env()
        if missing:
            print(f'건너뜀: {name} (환경변수 없음: {", ".join(missing)})')
        else:
            runnable.append(name)
    planned = {e['engine']: e['krw'] for e in estimates if e['engine'] in runnable}
    total_planned = sum(planned.values())
    reason = (cost.check_budget(total_planned, args.budget_krw, args.confirm)
              or cost.check_total_cap(total_planned, spent_total, args.total_cap_krw))
    if reason:
        print(f'\n시작하지 않음: {reason}', file=sys.stderr)
        return 2
    if not runnable:
        print('\n키가 있는 엔진이 없어 시작하지 않습니다.', file=sys.stderr)
        return 2

    effective = min(args.budget_krw, args.total_cap_krw - spent_total)
    print(f'\n실행: {", ".join(runnable)} / 예상 {total_planned:,.0f}원 / 차단 기준 {effective:,.0f}원'
          f'(이번 예산 {args.budget_krw:,.0f}원, 남은 누적 한도 {args.total_cap_krw - spent_total:,.0f}원)')
    engine_kwargs = {n: {'environ': environ} for n in runnable} if environ is not None else None
    run_dir, summary = asyncio.run(execute(args, root, units, runnable, planned, effective,
                                           engine_kwargs=engine_kwargs))
    print(format_summary(summary))
    print(f'\n산출물: {run_dir}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
