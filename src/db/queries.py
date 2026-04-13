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
from src.constants import PAPER_TRADING_INITIAL_CAPITAL
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


async def insert_tick_batch(ticks: list) -> int:
    """tick_data 테이블에 틱 배치를 INSERT합니다.

    ON CONFLICT 시 무시합니다 (동일 instrument_id + timestamp_kst).

    Args:
        ticks: TickData 객체 리스트 (instrument_id, timestamp_kst, price, volume, change_pct, source)

    Returns:
        INSERT 시도 건수
    """
    if not ticks:
        return 0

    query = """
        INSERT INTO tick_data (
            instrument_id, timestamp_kst,
            price, volume, change_pct, source
        ) VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (instrument_id, timestamp_kst) DO NOTHING
    """
    await executemany(query, [
        (
            t.instrument_id,
            t.timestamp_kst,
            int(t.price),
            int(t.volume),
            t.change_pct,
            t.source,
        )
        for t in ticks
    ])
    return len(ticks)


async def get_ohlcv_bars(
    instrument_id: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """tick_data에서 분봉/시간봉 OHLCV를 실시간 집계합니다.

    Args:
        instrument_id: 종목 ID (예: '005930.KS')
        interval: '1min', '5min', '15min', '1hour'
        start: 조회 시작 시각 (KST)
        end: 조회 종료 시각 (KST)

    Returns:
        [{timestamp_kst, open, high, low, close, volume}, ...]
    """
    # interval → SQL bucket expression
    bucket_map = {
        "1min": "date_trunc('minute', timestamp_kst)",
        "5min": "to_timestamp(floor(extract(epoch FROM timestamp_kst) / 300) * 300) AT TIME ZONE 'Asia/Seoul'",
        "15min": "to_timestamp(floor(extract(epoch FROM timestamp_kst) / 900) * 900) AT TIME ZONE 'Asia/Seoul'",
        "1hour": "date_trunc('hour', timestamp_kst)",
    }
    bucket_expr = bucket_map.get(interval)
    if not bucket_expr:
        raise ValueError(f"지원하지 않는 interval: {interval}. 허용: {list(bucket_map.keys())}")

    query = f"""
        SELECT
            {bucket_expr}  AS bucket,
            (array_agg(price ORDER BY timestamp_kst ASC))[1]  AS open,
            MAX(price)     AS high,
            MIN(price)     AS low,
            (array_agg(price ORDER BY timestamp_kst DESC))[1] AS close,
            SUM(volume)    AS volume
        FROM tick_data
        WHERE instrument_id = $1
          AND timestamp_kst >= $2
          AND timestamp_kst < $3
        GROUP BY bucket
        ORDER BY bucket ASC
    """
    rows = await fetch(query, instrument_id, start, end)
    return [
        {
            "timestamp_kst": row["bucket"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
        }
        for row in rows
    ]


async def aggregate_ticks_to_minutes(start: datetime, end: datetime) -> int:
    """tick_data를 1분봉으로 집계하여 ohlcv_minute에 UPSERT합니다.

    Args:
        start: 집계 시작 시각 (KST)
        end: 집계 종료 시각 (KST)

    Returns:
        집계된 행 수
    """
    query = """
        INSERT INTO ohlcv_minute
            (instrument_id, bucket_at, open, high, low, close,
             volume, trade_count, vwap)
        SELECT
            instrument_id,
            date_trunc('minute', timestamp_kst) AS bucket_at,
            (array_agg(price ORDER BY timestamp_kst ASC))[1]   AS open,
            MAX(price)                                           AS high,
            MIN(price)                                           AS low,
            (array_agg(price ORDER BY timestamp_kst DESC))[1]  AS close,
            SUM(volume)                                          AS volume,
            COUNT(*)                                             AS trade_count,
            CASE WHEN SUM(volume) > 0
                 THEN SUM(price::numeric * volume) / SUM(volume)
                 ELSE 0 END                                      AS vwap
        FROM tick_data
        WHERE timestamp_kst >= $1
          AND timestamp_kst < $2
        GROUP BY instrument_id, date_trunc('minute', timestamp_kst)
        ON CONFLICT (instrument_id, bucket_at) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
            close = EXCLUDED.close, volume = EXCLUDED.volume,
            trade_count = EXCLUDED.trade_count, vwap = EXCLUDED.vwap
    """
    result = await execute(query, start, end)
    # asyncpg execute() returns status string, e.g. "INSERT 0 150"
    return int(result.split()[-1]) if result else 0


async def fetch_minute_bars(
    instrument_id: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """ohlcv_minute에서 분봉 데이터를 조회합니다."""
    rows = await fetch(
        """
        SELECT instrument_id, bucket_at, open, high, low, close,
               volume, trade_count, vwap
        FROM ohlcv_minute
        WHERE instrument_id = $1
          AND bucket_at >= $2
          AND bucket_at < $3
        ORDER BY bucket_at ASC
        """,
        instrument_id, start, end,
    )
    return [dict(row) for row in rows]


async def list_tickers(mode: str = "paper", limit: int = 30) -> list[dict]:
    rows = await fetch(
        """
        SELECT i.instrument_id, i.ticker, sm.name, i.market_id AS market,
               tu.priority, tu.max_weight_pct
        FROM instruments i
        JOIN trading_universe tu ON i.instrument_id = tu.instrument_id
        LEFT JOIN krx_stock_master sm ON i.ticker = sm.ticker
        WHERE tu.account_scope = $1 AND i.is_active = TRUE
        ORDER BY tu.priority DESC, i.instrument_id
        LIMIT $2
        """,
        mode,
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

    # instrument_id 또는 ticker 모두 허용
    conditions = [
        "(o.instrument_id = $1 OR i.ticker = $1)",
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
            o.instrument_id, i.ticker, sm.name,
            o.traded_at, o.open, o.high, o.low, o.close, o.volume,
            o.change_pct, o.adj_close
        FROM ohlcv_daily o
        JOIN instruments i ON o.instrument_id = i.instrument_id
        LEFT JOIN krx_stock_master sm ON i.ticker = sm.ticker
        WHERE {' AND '.join(conditions)}
        ORDER BY o.traded_at DESC
        {limit_sql}
        """,
        *params,
    )
    return [dict(r) for r in rows]


async def fetch_ohlcv_range(ticker: str, start: date, end: date) -> list[dict]:
    """날짜 범위로 ohlcv_daily를 조회합니다.

    ticker는 instrument_id(005930.KS) 또는 raw_code(005930) 모두 허용합니다.
    반환 형식은 fetch_recent_market_data()와 동일합니다.
    """
    rows = await fetch(
        """
        SELECT
            o.instrument_id, i.ticker, sm.name,
            o.traded_at, o.open, o.high, o.low, o.close, o.volume,
            o.change_pct, o.adj_close
        FROM ohlcv_daily o
        JOIN instruments i ON o.instrument_id = i.instrument_id
        LEFT JOIN krx_stock_master sm ON i.ticker = sm.ticker
        WHERE (o.instrument_id = $1 OR i.ticker = $1)
          AND o.traded_at >= $2
          AND o.traded_at <= $3
        ORDER BY o.traded_at ASC
        """,
        ticker,
        start,
        end,
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
        WHERE o.instrument_id = $1 OR i.ticker = $1
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
    strategy_id: str | None = None,
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
            ticker, name, quantity, avg_price, current_price, is_paper, account_scope, strategy_id, opened_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW())
        ON CONFLICT (ticker, account_scope, COALESCE(strategy_id, ''))
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
        strategy_id or "",
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


async def insert_model_role_config(
    *,
    config_key: str,
    strategy_code: str,
    role: str,
    role_label: str,
    agent_id: str,
    llm_model: str,
    persona: str,
    execution_order: int,
) -> dict:
    """새 모델 역할을 추가한다. config_key 중복 시 예외."""
    rows = await fetch(
        """
        INSERT INTO model_role_configs (
            config_key, strategy_code, role, role_label, agent_id,
            llm_model, persona, execution_order, is_enabled, created_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, true, NOW(), NOW()
        )
        RETURNING
            config_key, strategy_code, role, role_label, agent_id,
            llm_model, persona, execution_order, is_enabled,
            to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS updated_at
        """,
        config_key, strategy_code, role, role_label, agent_id,
        llm_model, persona, execution_order,
    )
    return dict(rows[0])


async def delete_model_role_config(config_key: str) -> str | None:
    """모델 역할을 삭제한다. 삭제된 역할의 strategy_code를 반환, 없으면 None."""
    rows = await fetch(
        "DELETE FROM model_role_configs WHERE config_key = $1 RETURNING strategy_code",
        config_key,
    )
    return rows[0]["strategy_code"] if rows else None


async def reorder_model_role_configs(strategy_code: str) -> None:
    """해당 전략의 역할 번호를 1부터 순차적으로 재정렬한다."""
    rows = await fetch(
        """
        SELECT config_key, role
        FROM model_role_configs
        WHERE strategy_code = $1
        ORDER BY execution_order, config_key
        """,
        strategy_code,
    )
    for idx, row in enumerate(rows, 1):
        role = row["role"]
        if strategy_code == "A":
            role_label = f"Predictor {idx}"
            agent_id = f"predictor_{idx}"
        else:
            role_label = f"{role.capitalize()} {idx}"
            agent_id = f"consensus_{role}_{idx}"
        await execute(
            """
            UPDATE model_role_configs
            SET execution_order = $2, role_label = $3, agent_id = $4, updated_at = NOW()
            WHERE config_key = $1
            """,
            row["config_key"], idx, role_label, agent_id,
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
    seed_capital: int = PAPER_TRADING_INITIAL_CAPITAL,
    cash_balance: int = PAPER_TRADING_INITIAL_CAPITAL,
    buying_power: int = PAPER_TRADING_INITIAL_CAPITAL,
    total_equity: int = PAPER_TRADING_INITIAL_CAPITAL,
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


async def insert_collector_error(
    source: str,
    ticker: str,
    error_type: str,
    message: str,
) -> None:
    """collector_errors 테이블에 수집 에러를 기록합니다."""
    await execute(
        """
        INSERT INTO collector_errors (source, ticker, error_type, message)
        VALUES ($1, $2, $3, $4)
        """,
        source,
        ticker,
        error_type,
        message,
    )


async def insert_daily_ranking(
    ranking_date: date,
    ranking_type: str,
    rank: int,
    ticker: str,
    name: str,
    value: Optional[float] = None,
    change_pct: Optional[float] = None,
    extra: Optional[dict] = None,
) -> None:
    """daily_rankings 테이블에 종목 랭킹을 기록합니다."""
    await execute(
        """
        INSERT INTO daily_rankings (
            ranking_date, ranking_type, rank, ticker, name,
            value, change_pct, extra
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
        ON CONFLICT (ranking_date, ranking_type, rank)
        DO UPDATE SET
            ticker = EXCLUDED.ticker,
            name = EXCLUDED.name,
            value = EXCLUDED.value,
            change_pct = EXCLUDED.change_pct,
            extra = EXCLUDED.extra
        """,
        ranking_date,
        ranking_type,
        rank,
        ticker,
        name,
        value,
        change_pct,
        json.dumps(extra or {}, ensure_ascii=False),
    )


async def insert_daily_rankings_batch(rankings: list[dict]) -> int:
    """daily_rankings 테이블에 종목 랭킹을 배치로 기록합니다."""
    if not rankings:
        return 0
    for r in rankings:
        await insert_daily_ranking(
            ranking_date=r["ranking_date"],
            ranking_type=r["ranking_type"],
            rank=r["rank"],
            ticker=r["ticker"],
            name=r["name"],
            value=r.get("value"),
            change_pct=r.get("change_pct"),
            extra=r.get("extra"),
        )
    return len(rankings)


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


# ── RL 학습 대상 종목 (rl_targets) ────────────────────────────────────


async def list_rl_targets(*, active_only: bool = True) -> list[dict]:
    """rl_targets에서 학습 대상 종목 목록을 반환합니다."""
    if active_only:
        rows = await fetch(
            """
            SELECT t.instrument_id, t.data_scope, t.is_active, t.memo,
                   t.added_at, t.updated_at
            FROM rl_targets t
            WHERE t.is_active = true
            ORDER BY t.instrument_id
            """
        )
    else:
        rows = await fetch(
            """
            SELECT t.instrument_id, t.data_scope, t.is_active, t.memo,
                   t.added_at, t.updated_at
            FROM rl_targets t
            ORDER BY t.instrument_id
            """
        )
    return [dict(r) for r in rows]


async def upsert_rl_targets(tickers: list[str], data_scope: str = "daily") -> list[str]:
    """rl_targets에 종목을 추가합니다. 이미 존재하면 is_active=true로 복원합니다.
    Returns: 실제로 새로 추가되거나 재활성화된 instrument_id 리스트
    """
    if not tickers:
        return []
    added: list[str] = []
    for ticker in tickers:
        await execute(
            """
            INSERT INTO rl_targets (instrument_id, data_scope)
            VALUES ($1, $2)
            ON CONFLICT (instrument_id) DO UPDATE
                SET is_active = true, updated_at = now()
            """,
            ticker,
            data_scope,
        )
        added.append(ticker)
    return added


async def remove_rl_target(ticker: str) -> bool:
    """rl_targets에서 종목을 삭제합니다. Returns: 삭제 여부"""
    result = await execute(
        "DELETE FROM rl_targets WHERE instrument_id = $1",
        ticker,
    )
    # asyncpg execute returns status string like "DELETE 1" or "DELETE 0"
    return result is not None and result.endswith("1")


async def list_rl_target_tickers(*, active_only: bool = True) -> list[str]:
    """rl_targets에서 instrument_id 목록만 반환합니다 (경량 조회)."""
    if active_only:
        rows = await fetch(
            "SELECT instrument_id FROM rl_targets WHERE is_active = true ORDER BY instrument_id"
        )
    else:
        rows = await fetch(
            "SELECT instrument_id FROM rl_targets ORDER BY instrument_id"
        )
    return [row["instrument_id"] for row in rows]


# ── RL 학습 작업 (rl_training_jobs) ──────────────────────────────────────


async def insert_training_job(
    job_id: str,
    instrument_id: str,
    *,
    policy_family: str = "",
    dataset_days: int = 720,
) -> str:
    """rl_training_jobs에 새 작업을 queued 상태로 생성합니다."""
    if not policy_family:
        from src.agents.rl_experiment_manager import get_available_profiles
        profiles = get_available_profiles()
        policy_family = profiles[0] if profiles else "tabular_q_v2_momentum"
    await execute(
        """
        INSERT INTO rl_training_jobs (job_id, instrument_id, policy_family, dataset_days)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (job_id) DO NOTHING
        """,
        job_id, instrument_id, policy_family, dataset_days,
    )
    return job_id


async def update_training_job_status(
    job_id: str,
    status: str,
    *,
    result_policy_id: str | None = None,
    error_message: str | None = None,
) -> None:
    """학습 작업 상태를 업데이트합니다."""
    if status == "running":
        await execute(
            "UPDATE rl_training_jobs SET status = $1, started_at = now() WHERE job_id = $2",
            status, job_id,
        )
    elif status in ("completed", "failed"):
        await execute(
            """
            UPDATE rl_training_jobs
            SET status = $1, completed_at = now(),
                result_policy_id = COALESCE($2, result_policy_id),
                error_message = $3
            WHERE job_id = $4
            """,
            status, result_policy_id, error_message, job_id,
        )
    else:
        await execute(
            "UPDATE rl_training_jobs SET status = $1 WHERE job_id = $2",
            status, job_id,
        )


async def update_training_job_progress(job_id: str, progress_pct: int) -> None:
    """학습 작업 진행률(0-100)을 업데이트합니다."""
    await execute(
        "UPDATE rl_training_jobs SET progress_pct = $1 WHERE job_id = $2",
        min(100, max(0, progress_pct)), job_id,
    )


async def fetch_training_job(job_id: str) -> dict | None:
    """학습 작업 상세를 반환합니다."""
    row = await fetchrow(
        "SELECT * FROM rl_training_jobs WHERE job_id = $1", job_id
    )
    return dict(row) if row else None


async def list_training_jobs(
    *, instrument_id: str | None = None, status: str | None = None
) -> list[dict]:
    """학습 작업 목록을 반환합니다."""
    conditions: list[str] = []
    params: list = []
    idx = 1
    if instrument_id:
        conditions.append(f"instrument_id = ${idx}")
        params.append(instrument_id)
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await fetch(
        f"SELECT * FROM rl_training_jobs {where} ORDER BY created_at DESC",
        *params,
    )
    return [dict(r) for r in rows]


async def find_queued_training_job(instrument_id: str) -> dict | None:
    """특정 종목의 queued 상태 학습 작업을 반환합니다."""
    row = await fetchrow(
        """
        SELECT * FROM rl_training_jobs
        WHERE instrument_id = $1 AND status = 'queued'
        ORDER BY created_at DESC LIMIT 1
        """,
        instrument_id,
    )
    return dict(row) if row else None


async def delete_training_job(job_id: str) -> bool:
    """학습 작업을 삭제합니다. running 상태는 삭제 불가."""
    row = await fetchrow(
        "SELECT status FROM rl_training_jobs WHERE job_id = $1", job_id
    )
    if not row:
        return False
    if row["status"] == "running":
        raise ValueError("실행 중인 작업은 삭제할 수 없습니다")
    # 연관 실험 레코드의 job_id 참조를 해제
    await execute(
        "UPDATE rl_experiments SET job_id = NULL WHERE job_id = $1", job_id
    )
    await execute("DELETE FROM rl_training_jobs WHERE job_id = $1", job_id)
    return True


# ── RL 실험 기록 (rl_experiments) ────────────────────────────────────────


async def insert_experiment(
    *,
    run_id: str,
    job_id: str | None,
    instrument_id: str,
    policy_id: str | None,
    profile_id: str | None,
    algorithm: str | None,
    return_pct: float | None,
    baseline_return_pct: float | None,
    excess_return_pct: float | None,
    max_drawdown_pct: float | None,
    trades: int | None,
    win_rate: float | None,
    holdout_steps: int | None,
    walk_forward_passed: bool = False,
    walk_forward_consistency: float | None = None,
    approved: bool = False,
    deployed: bool = False,
) -> str:
    """rl_experiments에 실험 결과를 기록합니다."""
    await execute(
        """
        INSERT INTO rl_experiments (
            run_id, job_id, instrument_id, policy_id, profile_id, algorithm,
            return_pct, baseline_return_pct, excess_return_pct, max_drawdown_pct,
            trades, win_rate, holdout_steps,
            walk_forward_passed, walk_forward_consistency,
            approved, deployed
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9, $10,
            $11, $12, $13,
            $14, $15,
            $16, $17
        )
        ON CONFLICT (run_id) DO NOTHING
        """,
        run_id, job_id, instrument_id, policy_id, profile_id, algorithm,
        return_pct, baseline_return_pct, excess_return_pct, max_drawdown_pct,
        trades, win_rate, holdout_steps,
        walk_forward_passed, walk_forward_consistency,
        approved, deployed,
    )
    return run_id


async def list_experiments(
    *, instrument_id: str | None = None, job_id: str | None = None
) -> list[dict]:
    """실험 기록 목록을 반환합니다."""
    conditions: list[str] = []
    params: list = []
    idx = 1
    if instrument_id:
        conditions.append(f"instrument_id = ${idx}")
        params.append(instrument_id)
        idx += 1
    if job_id:
        conditions.append(f"job_id = ${idx}")
        params.append(job_id)
        idx += 1
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await fetch(
        f"SELECT * FROM rl_experiments {where} ORDER BY created_at DESC",
        *params,
    )
    return [dict(r) for r in rows]


# ── Prediction Schedule ───────────────────────────────────────────────────


async def fetch_prediction_schedules() -> list[dict]:
    """prediction_schedule 테이블에서 전략별 예측 주기를 조회한다."""
    rows = await fetch(
        "SELECT strategy_code, interval_minutes, is_enabled, last_run_at, updated_at "
        "FROM prediction_schedule ORDER BY strategy_code"
    )
    return [dict(r) for r in rows]


async def upsert_prediction_schedule(
    strategy_code: str,
    interval_minutes: int,
    is_enabled: bool = True,
) -> dict:
    """전략별 예측 주기를 생성/수정한다."""
    row = await fetchrow(
        """
        INSERT INTO prediction_schedule (strategy_code, interval_minutes, is_enabled, updated_at)
        VALUES ($1, $2, $3, now())
        ON CONFLICT (strategy_code) DO UPDATE
            SET interval_minutes = $2, is_enabled = $3, updated_at = now()
        RETURNING strategy_code, interval_minutes, is_enabled, last_run_at, updated_at
        """,
        strategy_code,
        interval_minutes,
        is_enabled,
    )
    return dict(row)


async def touch_prediction_schedule(strategy_code: str) -> None:
    """전략 실행 후 last_run_at을 갱신한다."""
    await execute(
        "UPDATE prediction_schedule SET last_run_at = now() WHERE strategy_code = $1",
        strategy_code,
    )
