"""
src/db/queries.py — 코어 에이전트용 DB 쿼리 유틸
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from src.db.models import (
    AgentHeartbeatRecord,
    MarketDataPoint,
    NotificationRecord,
    PaperOrderRequest,
    PredictionSignal,
)
from src.utils.account_scope import AccountScope, normalize_account_scope, scope_from_is_paper
from src.utils.db_client import execute, executemany, fetch, fetchrow, fetchval


async def upsert_market_data(points: list[MarketDataPoint]) -> int:
    """ohlcv_daily를 upsert하고 반영 건수를 반환합니다."""
    if not points:
        return 0

    query = """
        INSERT INTO ohlcv_daily (
            instrument_id, traded_at,
            open, high, low, close, volume,
            change_pct, adj_close
        ) VALUES (
            $1, $2,
            $3, $4, $5, $6, $7,
            $8, $9
        )
        ON CONFLICT (instrument_id, traded_at)
        DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            change_pct = EXCLUDED.change_pct,
            adj_close = EXCLUDED.adj_close
    """
    await executemany(query, [
        (
            p.instrument_id, p.traded_at,
            p.open, p.high, p.low, p.close, p.volume,
            p.change_pct, p.adj_close,
        )
        for p in points
    ])
    return len(points)


async def list_tickers(limit: int = 30) -> list[dict]:
    rows = await fetch(
        """
        SELECT instrument_id, raw_code AS ticker, name, market_id AS market
        FROM instruments
        WHERE is_active = TRUE
        ORDER BY instrument_id
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def fetch_recent_ohlcv(ticker: str, days: int = 30) -> list[dict]:
    """최근 N일 OHLCV를 반환합니다.

    ticker는 instrument_id(005930.KS) 또는 raw_code(005930) 모두 허용합니다.
    """
    return await fetch_recent_market_data(ticker, days=days)


async def fetch_recent_market_data(
    ticker: str,
    *,
    days: int | None = None,
    limit: int | None = None,
    # interval/seconds 인자는 하위 호환을 위해 유지하되 무시합니다
    interval: str = "daily",
    seconds: int | None = None,
) -> list[dict]:
    if days is None:
        days = 30

    # instrument_id 또는 raw_code 모두 허용
    conditions = [
        "(o.instrument_id = $1 OR i.raw_code = $1)",
    ]
    params: list[Any] = [ticker]

    params.append(days)
    conditions.append(f"o.traded_at >= (CURRENT_DATE - (${len(params)} * INTERVAL '1 day'))::date")

    limit_sql = ""
    if limit is not None:
        params.append(limit)
        limit_sql = f" LIMIT ${len(params)}"

    rows = await fetch(
        f"""
        SELECT
            o.instrument_id, i.raw_code AS ticker, i.name,
            o.traded_at, o.open, o.high, o.low, o.close, o.volume,
            o.change_pct, o.adj_close
        FROM ohlcv_daily o
        JOIN instruments i ON o.instrument_id = i.instrument_id
        WHERE {' AND '.join(conditions)}
        ORDER BY o.traded_at DESC
        {limit_sql}
        """,
        *params,
    )
    return [dict(r) for r in rows]


