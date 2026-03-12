"""
src/db/queries.py — 코어 에이전트용 DB 쿼리 유틸
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional

from src.db.models import (
    AgentHeartbeatRecord,
    MarketDataPoint,
    NotificationRecord,
    PaperOrderRequest,
    PredictionSignal,
)
from src.utils.db_client import execute, fetch, fetchrow, fetchval


async def upsert_market_data(points: list[MarketDataPoint]) -> int:
    """market_data를 upsert하고 반영 건수를 반환합니다."""
    if not points:
        return 0

    query = """
        INSERT INTO market_data (
            ticker, name, market, timestamp_kst, interval,
            open, high, low, close, volume,
            change_pct, market_cap, foreigner_ratio
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9, $10,
            $11, $12, $13
        )
        ON CONFLICT (ticker, timestamp_kst, interval)
        DO UPDATE SET
            name = EXCLUDED.name,
            market = EXCLUDED.market,
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            change_pct = EXCLUDED.change_pct,
            market_cap = EXCLUDED.market_cap,
            foreigner_ratio = EXCLUDED.foreigner_ratio
    """
    for p in points:
        await execute(
            query,
            p.ticker,
            p.name,
            p.market,
            p.timestamp_kst,
            p.interval,
            p.open,
            p.high,
            p.low,
            p.close,
            p.volume,
            p.change_pct,
            p.market_cap,
            p.foreigner_ratio,
        )
    return len(points)


async def list_tickers(limit: int = 30) -> list[dict]:
    rows = await fetch(
        """
        SELECT DISTINCT ON (ticker) ticker, name, market
        FROM market_data
        ORDER BY ticker, timestamp_kst DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def fetch_recent_ohlcv(ticker: str, days: int = 30) -> list[dict]:
    rows = await fetch(
        """
        SELECT
            ticker, name, timestamp_kst, open, high, low, close, volume, change_pct
        FROM market_data
        WHERE ticker = $1
          AND interval = 'daily'
          AND timestamp_kst >= NOW() - ($2 * INTERVAL '1 day')
        ORDER BY timestamp_kst DESC
        """,
        ticker,
        days,
    )
    return [dict(r) for r in rows]


async def latest_close_price(ticker: str) -> Optional[int]:
    return await fetchval(
        """
        SELECT close
        FROM market_data
        WHERE ticker = $1
        ORDER BY timestamp_kst DESC
        LIMIT 1
        """,
        ticker,
    )


async def insert_prediction(signal: PredictionSignal) -> int:
    prediction_id = await fetchval(
        """
        INSERT INTO predictions (
            agent_id, llm_model, strategy, ticker, signal,
            confidence, target_price, stop_loss, reasoning_summary,
            debate_transcript_id, trading_date
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9,
            $10, $11
        )
        RETURNING id
        """,
        signal.agent_id,
        signal.llm_model,
        signal.strategy,
        signal.ticker,
        signal.signal,
        signal.confidence,
        signal.target_price,
        signal.stop_loss,
        signal.reasoning_summary,
        signal.debate_transcript_id,
        signal.trading_date,
    )
    return int(prediction_id)


async def insert_debate_transcript(
    trading_date: date,
    ticker: str,
    rounds: int,
    consensus_reached: bool,
    final_signal: Optional[str],
    confidence: Optional[float],
    proposer_content: str,
    challenger1_content: str,
    challenger2_content: str,
    synthesizer_content: str,
    no_consensus_reason: Optional[str] = None,
    duration_seconds: Optional[int] = None,
) -> int:
    transcript_id = await fetchval(
        """
        INSERT INTO debate_transcripts (
            trading_date, ticker, rounds, consensus_reached,
            final_signal, confidence,
            proposer_content, challenger1_content, challenger2_content, synthesizer_content,
            no_consensus_reason, duration_seconds
        ) VALUES (
            $1, $2, $3, $4,
            $5, $6,
            $7, $8, $9, $10,
            $11, $12
        )
        RETURNING id
        """,
        trading_date,
        ticker,
        rounds,
        consensus_reached,
        final_signal,
        confidence,
        proposer_content,
        challenger1_content,
        challenger2_content,
        synthesizer_content,
        no_consensus_reason,
        duration_seconds,
    )
    return int(transcript_id)


async def get_position(ticker: str) -> Optional[dict]:
    row = await fetchrow(
        """
        SELECT ticker, name, quantity, avg_price, current_price, is_paper
        FROM portfolio_positions
        WHERE ticker = $1
        LIMIT 1
        """,
        ticker,
    )
    return dict(row) if row else None


async def save_position(
    ticker: str,
    name: str,
    quantity: int,
    avg_price: int,
    current_price: int,
    is_paper: bool,
) -> None:
    if quantity <= 0:
        await execute("DELETE FROM portfolio_positions WHERE ticker = $1", ticker)
        return

    await execute(
        """
        INSERT INTO portfolio_positions (
            ticker, name, quantity, avg_price, current_price, is_paper, opened_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        ON CONFLICT (ticker)
        DO UPDATE SET
            name = EXCLUDED.name,
            quantity = EXCLUDED.quantity,
            avg_price = EXCLUDED.avg_price,
            current_price = EXCLUDED.current_price,
            is_paper = EXCLUDED.is_paper,
            updated_at = NOW()
        """,
        ticker,
        name,
        quantity,
        avg_price,
        current_price,
        is_paper,
    )


async def portfolio_total_value() -> int:
    value = await fetchval(
        """
        SELECT COALESCE(SUM(quantity * current_price), 0)
        FROM portfolio_positions
        WHERE quantity > 0
        """
    )
    return int(value or 0)


