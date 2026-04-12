"""
src/backtest/repository.py — 백테스트 DB CRUD

save_backtest_run + save_backtest_daily 는 단일 트랜잭션으로 실행된다.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from src.backtest.models import BacktestResult
from src.utils.db_client import fetch, fetchrow, get_pool


async def save_backtest(result: BacktestResult) -> int:
    """백테스트 결과(run + daily snapshots)를 단일 트랜잭션으로 저장한다.

    Returns:
        생성된 backtest_runs.id
    """
    cfg = result.config
    m = result.metrics

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            run_id: int = await conn.fetchval(
                """
                INSERT INTO backtest_runs (
                    ticker, strategy,
                    train_start, train_end, test_start, test_end,
                    initial_capital, commission_rate_pct, tax_rate_pct, slippage_bps,
                    total_return_pct, annual_return_pct, sharpe_ratio,
                    max_drawdown_pct, win_rate, total_trades,
                    avg_holding_days, baseline_return_pct, excess_return_pct
                ) VALUES (
                    $1, $2,
                    $3, $4, $5, $6,
                    $7, $8, $9, $10,
                    $11, $12, $13,
                    $14, $15, $16,
                    $17, $18, $19
                ) RETURNING id
                """,
                cfg.ticker,
                cfg.strategy,
                cfg.train_start,
                cfg.train_end,
                cfg.test_start,
                cfg.test_end,
                cfg.initial_capital,
                cfg.commission_rate_pct,
                cfg.tax_rate_pct,
                cfg.slippage_bps,
                m.total_return_pct,
                m.annual_return_pct,
                m.sharpe_ratio,
                m.max_drawdown_pct,
                m.win_rate,
                m.total_trades,
                m.avg_holding_days,
                m.baseline_return_pct,
                m.excess_return_pct,
            )

            if result.daily_snapshots:
                await conn.executemany(
                    """
                    INSERT INTO backtest_daily (
                        run_id, date, close_price,
                        cash, position_qty, position_value,
                        portfolio_value, daily_return_pct
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    [
                        (
                            run_id,
                            s.date,
                            s.close_price,
                            s.cash,
                            s.position_qty,
                            s.position_value,
                            s.portfolio_value,
                            s.daily_return_pct,
                        )
                        for s in result.daily_snapshots
                    ],
                )

    return run_id


async def fetch_backtest_run(run_id: int) -> Optional[dict]:
    """backtest_runs 단건 조회."""
    row = await fetchrow(
        "SELECT * FROM backtest_runs WHERE id = $1",
        run_id,
    )
    return dict(row) if row else None


async def fetch_predictions_for_replay(
    ticker: str,
    start_date: date,
    end_date: date,
    strategy: str,
) -> list[dict]:
    """predictions 테이블에서 시그널을 조회한다 (Strategy A/B replay 용).

    Returns:
        ``[{"trading_date": date, "signal": str}, ...]``
    """
    rows = await fetch(
        """
        SELECT trading_date, signal
        FROM predictions
        WHERE ticker = $1
          AND trading_date BETWEEN $2 AND $3
          AND strategy = $4
        ORDER BY trading_date
        """,
        ticker,
        start_date,
        end_date,
        strategy,
    )
    return [dict(r) for r in rows]