async def latest_close_price(ticker: str) -> Optional[float]:
    """최근 종가를 반환합니다.

    ticker는 instrument_id(005930.KS) 또는 raw_code(005930) 모두 허용합니다.
    """
    return await fetchval(
        """
        SELECT o.close
        FROM ohlcv_daily o
        JOIN instruments i ON o.instrument_id = i.instrument_id
        WHERE o.instrument_id = $1 OR i.raw_code = $1
        ORDER BY o.traded_at DESC
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


async def get_position(ticker: str, account_scope: AccountScope = "paper") -> Optional[dict]:
    scope = normalize_account_scope(account_scope)
    row = await fetchrow(
        """
        SELECT ticker, name, quantity, avg_price, current_price, is_paper, account_scope
        FROM portfolio_positions
        WHERE ticker = $1
          AND account_scope = $2
        LIMIT 1
        """,
        ticker,
        scope,
    )
    return dict(row) if row else None


async def get_positions_for_scope(account_scope: AccountScope = "paper") -> list[dict]:
    """특정 계좌의 모든 보유 포지션을 반환합니다."""
    scope = normalize_account_scope(account_scope)
    rows = await fetch(
        """
        SELECT ticker, name, quantity, avg_price, current_price, is_paper, account_scope
        FROM portfolio_positions
        WHERE account_scope = $1 AND quantity > 0
        ORDER BY ticker
        """,
        scope,
    )
    return [dict(r) for r in rows]


async def save_position(
    ticker: str,
    name: str,
    quantity: int,
    avg_price: int,
    current_price: int,
    is_paper: bool,
    account_scope: AccountScope | None = None,
) -> None:
    scope = normalize_account_scope(account_scope or scope_from_is_paper(is_paper))
    if quantity <= 0:
        await execute(
            "DELETE FROM portfolio_positions WHERE ticker = $1 AND account_scope = $2",
            ticker,
            scope,
        )
        return

    await execute(
        """
        INSERT INTO portfolio_positions (
            ticker, name, quantity, avg_price, current_price, is_paper, account_scope, opened_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
        ON CONFLICT (ticker, account_scope)
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
        scope == "paper",
        scope,
    )


async def portfolio_total_value(account_scope: AccountScope = "paper") -> int:
    scope = normalize_account_scope(account_scope)
    value = await fetchval(
        """
        SELECT COALESCE(SUM(quantity * current_price), 0)
        FROM portfolio_positions
        WHERE quantity > 0
          AND account_scope = $1
        """,
        scope,
    )
    return int(value or 0)


async def list_positions(account_scope: AccountScope = "paper") -> list[dict]:
    scope = normalize_account_scope(account_scope)
    rows = await fetch(
        """
        SELECT ticker, name, quantity, avg_price, current_price, is_paper, account_scope
        FROM portfolio_positions
        WHERE quantity > 0
          AND account_scope = $1
        ORDER BY (quantity * current_price) DESC, ticker
        """,
        scope,
    )
    return [dict(r) for r in rows]


async def portfolio_position_stats(account_scope: AccountScope = "paper") -> dict:
    scope = normalize_account_scope(account_scope)
    row = await fetchrow(
        """
        SELECT
            COALESCE(SUM(quantity * current_price), 0) AS market_value,
            COALESCE(SUM(quantity * (current_price - avg_price)), 0) AS unrealized_pnl,
            COUNT(*) FILTER (WHERE quantity > 0) AS position_count
        FROM portfolio_positions
        WHERE quantity > 0
          AND account_scope = $1
        """,
        scope,
    )
    return {
        "market_value": int(row["market_value"]) if row else 0,
        "unrealized_pnl": int(row["unrealized_pnl"]) if row else 0,
        "position_count": int(row["position_count"]) if row else 0,
    }


async def get_portfolio_config() -> dict:
    row = await fetchrow(
        """
        SELECT
            strategy_blend_ratio,
            max_position_pct,
            daily_loss_limit_pct,
            is_paper_trading,
            enable_paper_trading,
            enable_real_trading,
            primary_account_scope
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
            "enable_paper_trading": True,
            "enable_real_trading": False,
            "primary_account_scope": "paper",
        }
    payload = dict(row)
    if payload.get("enable_paper_trading") is None:
        payload["enable_paper_trading"] = bool(payload.get("is_paper_trading", True))
    if payload.get("enable_real_trading") is None:
        payload["enable_real_trading"] = not bool(payload.get("is_paper_trading", True))
    if not payload.get("primary_account_scope"):
        payload["primary_account_scope"] = "paper" if bool(payload.get("is_paper_trading", True)) else "real"
    payload["is_paper_trading"] = normalize_account_scope(payload["primary_account_scope"]) == "paper"
    return payload


async def list_model_role_configs(strategy_code: str | None = None) -> list[dict]:
    if strategy_code:
        rows = await fetch(
            """
            SELECT
                config_key, strategy_code, role, role_label, agent_id,
                llm_model, persona, execution_order, is_enabled,
                to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS updated_at
            FROM model_role_configs
            WHERE strategy_code = $1
            ORDER BY execution_order, config_key
            """,
            strategy_code,
        )
    else:
        rows = await fetch(
            """
            SELECT
                config_key, strategy_code, role, role_label, agent_id,
                llm_model, persona, execution_order, is_enabled,
                to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS updated_at
            FROM model_role_configs
            ORDER BY strategy_code, execution_order, config_key
            """
        )
    return [dict(r) for r in rows]


async def upsert_model_role_config(
    *,
    config_key: str,
    strategy_code: str,
    role: str,
    role_label: str,
    agent_id: str,
    llm_model: str,
    persona: str,
    execution_order: int,
) -> None:
    await execute(
        """
        INSERT INTO model_role_configs (
            config_key, strategy_code, role, role_label, agent_id,
            llm_model, persona, execution_order, created_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, NOW(), NOW()
        )
        ON CONFLICT (config_key)
        DO UPDATE SET
            strategy_code = EXCLUDED.strategy_code,
            role = EXCLUDED.role,
            role_label = EXCLUDED.role_label,
            agent_id = EXCLUDED.agent_id,
            llm_model = EXCLUDED.llm_model,
            persona = EXCLUDED.persona,
            execution_order = EXCLUDED.execution_order,
            updated_at = NOW()
        """,
        config_key,
        strategy_code,
        role,
        role_label,
        agent_id,
        llm_model,
        persona,
        execution_order,
    )


async def update_model_role_config(
    *,
    config_key: str,
    llm_model: str,
    persona: str,
    is_enabled: bool = True,
) -> None:
    await execute(
        """
        UPDATE model_role_configs
        SET llm_model = $2,
            persona = $3,
            is_enabled = $4,
            updated_at = NOW()
        WHERE config_key = $1
        """,
        config_key,
        llm_model,
        persona,
        is_enabled,
    )


async def today_trade_totals(account_scope: AccountScope = "paper") -> dict:
    scope = normalize_account_scope(account_scope)
    row = await fetchrow(
        """
        SELECT
            COALESCE(SUM(CASE WHEN side = 'BUY' THEN amount ELSE 0 END), 0) AS buy_total,
            COALESCE(SUM(CASE WHEN side = 'SELL' THEN amount ELSE 0 END), 0) AS sell_total
        FROM trade_history
        WHERE executed_at::date = CURRENT_DATE
          AND account_scope = $1
        """,
        scope,
    )
    return {
        "buy_total": int(row["buy_total"]) if row else 0,
        "sell_total": int(row["sell_total"]) if row else 0,
    }


async def trade_cash_totals(account_scope: AccountScope = "paper") -> dict:
    scope = normalize_account_scope(account_scope)
    row = await fetchrow(
        """
        SELECT
            COALESCE(SUM(CASE WHEN side = 'BUY' THEN amount ELSE 0 END), 0) AS buy_total,
            COALESCE(SUM(CASE WHEN side = 'SELL' THEN amount ELSE 0 END), 0) AS sell_total
        FROM trade_history
        WHERE account_scope = $1
        """,
        scope,
    )
    return {
        "buy_total": int(row["buy_total"]) if row else 0,
        "sell_total": int(row["sell_total"]) if row else 0,
    }


async def fetch_trade_rows(
    days: int,
    is_paper: bool = True,
    account_scope: AccountScope | None = None,
) -> list[dict]:
    scope = normalize_account_scope(account_scope or scope_from_is_paper(is_paper))
    rows = await fetch(
        """
        SELECT ticker, side, price, quantity, amount, executed_at
        FROM trade_history
        WHERE account_scope = $1
          AND executed_at >= NOW() - ($2 * INTERVAL '1 day')
        ORDER BY executed_at
        """,
        scope,
        days,
    )
    return [dict(r) for r in rows]


async def fetch_trade_rows_by_source(
    signal_source: str,
    days: int,
    account_scope: AccountScope = "paper",
) -> list[dict]:
    """특정 전략(signal_source)의 최근 N일 거래 이력을 반환합니다."""
    scope = normalize_account_scope(account_scope)
    rows = await fetch(
        """
        SELECT ticker, side, price, quantity, amount, executed_at
        FROM trade_history
        WHERE signal_source = $1
          AND account_scope = $2
          AND executed_at >= NOW() - ($3 * INTERVAL '1 day')
        ORDER BY executed_at
        """,
        signal_source,
        scope,
        days,
    )
    return [dict(r) for r in rows]


async def fetch_all_trade_rows(account_scope: AccountScope = "paper") -> list[dict]:
    scope = normalize_account_scope(account_scope)
    rows = await fetch(
        """
        SELECT ticker, side, price, quantity, amount, executed_at
        FROM trade_history
        WHERE account_scope = $1
        ORDER BY executed_at
        """,
        scope,
    )
    return [dict(r) for r in rows]


async def fetch_trade_rows_for_date(
    trade_date: date,
    is_paper: bool = True,
    account_scope: AccountScope | None = None,
) -> list[dict]:
    scope = normalize_account_scope(account_scope or scope_from_is_paper(is_paper))
    rows = await fetch(
        """
        SELECT ticker, side, price, quantity, amount, executed_at
        FROM trade_history
        WHERE account_scope = $1
          AND executed_at::date = $2::date
        ORDER BY executed_at
        """,
        scope,
        trade_date,
    )
    return [dict(r) for r in rows]


async def insert_trade(order: PaperOrderRequest, circuit_breaker: bool = False) -> None:
    scope = normalize_account_scope(order.account_scope)
    await execute(
        """
        INSERT INTO trade_history (
            ticker, name, side, quantity, price, amount,
            signal_source, agent_id, kis_order_id, is_paper, account_scope, circuit_breaker
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, NULL, $9, $10, $11
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
        scope == "paper",
        scope,
        circuit_breaker,
    )


async def upsert_trade_fill(
    *,
    account_scope: AccountScope,
    ticker: str,
    name: str,
    side: str,
    quantity: int,
    price: int,
    signal_source: str,
    agent_id: str,
    kis_order_id: str,
    executed_at: datetime | None = None,
) -> bool:
    scope = normalize_account_scope(account_scope)
    exists = await fetchval(
        """
        SELECT 1
        FROM trade_history
        WHERE account_scope = $1
          AND kis_order_id = $2
        LIMIT 1
        """,
        scope,
        kis_order_id,
    )

    if exists:
        await execute(
            """
            UPDATE trade_history
            SET ticker = $3,
                name = $4,
                side = $5,
                quantity = $6,
                price = $7,
                amount = $8,
                signal_source = $9,
                agent_id = $10,
                executed_at = COALESCE($11, executed_at)
            WHERE account_scope = $1
              AND kis_order_id = $2
            """,
            scope,
            kis_order_id,
            ticker,
            name,
            side,
            quantity,
            price,
            quantity * price,
            signal_source,
            agent_id,
            executed_at,
        )
        return False

    await execute(
        """
        INSERT INTO trade_history (
            ticker, name, side, quantity, price, amount,
            signal_source, agent_id, kis_order_id, is_paper, account_scope, circuit_breaker, executed_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9, $10, $11, FALSE, COALESCE($12, NOW())
        )
        """,
        ticker,
        name,
        side,
        quantity,
        price,
        quantity * price,
        signal_source,
        agent_id,
        kis_order_id,
        scope == "paper",
        scope,
        executed_at,
    )
    return True


async def insert_broker_order(
    client_order_id: str,
    account_scope: AccountScope,
    broker_name: str,
    ticker: str,
    name: str,
    side: str,
    requested_quantity: int,
    requested_price: int,
    signal_source: str,
    agent_id: str,
    status: str = "PENDING",
    broker_order_id: str | None = None,
    rejection_reason: str | None = None,
) -> None:
    scope = normalize_account_scope(account_scope)
    await execute(
        """
        INSERT INTO broker_orders (
            client_order_id, account_scope, broker_name, ticker, name, side,
            order_type, requested_quantity, requested_price,
            filled_quantity, avg_fill_price, status,
            signal_source, agent_id, broker_order_id, rejection_reason,
            requested_at, created_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            'MARKET', $7, $8,
            0, NULL, $9,
            $10, $11, $12, $13,
            NOW(), NOW(), NOW()
        )
        """,
        client_order_id,
        scope,
        broker_name,
        ticker,
        name,
        side,
        requested_quantity,
        requested_price,
        status,
        signal_source,
        agent_id,
        broker_order_id,
        rejection_reason,
    )


async def update_broker_order_status(
    client_order_id: str,
    status: str,
    filled_quantity: int = 0,
    avg_fill_price: int | None = None,
    broker_order_id: str | None = None,
    rejection_reason: str | None = None,
) -> None:
    await execute(
        """
        UPDATE broker_orders
        SET status = $2::varchar,
            filled_quantity = $3,
            avg_fill_price = $4,
            broker_order_id = COALESCE($5, broker_order_id),
            rejection_reason = $6,
            filled_at = CASE WHEN $2::varchar = 'FILLED' THEN NOW() ELSE filled_at END,
            updated_at = NOW()
        WHERE client_order_id = $1
        """,
        client_order_id,
        status,
        filled_quantity,
        avg_fill_price,
        broker_order_id,
        rejection_reason,
    )


async def attach_broker_order_reference(
    client_order_id: str,
    *,
    broker_name: str | None = None,
    broker_order_id: str | None = None,
) -> None:
    await execute(
        """
        UPDATE broker_orders
        SET broker_name = COALESCE($2, broker_name),
            broker_order_id = COALESCE($3, broker_order_id),
            updated_at = NOW()
        WHERE client_order_id = $1
        """,
        client_order_id,
        broker_name,
        broker_order_id,
    )


async def upsert_kis_broker_order(
    *,
    account_scope: AccountScope,
    broker_order_id: str,
    ticker: str,
    name: str,
    side: str,
    requested_quantity: int,
    requested_price: int,
    filled_quantity: int,
    avg_fill_price: int | None,
    status: str,
    requested_at: datetime | None,
    filled_at: datetime | None,
    signal_source: str = "BLEND",
    agent_id: str = "kis_reconciler",
) -> None:
    scope = normalize_account_scope(account_scope)
    client_order_id = f"kis-sync-{broker_order_id}"
    exists = await fetchval(
        """
        SELECT 1
        FROM broker_orders
        WHERE client_order_id = $1
        LIMIT 1
        """,
        client_order_id,
    )

    if exists:
        await execute(
            """
            UPDATE broker_orders
            SET broker_name = '한국투자증권 KIS',
                ticker = $2,
                name = $3,
                side = $4,
                requested_quantity = $5,
                requested_price = $6,
                filled_quantity = $7,
                avg_fill_price = $8,
                status = $9,
                signal_source = COALESCE(signal_source, $10),
                agent_id = COALESCE(agent_id, $11),
                broker_order_id = $12,
                requested_at = COALESCE($13, requested_at),
                filled_at = COALESCE($14, filled_at),
                updated_at = NOW()
            WHERE client_order_id = $1
            """,
            client_order_id,
            ticker,
            name,
            side,
            requested_quantity,
            requested_price,
            filled_quantity,
            avg_fill_price,
            status,
            signal_source,
            agent_id,
            broker_order_id,
            requested_at,
            filled_at,
        )
        return

    await execute(
        """
        INSERT INTO broker_orders (
            client_order_id, account_scope, broker_name, ticker, name, side,
            order_type, requested_quantity, requested_price,
            filled_quantity, avg_fill_price, status,
            signal_source, agent_id, broker_order_id, rejection_reason,
            requested_at, filled_at, created_at, updated_at
        ) VALUES (
            $1, $2, '한국투자증권 KIS', $3, $4, $5,
            'MARKET', $6, $7,
            $8, $9, $10,
            $11, $12, $13, NULL,
            COALESCE($14, NOW()), $15, NOW(), NOW()
        )
        """,
        client_order_id,
        scope,
        ticker,
        name,
        side,
        requested_quantity,
        requested_price,
        filled_quantity,
        avg_fill_price,
        status,
        signal_source,
        agent_id,
        broker_order_id,
        requested_at,
        filled_at,
    )


async def list_broker_orders(account_scope: AccountScope = "paper", limit: int = 50) -> list[dict]:
    scope = normalize_account_scope(account_scope)
    rows = await fetch(
        """
        SELECT
            client_order_id, account_scope, broker_name, ticker, name, side, order_type,
            requested_quantity, requested_price, filled_quantity, avg_fill_price, status,
            signal_source, agent_id, broker_order_id, rejection_reason,
            requested_at, filled_at
        FROM broker_orders
        WHERE account_scope = $1
        ORDER BY requested_at DESC
        LIMIT $2
        """,
        scope,
        limit,
    )
    return [dict(r) for r in rows]


async def record_account_snapshot(
    account_scope: AccountScope,
    cash_balance: int,
    buying_power: int,
    position_market_value: int,
    total_equity: int,
    realized_pnl: int,
    unrealized_pnl: int,
    position_count: int,
    snapshot_source: str = "broker",
) -> None:
    scope = normalize_account_scope(account_scope)
    await execute(
        """
        INSERT INTO account_snapshots (
            account_scope, cash_balance, buying_power, position_market_value,
            total_equity, realized_pnl, unrealized_pnl, position_count,
            snapshot_source, snapshot_at
        ) VALUES (
            $1, $2, $3, $4,
            $5, $6, $7, $8,
            $9, NOW()
        )
        """,
        scope,
        cash_balance,
        buying_power,
        position_market_value,
        total_equity,
        realized_pnl,
        unrealized_pnl,
        position_count,
        snapshot_source,
    )


async def latest_account_snapshot(account_scope: AccountScope = "paper") -> Optional[dict]:
    scope = normalize_account_scope(account_scope)
    row = await fetchrow(
        """
        SELECT
            account_scope, cash_balance, buying_power, position_market_value,
            total_equity, realized_pnl, unrealized_pnl, position_count,
            snapshot_source, snapshot_at
        FROM account_snapshots
        WHERE account_scope = $1
        ORDER BY snapshot_at DESC
        LIMIT 1
        """,
        scope,
    )
    return dict(row) if row else None


async def list_account_snapshots(account_scope: AccountScope = "paper", limit: int = 30) -> list[dict]:
    scope = normalize_account_scope(account_scope)
    rows = await fetch(
        """
        SELECT
            account_scope, cash_balance, buying_power, position_market_value,
            total_equity, realized_pnl, unrealized_pnl, position_count,
            snapshot_source, snapshot_at
        FROM account_snapshots
        WHERE account_scope = $1
        ORDER BY snapshot_at DESC
        LIMIT $2
        """,
        scope,
        limit,
    )
    return [dict(r) for r in rows]


async def get_trading_account(account_scope: AccountScope = "paper") -> Optional[dict]:
    scope = normalize_account_scope(account_scope)
    row = await fetchrow(
        """
        SELECT account_scope, broker_name, account_label, base_currency, seed_capital,
               cash_balance, buying_power, total_equity, is_active, last_synced_at
        FROM trading_accounts
        WHERE account_scope = $1
        LIMIT 1
        """,
        scope,
    )
    return dict(row) if row else None


async def upsert_trading_account(
    account_scope: AccountScope,
    broker_name: str,
    account_label: str,
    base_currency: str = "KRW",
    seed_capital: int = 10_000_000,
    cash_balance: int = 10_000_000,
    buying_power: int = 10_000_000,
    total_equity: int = 10_000_000,
    is_active: bool = False,
) -> None:
    scope = normalize_account_scope(account_scope)
    await execute(
        """
        INSERT INTO trading_accounts (
            account_scope, broker_name, account_label, base_currency,
            seed_capital, cash_balance, buying_power, total_equity, is_active, last_synced_at, updated_at
        ) VALUES (
            $1, $2, $3, $4,
            $5, $6, $7, $8, $9, NOW(), NOW()
        )
        ON CONFLICT (account_scope)
        DO UPDATE SET
            broker_name = EXCLUDED.broker_name,
            account_label = EXCLUDED.account_label,
            base_currency = EXCLUDED.base_currency,
            seed_capital = EXCLUDED.seed_capital,
            cash_balance = EXCLUDED.cash_balance,
            buying_power = EXCLUDED.buying_power,
            total_equity = EXCLUDED.total_equity,
            is_active = EXCLUDED.is_active,
            last_synced_at = NOW(),
            updated_at = NOW()
        """,
        scope,
        broker_name,
        account_label,
        base_currency,
        seed_capital,
        cash_balance,
        buying_power,
        total_equity,
        is_active,
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
    requested_paper_enabled: bool,
    requested_real_enabled: bool,
    requested_primary_account_scope: str,
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
            requested_paper_enabled,
            requested_real_enabled,
            requested_primary_account_scope,
            confirmation_code_ok,
            readiness_passed,
            readiness_summary,
            applied,
            message
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)
        """,
        requested_by_email,
        requested_by_user_id,
        requested_mode_is_paper,
        requested_paper_enabled,
        requested_real_enabled,
        requested_primary_account_scope,
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


async def fetch_operational_audits(limit: int = 20, audit_type: str | None = None) -> list[dict]:
    if audit_type:
        rows = await fetch(
            """
            SELECT id, audit_type, passed, summary, details, executed_by, created_at
            FROM operational_audits
            WHERE audit_type = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            audit_type,
            limit,
        )
    else:
        rows = await fetch(
            """
            SELECT id, audit_type, passed, summary, details, executed_by, created_at
            FROM operational_audits
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


async def fetch_real_trading_audits(limit: int = 20) -> list[dict]:
    rows = await fetch(
        """
        SELECT id, requested_at, requested_by_email, requested_by_user_id,
               requested_mode_is_paper,
               requested_paper_enabled,
               requested_real_enabled,
               requested_primary_account_scope,
               confirmation_code_ok, readiness_passed,
               readiness_summary, applied, message
        FROM real_trading_audit
        ORDER BY requested_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def insert_paper_trading_run(
    scenario: str,
    simulated_days: int,
    start_date: date,
    end_date: date,
    trade_count: int,
    return_pct: float,
    benchmark_return_pct: float | None,
    max_drawdown_pct: float | None,
    sharpe_ratio: float | None,
    passed: bool,
    summary: str,
    report: dict[str, Any] | None = None,
) -> None:
    await execute(
        """
        INSERT INTO paper_trading_runs (
            scenario, simulated_days, start_date, end_date,
            trade_count, return_pct, benchmark_return_pct,
            max_drawdown_pct, sharpe_ratio, passed, summary, report
        ) VALUES (
            $1, $2, $3, $4,
            $5, $6, $7,
            $8, $9, $10, $11, $12::jsonb
        )
        """,
        scenario,
        simulated_days,
        start_date,
        end_date,
        trade_count,
        return_pct,
        benchmark_return_pct,
        max_drawdown_pct,
        sharpe_ratio,
        passed,
        summary,
        json.dumps(report or {}, ensure_ascii=False),
    )


async def fetch_latest_paper_trading_run(scenario: str | None = None) -> Optional[dict]:
    if scenario:
        row = await fetchrow(
            """
            SELECT *
            FROM paper_trading_runs
            WHERE scenario = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            scenario,
        )
    else:
        row = await fetchrow(
            """
            SELECT *
            FROM paper_trading_runs
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
    return dict(row) if row else None