async def get_portfolio_config() -> dict:
    row = await fetchrow(
        """
        SELECT strategy_blend_ratio, max_position_pct, daily_loss_limit_pct, is_paper_trading
        FROM portfolio_config
        LIMIT 1
        """
    )
    if not row:
        return {
            "strategy_blend_ratio": 0.5,
            "max_position_pct": 20,
            "daily_loss_limit_pct": 3,
            "is_paper_trading": True,
        }
    return dict(row)


async def today_trade_totals() -> dict:
    row = await fetchrow(
        """
        SELECT
            COALESCE(SUM(CASE WHEN side = 'BUY' THEN amount ELSE 0 END), 0) AS buy_total,
            COALESCE(SUM(CASE WHEN side = 'SELL' THEN amount ELSE 0 END), 0) AS sell_total
        FROM trade_history
        WHERE executed_at::date = CURRENT_DATE
          AND is_paper = TRUE
        """
    )
    return {
        "buy_total": int(row["buy_total"]) if row else 0,
        "sell_total": int(row["sell_total"]) if row else 0,
    }


async def fetch_trade_rows(days: int, is_paper: bool = True) -> list[dict]:
    rows = await fetch(
        """
        SELECT ticker, side, price, quantity, amount, executed_at
        FROM trade_history
        WHERE is_paper = $1
          AND executed_at >= NOW() - ($2 * INTERVAL '1 day')
        ORDER BY executed_at
        """,
        is_paper,
        days,
    )
    return [dict(r) for r in rows]


async def fetch_trade_rows_for_date(trade_date: date, is_paper: bool = True) -> list[dict]:
    rows = await fetch(
        """
        SELECT ticker, side, price, quantity, amount, executed_at
        FROM trade_history
        WHERE is_paper = $1
          AND executed_at::date = $2::date
        ORDER BY executed_at
        """,
        is_paper,
        trade_date,
    )
    return [dict(r) for r in rows]


async def insert_trade(order: PaperOrderRequest, circuit_breaker: bool = False) -> None:
    await execute(
        """
        INSERT INTO trade_history (
            ticker, name, side, quantity, price, amount,
            signal_source, agent_id, is_paper, circuit_breaker
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, TRUE, $9
        )
        """,
        order.ticker,
        order.name,
        order.signal,
        order.quantity,
        order.price,
        order.quantity * order.price,
        order.signal_source,
        order.agent_id,
        circuit_breaker,
    )


async def upsert_tournament_score(
    agent_id: str,
    llm_model: str,
    persona: str,
    trading_date: date,
    correct: int,
    total: int,
    is_winner: bool,
) -> None:
    rolling_accuracy = (correct / total) if total > 0 else None
    await execute(
        """
        INSERT INTO predictor_tournament_scores (
            agent_id, llm_model, persona, trading_date, correct, total, rolling_accuracy, is_current_winner
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (agent_id, trading_date)
        DO UPDATE SET
            llm_model = EXCLUDED.llm_model,
            persona = EXCLUDED.persona,
            correct = EXCLUDED.correct,
            total = EXCLUDED.total,
            rolling_accuracy = EXCLUDED.rolling_accuracy,
            is_current_winner = EXCLUDED.is_current_winner,
            updated_at = NOW()
        """,
        agent_id,
        llm_model,
        persona,
        trading_date,
        correct,
        total,
        rolling_accuracy,
        is_winner,
    )


async def insert_heartbeat(heartbeat: AgentHeartbeatRecord) -> None:
    await execute(
        """
        INSERT INTO agent_heartbeats (agent_id, status, last_action, metrics)
        VALUES ($1, $2, $3, $4::jsonb)
        """,
        heartbeat.agent_id,
        heartbeat.status,
        heartbeat.last_action,
        json.dumps(heartbeat.metrics or {}, ensure_ascii=False),
    )


async def insert_notification(record: NotificationRecord) -> None:
    await execute(
        """
        INSERT INTO notification_history (event_type, message, success, error_msg)
        VALUES ($1, $2, $3, $4)
        """,
        record.event_type,
        record.message,
        record.success,
        record.error_msg,
    )


async def insert_real_trading_audit(
    requested_by_email: str | None,
    requested_by_user_id: str | None,
    requested_mode_is_paper: bool,
    confirmation_code_ok: bool,
    readiness_passed: bool,
    readiness_summary: dict,
    applied: bool,
    message: str,
) -> None:
    await execute(
        """
        INSERT INTO real_trading_audit (
            requested_by_email,
            requested_by_user_id,
            requested_mode_is_paper,
            confirmation_code_ok,
            readiness_passed,
            readiness_summary,
            applied,
            message
        ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
        """,
        requested_by_email,
        requested_by_user_id,
        requested_mode_is_paper,
        confirmation_code_ok,
        readiness_passed,
        json.dumps(readiness_summary, ensure_ascii=False),
        applied,
        message,
    )


async def insert_operational_audit(
    audit_type: str,
    passed: bool,
    summary: str,
    details: dict[str, Any] | None = None,
    executed_by: str | None = None,
) -> None:
    await execute(
        """
        INSERT INTO operational_audits (
            audit_type, passed, summary, details, executed_by
        ) VALUES ($1, $2, $3, $4::jsonb, $5)
        """,
        audit_type,
        passed,
        summary,
        json.dumps(details or {}, ensure_ascii=False),
        executed_by,
    )


async def fetch_latest_operational_audit(audit_type: str) -> Optional[dict]:
    row = await fetchrow(
        """
        SELECT audit_type, passed, summary, details, executed_by, created_at
        FROM operational_audits
        WHERE audit_type = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        audit_type,
    )
    return dict(row) if row else None
