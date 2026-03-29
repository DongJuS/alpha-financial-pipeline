"""
src/db/marketplace_queries.py — 마켓플레이스 확장 DB 쿼리

stock_master, theme_stocks, macro_indicators, daily_rankings, watchlist 테이블 조회/삽입.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from src.db.models import (
    DailyRanking,
    MacroIndicator,
    StockMasterRecord,
    WatchlistItem,
)
from src.utils.db_client import execute, executemany, fetch, fetchrow, fetchval


# ── stock_master ─────────────────────────────────────────────────────────────


async def upsert_stock_master(records: list[StockMasterRecord]) -> int:
    """stock_master 테이블에 bulk upsert하고 반영 건수를 반환합니다."""
    if not records:
        return 0

    query = """
        INSERT INTO stock_master (
            ticker, name, market, sector, industry, market_cap,
            listing_date, is_etf, is_etn, is_active, tier, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9, $10, $11, NOW()
        )
        ON CONFLICT (ticker)
        DO UPDATE SET
            name = EXCLUDED.name,
            market = EXCLUDED.market,
            sector = COALESCE(EXCLUDED.sector, stock_master.sector),
            industry = COALESCE(EXCLUDED.industry, stock_master.industry),
            market_cap = COALESCE(EXCLUDED.market_cap, stock_master.market_cap),
            listing_date = COALESCE(EXCLUDED.listing_date, stock_master.listing_date),
            is_etf = EXCLUDED.is_etf,
            is_etn = EXCLUDED.is_etn,
            is_active = EXCLUDED.is_active,
            updated_at = NOW()
    """
    await executemany(query, [
        (
            r.ticker, r.name, r.market, r.sector, r.industry, r.market_cap,
            r.listing_date, r.is_etf, r.is_etn, r.is_active, r.tier,
        )
        for r in records
    ])
    return len(records)


async def update_stock_sectors(sector_map: dict[str, tuple[Optional[str], Optional[str]]]) -> int:
    """ticker → (sector, industry) 맵으로 NULL 섹터를 일괄 업데이트합니다.

    이미 sector 값이 있는 종목은 덮어쓰지 않습니다 (COALESCE 보호).
    Returns: 업데이트 대상 건수
    """
    if not sector_map:
        return 0

    query = """
        UPDATE stock_master
        SET
            sector   = COALESCE(stock_master.sector,   $2),
            industry = COALESCE(stock_master.industry, $3),
            updated_at = NOW()
        WHERE ticker = $1
          AND (stock_master.sector IS NULL OR stock_master.industry IS NULL)
    """
    await executemany(query, [
        (ticker, sector, industry)
        for ticker, (sector, industry) in sector_map.items()
        if sector or industry
    ])
    return len(sector_map)


async def get_stock_master(ticker: str) -> Optional[dict]:
    """단일 종목 마스터 조회."""
    row = await fetchrow(
        """
        SELECT ticker, name, market, sector, industry, market_cap,
               listing_date, is_etf, is_etn, is_active, tier, updated_at
        FROM stock_master
        WHERE ticker = $1
        """,
        ticker,
    )
    return dict(row) if row else None


async def list_stock_master(
    *,
    market: Optional[str] = None,
    sector: Optional[str] = None,
    is_etf: Optional[bool] = None,
    tier: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """필터 조건으로 종목 마스터 목록을 조회합니다."""
    conditions: list[str] = ["is_active = TRUE"]
    params: list[Any] = []

    if market:
        params.append(market)
        conditions.append(f"market = ${len(params)}")
    if sector:
        params.append(sector)
        conditions.append(f"sector = ${len(params)}")
    if is_etf is not None:
        params.append(is_etf)
        conditions.append(f"is_etf = ${len(params)}")
    if tier:
        params.append(tier)
        conditions.append(f"tier = ${len(params)}")
    if search:
        params.append(f"%{search}%")
        conditions.append(f"(name ILIKE ${len(params)} OR ticker ILIKE ${len(params)})")

    params.append(limit)
    params.append(offset)
    where = " AND ".join(conditions)

    rows = await fetch(
        f"""
        SELECT ticker, name, market, sector, industry, market_cap,
               listing_date, is_etf, is_etn, is_active, tier
        FROM stock_master
        WHERE {where}
        ORDER BY market_cap DESC NULLS LAST, ticker
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )
    return [dict(r) for r in rows]


