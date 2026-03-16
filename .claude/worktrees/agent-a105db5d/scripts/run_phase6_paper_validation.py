"""
scripts/run_phase6_paper_validation.py — Phase 6(페이퍼 운용) 자동 검증

목표:
- 30일 페이퍼 트레이딩 시뮬레이션
- 전략 성과 vs 벤치마크 비교
- 고변동성 시나리오 안정성 점검
- 간단 부하 테스트

사용법:
    python scripts/run_phase6_paper_validation.py
    python scripts/run_phase6_paper_validation.py --days 45 --tickers 005930,000660,035420
    python scripts/run_phase6_paper_validation.py --no-record
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import math
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.db.queries import insert_paper_trading_run
from src.utils.performance import compute_benchmark_series, compute_trade_performance


DEFAULT_TICKERS = ["005930", "000660", "035420", "051910"]


@dataclass
class ScenarioResult:
    scenario: str
    simulated_days: int
    start_date: date
    end_date: date
    trade_rows: list[dict[str, Any]]
    metrics: dict[str, Any]
    benchmark_return_pct: float
    passed: bool
    summary: str
    report: dict[str, Any]


def _clamp_metric(value: float | None, bound: float = 9_999.0) -> float | None:
    if value is None:
        return None
    return max(min(float(value), bound), -bound)


def business_days_backward(end_day: date, days: int) -> list[date]:
    out: list[date] = []
    cursor = end_day
    while len(out) < days:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor -= timedelta(days=1)
    out.reverse()
    return out


def simulate_prices(
    tickers: list[str],
    days: list[date],
    volatility: float,
    seed: int,
) -> dict[str, list[float]]:
    rng = random.Random(seed)
    prices: dict[str, list[float]] = {}

    for idx, ticker in enumerate(tickers):
        base = 30_000 + (idx * 12_000) + rng.randint(1_000, 8_000)
        series = [float(base)]
        for _ in range(1, len(days)):
            # drift + gaussian noise
            drift = 0.0008
            shock = rng.gauss(0, volatility)
            ret = max(min(drift + shock, 0.12), -0.12)
            nxt = max(series[-1] * (1 + ret), 1_000.0)
            series.append(nxt)
        prices[ticker] = series

    return prices


def moving_avg(values: list[float], window: int = 3) -> float:
    if not values:
        return 0.0
    if len(values) < window:
        return sum(values) / len(values)
    chunk = values[-window:]
    return sum(chunk) / len(chunk)


def run_strategy_simulation(
    scenario: str,
    days: list[date],
    tickers: list[str],
    prices: dict[str, list[float]],
) -> ScenarioResult:
    positions: dict[str, int] = {ticker: 0 for ticker in tickers}
    trade_rows: list[dict[str, Any]] = []

    benchmark_rows: list[dict[str, Any]] = []

    for day_idx, day in enumerate(days):
        # 벤치마크는 종목 평균가를 사용
        avg_close = sum(prices[t][day_idx] for t in tickers) / len(tickers)
        benchmark_rows.append({"trade_date": day.isoformat(), "avg_close": avg_close})

        for ticker in tickers:
            close_price = int(round(prices[ticker][day_idx]))
            history = prices[ticker][: day_idx + 1]
            ma3 = moving_avg(history, window=3)

            signal = "BUY" if close_price >= ma3 else "SELL"

            # 과매매 방지: 2일마다만 신규 체결 허용
            if day_idx % 2 == 1:
                continue

            if signal == "BUY" and positions[ticker] == 0:
                qty = 1
                positions[ticker] += qty
                trade_rows.append(
                    {
                        "ticker": ticker,
                        "side": "BUY",
                        "price": close_price,
                        "quantity": qty,
                        "amount": close_price * qty,
                        "executed_at": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
                        + timedelta(hours=6, minutes=30),
                    }
                )
            elif signal == "SELL" and positions[ticker] > 0:
                qty = positions[ticker]
                positions[ticker] = 0
                trade_rows.append(
                    {
                        "ticker": ticker,
                        "side": "SELL",
                        "price": close_price,
                        "quantity": qty,
                        "amount": close_price * qty,
                        "executed_at": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
                        + timedelta(hours=6, minutes=30),
                    }
                )

    # 종료일 강제 청산
    last_day = days[-1]
    last_dt = datetime.combine(last_day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=6, minutes=30)
    for ticker, qty in positions.items():
        if qty <= 0:
            continue
        close_price = int(round(prices[ticker][-1]))
        trade_rows.append(
            {
                "ticker": ticker,
                "side": "SELL",
                "price": close_price,
                "quantity": qty,
                "amount": close_price * qty,
                "executed_at": last_dt,
            }
        )
        positions[ticker] = 0

    metrics = compute_trade_performance(trade_rows)
    benchmark_series = compute_benchmark_series(benchmark_rows)
    benchmark_return_pct = benchmark_series[-1]["benchmark_return_pct"] if benchmark_series else 0.0

    trade_count = len(trade_rows)
    max_dd = float(metrics.get("max_drawdown_pct") or 0.0)
    return_pct = float(metrics.get("return_pct") or 0.0)

    min_trades = max(10, len(days) // 3)
    pass_by_trade_count = trade_count >= min_trades
    pass_by_drawdown = max_dd >= (-5_000.0 if scenario == "high_volatility" else -3_000.0)

    # 극단적 수익도 비정상 시그널일 수 있어 상한도 체크
    pass_by_return_sanity = -80.0 <= return_pct <= 250.0

    passed = pass_by_trade_count and pass_by_drawdown and pass_by_return_sanity
    summary = (
        f"{scenario}: {'PASS' if passed else 'FAIL'} "
        f"(days={len(days)}, trades={trade_count}, return={return_pct:.2f}%, "
        f"benchmark={benchmark_return_pct:.2f}%, mdd={max_dd:.2f}%)"
    )

    report = {
        "scenario": scenario,
        "days": len(days),
        "trade_count": trade_count,
        "return_pct": return_pct,
        "benchmark_return_pct": benchmark_return_pct,
        "max_drawdown_pct": max_dd,
        "sharpe_ratio": metrics.get("sharpe_ratio"),
        "win_rate": metrics.get("win_rate"),
        "checks": {
            "trade_count": pass_by_trade_count,
            "drawdown": pass_by_drawdown,
            "return_sanity": pass_by_return_sanity,
        },
    }

    return ScenarioResult(
        scenario=scenario,
        simulated_days=len(days),
        start_date=days[0],
        end_date=days[-1],
        trade_rows=trade_rows,
        metrics=metrics,
        benchmark_return_pct=benchmark_return_pct,
        passed=passed,
        summary=summary,
        report=report,
    )


def run_load_scenario(sim_runs: int, days: int, tickers: list[str]) -> ScenarioResult:
    started = time.perf_counter()
    durations: list[float] = []

    base_end = date.today() - timedelta(days=1)
    day_list = business_days_backward(base_end, max(days, 10))

    for i in range(sim_runs):
        t0 = time.perf_counter()
        price_map = simulate_prices(tickers, day_list, volatility=0.016, seed=10_000 + i)
        _ = run_strategy_simulation(
            scenario="load",
            days=day_list,
            tickers=tickers,
            prices=price_map,
        )
        durations.append(time.perf_counter() - t0)

    total = time.perf_counter() - started
    p95 = sorted(durations)[max(0, math.ceil(len(durations) * 0.95) - 1)]

    # 부하 허용 기준: 총 6초 이내 + p95 0.35초 이내
    passed = total <= 6.0 and p95 <= 0.35
    summary = f"load: {'PASS' if passed else 'FAIL'} (runs={sim_runs}, total={total:.3f}s, p95={p95:.3f}s)"

    fake_days = day_list[: min(30, len(day_list))]
    return ScenarioResult(
        scenario="load",
        simulated_days=len(fake_days),
        start_date=fake_days[0],
        end_date=fake_days[-1],
        trade_rows=[],
        metrics={
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": None,
            "win_rate": 0.0,
            "total_trades": 0,
        },
        benchmark_return_pct=0.0,
        passed=passed,
        summary=summary,
        report={
            "scenario": "load",
            "runs": sim_runs,
            "total_seconds": round(total, 4),
            "avg_seconds": round(statistics.mean(durations), 4) if durations else 0.0,
            "p95_seconds": round(p95, 4),
            "checks": {
                "total_seconds": total <= 6.0,
                "p95_seconds": p95 <= 0.35,
            },
        },
    )


async def maybe_record(result: ScenarioResult, record: bool) -> None:
    if not record:
        return
    await insert_paper_trading_run(
        scenario=result.scenario,
        simulated_days=result.simulated_days,
        start_date=result.start_date,
        end_date=result.end_date,
        trade_count=len(result.trade_rows),
        return_pct=float(_clamp_metric(result.metrics.get("return_pct") or 0.0) or 0.0),
        benchmark_return_pct=_clamp_metric(result.benchmark_return_pct),
        max_drawdown_pct=_clamp_metric(float(result.metrics.get("max_drawdown_pct") or 0.0)),
        sharpe_ratio=(
            _clamp_metric(float(result.metrics.get("sharpe_ratio")))
            if result.metrics.get("sharpe_ratio") is not None
            else None
        ),
        passed=result.passed,
        summary=result.summary,
        report=result.report,
    )


async def _main(args: argparse.Namespace) -> int:
    days = max(10, int(args.days))
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()] or DEFAULT_TICKERS
    sim_runs = max(5, int(args.load_runs))

    base_end = date.today() - timedelta(days=1)
    day_list = business_days_backward(base_end, days)

    baseline_prices = simulate_prices(tickers, day_list, volatility=0.012, seed=20260312)
    high_vol_prices = simulate_prices(tickers, day_list, volatility=0.026, seed=20260313)

    baseline = run_strategy_simulation("baseline", day_list, tickers, baseline_prices)
    high_vol = run_strategy_simulation("high_volatility", day_list, tickers, high_vol_prices)
    load = run_load_scenario(sim_runs=sim_runs, days=days, tickers=tickers)

    print("\n=== Phase 6 Paper Validation ===")
    print(baseline.summary)
    print(high_vol.summary)
    print(load.summary)

    await maybe_record(baseline, record=not args.no_record)
    await maybe_record(high_vol, record=not args.no_record)
    await maybe_record(load, record=not args.no_record)

    all_passed = baseline.passed and high_vol.passed and load.passed
    print("OVERALL:", "PASS" if all_passed else "FAIL")
    return 0 if all_passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 6 페이퍼 트레이딩 자동 검증")
    parser.add_argument("--days", type=int, default=30, help="검증 일수 (기본 30)")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS), help="쉼표 구분 종목")
    parser.add_argument("--load-runs", type=int, default=30, help="부하 시뮬레이션 반복 횟수")
    parser.add_argument("--no-record", action="store_true", help="paper_trading_runs DB 기록 생략")
    args = parser.parse_args()

    raise SystemExit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