async def count_stock_master(
    *,
    market: Optional[str] = None,
    sector: Optional[str] = None,
    is_etf: Optional[bool] = None,
    search: Optional[str] = None,
) -> int:
    """필터 조건에 맞는 종목 수를 반환합니다."""
    conditions: list[str] = ["is_active = TRUE"]
    params: list[Any] = []

    if market:
        params.append(market)
        conditions.append(f"market = ${len(params)}")
    if sector:
        params.append(sector)
        conditions.append(f"sector = ${len(params)}")
    if is_etf is not None:
        params.append(is_etf)
        conditions.append(f"is_etf = ${len(params)}")
    if search:
        params.append(f"%{search}%")
        conditions.append(f"(name ILIKE ${len(params)} OR ticker ILIKE ${len(params)})")

    where = " AND ".join(conditions)
    total = await fetchval(
        f"SELECT COUNT(*) FROM stock_master WHERE {where}",
        *params,
    )
    return int(total or 0)


async def get_sectors() -> list[dict]:
    """섹터별 종목 수를 반환합니다."""
    rows = await fetch(
        """
        SELECT sector, COUNT(*) AS stock_count,
               COALESCE(SUM(market_cap), 0) AS total_market_cap
        FROM stock_master
        WHERE is_active = TRUE AND sector IS NOT NULL AND sector != ''
          AND is_etf = FALSE AND is_etn = FALSE
        GROUP BY sector
        ORDER BY total_market_cap DESC
        """
    )
    return [dict(r) for r in rows]


async def search_stocks(query: str, limit: int = 20) -> list[dict]:
    """종목명 또는 티커로 검색합니다."""
    rows = await fetch(
        """
        SELECT ticker, name, market, sector, is_etf, market_cap
        FROM stock_master
        WHERE is_active = TRUE
          AND (name ILIKE $1 OR ticker ILIKE $1)
        ORDER BY market_cap DESC NULLS LAST
        LIMIT $2
        """,
        f"%{query}%",
        limit,
    )
    return [dict(r) for r in rows]


# ── theme_stocks ─────────────────────────────────────────────────────────────


async def upsert_theme_stocks(
    theme_slug: str,
    theme_name: str,
    tickers: list[str],
    leader_tickers: Optional[list[str]] = None,
) -> int:
    """테마에 종목 매핑을 upsert합니다."""
    leaders = set(leader_tickers or [])
    query = """
        INSERT INTO theme_stocks (theme_slug, theme_name, ticker, is_leader)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (theme_slug, ticker)
        DO UPDATE SET
            theme_name = EXCLUDED.theme_name,
            is_leader = EXCLUDED.is_leader
    """
    await executemany(query, [
        (theme_slug, theme_name, ticker, ticker in leaders)
        for ticker in tickers
    ])
    return len(tickers)


async def get_themes() -> list[dict]:
    """전체 테마 목록과 종목 수를 반환합니다."""
    rows = await fetch(
        """
        SELECT theme_slug, theme_name, COUNT(*) AS stock_count,
               COUNT(*) FILTER (WHERE is_leader) AS leader_count
        FROM theme_stocks
        GROUP BY theme_slug, theme_name
        ORDER BY stock_count DESC
        """
    )
    return [dict(r) for r in rows]


async def get_theme_stocks(theme_slug: str) -> list[dict]:
    """특정 테마에 속한 종목 목록을 반환합니다."""
    rows = await fetch(
        """
        SELECT ts.ticker, ts.theme_name, ts.is_leader,
               sm.name, sm.market, sm.sector, sm.market_cap
        FROM theme_stocks ts
        LEFT JOIN stock_master sm ON ts.ticker = sm.ticker
        WHERE ts.theme_slug = $1
        ORDER BY sm.market_cap DESC NULLS LAST
        """,
        theme_slug,
    )
    return [dict(r) for r in rows]


# ── macro_indicators ─────────────────────────────────────────────────────────


async def upsert_macro_indicators(indicators: list[MacroIndicator]) -> int:
    """매크로 지표를 upsert합니다."""
    if not indicators:
        return 0

    query = """
        INSERT INTO macro_indicators (
            category, symbol, name, value, change_pct,
            previous_close, snapshot_date, source, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
        ON CONFLICT (symbol, snapshot_date)
        DO UPDATE SET
            category = EXCLUDED.category,
            name = EXCLUDED.name,
            value = EXCLUDED.value,
            change_pct = EXCLUDED.change_pct,
            previous_close = EXCLUDED.previous_close,
            source = EXCLUDED.source,
            updated_at = NOW()
    """
    await executemany(query, [
        (
            ind.category, ind.symbol, ind.name, ind.value, ind.change_pct,
            ind.previous_close, ind.snapshot_date, ind.source,
        )
        for ind in indicators
    ])
    return len(indicators)


async def get_macro_indicators(
    category: Optional[str] = None,
    snapshot_date: Optional[date] = None,
) -> list[dict]:
    """매크로 지표를 조회합니다."""
    conditions: list[str] = []
    params: list[Any] = []

    if category:
        params.append(category)
        conditions.append(f"category = ${len(params)}")
    if snapshot_date:
        params.append(snapshot_date)
        conditions.append(f"snapshot_date = ${len(params)}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = await fetch(
        f"""
        SELECT DISTINCT ON (symbol)
            category, symbol, name, value::float, change_pct::float,
            previous_close::float, snapshot_date, source, updated_at
        FROM macro_indicators
        {where}
        ORDER BY symbol, snapshot_date DESC
        """,
        *params,
    )
    return [dict(r) for r in rows]


# ── daily_rankings ───────────────────────────────────────────────────────────


async def upsert_daily_rankings(rankings: list[DailyRanking]) -> int:
    """일별 랭킹을 upsert합니다."""
    if not rankings:
        return 0

    query = """
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
    """
    await executemany(query, [
        (
            r.ranking_date, r.ranking_type, r.rank, r.ticker, r.name,
            r.value, r.change_pct,
            json.dumps(r.extra or {}, ensure_ascii=False) if r.extra else None,
        )
        for r in rankings
    ])
    return len(rankings)


async def get_daily_rankings(
    ranking_type: str,
    ranking_date: Optional[date] = None,
    limit: int = 50,
) -> list[dict]:
    """일별 랭킹을 조회합니다."""
    if ranking_date:
        rows = await fetch(
            """
            SELECT ranking_date, ranking_type, rank, ticker, name,
                   value::float, change_pct::float, extra
            FROM daily_rankings
            WHERE ranking_type = $1 AND ranking_date = $2
            ORDER BY rank
            LIMIT $3
            """,
            ranking_type,
            ranking_date,
            limit,
        )
    else:
        # 최신 날짜의 랭킹
        rows = await fetch(
            """
            SELECT ranking_date, ranking_type, rank, ticker, name,
                   value::float, change_pct::float, extra
            FROM daily_rankings
            WHERE ranking_type = $1
              AND ranking_date = (
                  SELECT MAX(ranking_date) FROM daily_rankings WHERE ranking_type = $1
              )
            ORDER BY rank
            LIMIT $2
            """,
            ranking_type,
            limit,
        )
    return [dict(r) for r in rows]


# ── watchlist ────────────────────────────────────────────────────────────────


async def add_watchlist_item(
    user_id: str,
    ticker: str,
    name: str,
    group_name: str = "default",
    price_alert_above: Optional[int] = None,
    price_alert_below: Optional[int] = None,
) -> None:
    """관심 종목을 추가합니다."""
    await execute(
        """
        INSERT INTO watchlist (user_id, group_name, ticker, name, price_alert_above, price_alert_below)
        VALUES ($1::uuid, $2, $3, $4, $5, $6)
        ON CONFLICT (user_id, group_name, ticker)
        DO UPDATE SET
            name = EXCLUDED.name,
            price_alert_above = COALESCE(EXCLUDED.price_alert_above, watchlist.price_alert_above),
            price_alert_below = COALESCE(EXCLUDED.price_alert_below, watchlist.price_alert_below)
        """,
        user_id,
        group_name,
        ticker,
        name,
        price_alert_above,
        price_alert_below,
    )


async def remove_watchlist_item(
    user_id: str,
    ticker: str,
    group_name: str = "default",
) -> bool:
    """관심 종목을 삭제합니다. 삭제 여부를 반환합니다."""
    result = await fetchval(
        """
        DELETE FROM watchlist
        WHERE user_id = $1::uuid AND group_name = $2 AND ticker = $3
        RETURNING id
        """,
        user_id,
        group_name,
        ticker,
    )
    return result is not None


async def get_watchlist(
    user_id: str,
    group_name: Optional[str] = None,
) -> list[dict]:
    """사용자 관심 종목 목록을 조회합니다."""
    if group_name:
        rows = await fetch(
            """
            SELECT w.ticker, w.name, w.group_name,
                   w.price_alert_above, w.price_alert_below, w.added_at,
                   sm.market, sm.sector, sm.market_cap
            FROM watchlist w
            LEFT JOIN stock_master sm ON w.ticker = sm.ticker
            WHERE w.user_id = $1::uuid AND w.group_name = $2
            ORDER BY w.added_at DESC
            """,
            user_id,
            group_name,
        )
    else:
        rows = await fetch(
            """
            SELECT w.ticker, w.name, w.group_name,
                   w.price_alert_above, w.price_alert_below, w.added_at,
                   sm.market, sm.sector, sm.market_cap
            FROM watchlist w
            LEFT JOIN stock_master sm ON w.ticker = sm.ticker
            WHERE w.user_id = $1::uuid
            ORDER BY w.group_name, w.added_at DESC
            """,
            user_id,
        )
    return [dict(r) for r in rows]
