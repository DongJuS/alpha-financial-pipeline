"""
test/test_db_marketplace_queries.py -- src/db/marketplace_queries.py 단위 테스트

DB 없이 실행 가능하도록 src.utils.db_client의 함수를 mock합니다.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


class FakeRecord:
    """asyncpg.Record 호환 가짜 레코드."""

    def __init__(self, d: dict):
        self._d = d

    def __iter__(self):
        return iter(self._d.items())

    def keys(self):
        return self._d.keys()

    def __getitem__(self, k):
        return self._d[k]


# ── upsert_stock_master ─────────────────────────────────────────────────────


class TestUpsertStockMaster:
    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self):
        from src.db.marketplace_queries import upsert_stock_master

        result = await upsert_stock_master([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_upsert_calls_executemany(self):
        from src.db.marketplace_queries import upsert_stock_master
        from src.db.models import StockMasterRecord

        records = [
            StockMasterRecord(
                ticker="005930",
                name="삼성전자",
                market="KOSPI",
                sector="반도체",
                market_cap=500_000_000_000,
            ),
            StockMasterRecord(
                ticker="000660",
                name="SK하이닉스",
                market="KOSPI",
                sector="반도체",
            ),
        ]

        with patch("src.db.marketplace_queries.executemany", new_callable=AsyncMock) as mock_exec:
            result = await upsert_stock_master(records)

        assert result == 2
        mock_exec.assert_awaited_once()
        sql = mock_exec.call_args.args[0]
        assert "stock_master" in sql
        assert "ON CONFLICT (ticker)" in sql


# ── update_stock_sectors ────────────────────────────────────────────────────


class TestUpdateStockSectors:
    @pytest.mark.asyncio
    async def test_empty_map_returns_zero(self):
        from src.db.marketplace_queries import update_stock_sectors

        result = await update_stock_sectors({})
        assert result == 0

    @pytest.mark.asyncio
    async def test_filters_none_sectors(self):
        from src.db.marketplace_queries import update_stock_sectors

        sector_map = {
            "005930": ("반도체", "메모리"),
            "000660": (None, None),  # both None => filtered out
        }

        with patch("src.db.marketplace_queries.executemany", new_callable=AsyncMock) as mock_exec:
            result = await update_stock_sectors(sector_map)

        assert result == 2  # returns len(sector_map) regardless of filtering
        # executemany receives only records where sector or industry is truthy
        args_list = mock_exec.call_args.args[1]
        assert len(args_list) == 1  # only 005930 passes the filter


# ── get_stock_master ────────────────────────────────────────────────────────


class TestGetStockMaster:
    @pytest.mark.asyncio
    async def test_returns_dict_when_found(self):
        from src.db.marketplace_queries import get_stock_master

        data = {
            "ticker": "005930",
            "name": "삼성전자",
            "market": "KOSPI",
            "sector": "반도체",
            "industry": "메모리",
            "market_cap": 500_000_000_000,
            "listing_date": None,
            "is_etf": False,
            "is_etn": False,
            "is_active": True,
            "tier": "core",
            "updated_at": None,
        }

        with patch("src.db.marketplace_queries.fetchrow", new_callable=AsyncMock, return_value=FakeRecord(data)):
            result = await get_stock_master("005930")

        assert result is not None
        assert result["ticker"] == "005930"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from src.db.marketplace_queries import get_stock_master

        with patch("src.db.marketplace_queries.fetchrow", new_callable=AsyncMock, return_value=None):
            result = await get_stock_master("UNKNOWN")

        assert result is None


# ── list_stock_master ───────────────────────────────────────────────────────


class TestListStockMaster:
    @pytest.mark.asyncio
    async def test_no_filters(self):
        from src.db.marketplace_queries import list_stock_master

        with patch("src.db.marketplace_queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            result = await list_stock_master()

        assert result == []
        sql = mock_f.call_args.args[0]
        assert "is_active = TRUE" in sql

    @pytest.mark.asyncio
    async def test_market_filter(self):
        from src.db.marketplace_queries import list_stock_master

        with patch("src.db.marketplace_queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            await list_stock_master(market="KOSPI")

        sql = mock_f.call_args.args[0]
        assert "market = $" in sql

    @pytest.mark.asyncio
    async def test_search_filter(self):
        from src.db.marketplace_queries import list_stock_master

        with patch("src.db.marketplace_queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            await list_stock_master(search="삼성")

        sql = mock_f.call_args.args[0]
        assert "ILIKE" in sql

    @pytest.mark.asyncio
    async def test_limit_and_offset(self):
        from src.db.marketplace_queries import list_stock_master

        with patch("src.db.marketplace_queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            await list_stock_master(limit=50, offset=10)

        args = mock_f.call_args.args
        # limit and offset are the last two positional args
        assert 50 in args
        assert 10 in args


# ── count_stock_master ──────────────────────────────────────────────────────


class TestCountStockMaster:
    @pytest.mark.asyncio
    async def test_returns_int(self):
        from src.db.marketplace_queries import count_stock_master

        with patch("src.db.marketplace_queries.fetchval", new_callable=AsyncMock, return_value=1500):
            result = await count_stock_master()

        assert result == 1500

    @pytest.mark.asyncio
    async def test_returns_zero_for_none(self):
        from src.db.marketplace_queries import count_stock_master

        with patch("src.db.marketplace_queries.fetchval", new_callable=AsyncMock, return_value=None):
            result = await count_stock_master()

        assert result == 0


# ── get_sectors ─────────────────────────────────────────────────────────────


class TestGetSectors:
    @pytest.mark.asyncio
    async def test_returns_dict_list(self):
        from src.db.marketplace_queries import get_sectors

        data = {"sector": "반도체", "stock_count": 10, "total_market_cap": 1_000_000_000}

        with patch("src.db.marketplace_queries.fetch", new_callable=AsyncMock, return_value=[FakeRecord(data)]):
            result = await get_sectors()

        assert len(result) == 1
        assert result[0]["sector"] == "반도체"


# ── search_stocks ───────────────────────────────────────────────────────────


class TestSearchStocks:
    @pytest.mark.asyncio
    async def test_search_with_default_limit(self):
        from src.db.marketplace_queries import search_stocks

        with patch("src.db.marketplace_queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            result = await search_stocks("삼성")

        assert result == []
        args = mock_f.call_args.args
        assert "%삼성%" in args[1]
        assert args[2] == 20  # default limit


# ── upsert_theme_stocks ────────────────────────────────────────────────────


class TestUpsertThemeStocks:
    @pytest.mark.asyncio
    async def test_upsert_with_leaders(self):
        from src.db.marketplace_queries import upsert_theme_stocks

        with patch("src.db.marketplace_queries.executemany", new_callable=AsyncMock) as mock_exec:
            result = await upsert_theme_stocks(
                theme_slug="ev",
                theme_name="전기차",
                tickers=["005930", "000660"],
                leader_tickers=["005930"],
            )

        assert result == 2
        args_list = mock_exec.call_args.args[1]
        assert len(args_list) == 2
        # 005930 is leader
        assert args_list[0][3] is True
        # 000660 is not leader
        assert args_list[1][3] is False


# ── upsert_macro_indicators ────────────────────────────────────────────────


class TestUpsertMacroIndicators:
    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self):
        from src.db.marketplace_queries import upsert_macro_indicators

        result = await upsert_macro_indicators([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_upsert_calls_executemany(self):
        from src.db.marketplace_queries import upsert_macro_indicators
        from src.db.models import MacroIndicator

        indicators = [
            MacroIndicator(
                category="index",
                symbol="SPX",
                name="S&P 500",
                value=5200.0,
                change_pct=0.5,
                snapshot_date=date(2026, 4, 10),
            ),
        ]

        with patch("src.db.marketplace_queries.executemany", new_callable=AsyncMock) as mock_exec:
            result = await upsert_macro_indicators(indicators)

        assert result == 1
        sql = mock_exec.call_args.args[0]
        assert "macro_indicators" in sql
        assert "ON CONFLICT (symbol, snapshot_date)" in sql


# ── get_macro_indicators ────────────────────────────────────────────────────


class TestGetMacroIndicators:
    @pytest.mark.asyncio
    async def test_no_filters(self):
        from src.db.marketplace_queries import get_macro_indicators

        with patch("src.db.marketplace_queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            result = await get_macro_indicators()

        assert result == []
        sql = mock_f.call_args.args[0]
        assert "DISTINCT ON (symbol)" in sql

    @pytest.mark.asyncio
    async def test_category_filter(self):
        from src.db.marketplace_queries import get_macro_indicators

        with patch("src.db.marketplace_queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            await get_macro_indicators(category="index")

        sql = mock_f.call_args.args[0]
        assert "category = $" in sql


# ── upsert_daily_rankings ──────────────────────────────────────────────────


class TestUpsertDailyRankings:
    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self):
        from src.db.marketplace_queries import upsert_daily_rankings

        result = await upsert_daily_rankings([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_serializes_extra_as_jsonb(self):
        from src.db.marketplace_queries import upsert_daily_rankings
        from src.db.models import DailyRanking

        rankings = [
            DailyRanking(
                ranking_date=date(2026, 4, 10),
                ranking_type="market_cap",
                rank=1,
                ticker="005930",
                name="삼성전자",
                value=500_000_000_000.0,
                extra={"sector": "반도체"},
            ),
        ]

        with patch("src.db.marketplace_queries.executemany", new_callable=AsyncMock) as mock_exec:
            result = await upsert_daily_rankings(rankings)

        assert result == 1
        args_list = mock_exec.call_args.args[1]
        # extra is serialized as JSON string
        import json
        extra_val = args_list[0][-1]
        parsed = json.loads(extra_val)
        assert parsed["sector"] == "반도체"


# ── get_daily_rankings ──────────────────────────────────────────────────────


class TestGetDailyRankings:
    @pytest.mark.asyncio
    async def test_with_date_filter(self):
        from src.db.marketplace_queries import get_daily_rankings

        with patch("src.db.marketplace_queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            await get_daily_rankings("market_cap", ranking_date=date(2026, 4, 10))

        sql = mock_f.call_args.args[0]
        assert "ranking_date = $2" in sql

    @pytest.mark.asyncio
    async def test_without_date_uses_max(self):
        from src.db.marketplace_queries import get_daily_rankings

        with patch("src.db.marketplace_queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            await get_daily_rankings("market_cap")

        sql = mock_f.call_args.args[0]
        assert "MAX(ranking_date)" in sql


# ── watchlist CRUD ──────────────────────────────────────────────────────────


class TestWatchlistCRUD:
    @pytest.mark.asyncio
    async def test_add_watchlist_item(self):
        from src.db.marketplace_queries import add_watchlist_item

        with patch("src.db.marketplace_queries.execute", new_callable=AsyncMock) as mock_exec:
            await add_watchlist_item(
                user_id="550e8400-e29b-41d4-a716-446655440000",
                ticker="005930",
                name="삼성전자",
            )

        mock_exec.assert_awaited_once()
        sql = mock_exec.call_args.args[0]
        assert "watchlist" in sql
        assert "ON CONFLICT" in sql

    @pytest.mark.asyncio
    async def test_remove_watchlist_item_found(self):
        from src.db.marketplace_queries import remove_watchlist_item

        with patch("src.db.marketplace_queries.fetchval", new_callable=AsyncMock, return_value=1):
            result = await remove_watchlist_item(
                user_id="550e8400-e29b-41d4-a716-446655440000",
                ticker="005930",
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_remove_watchlist_item_not_found(self):
        from src.db.marketplace_queries import remove_watchlist_item

        with patch("src.db.marketplace_queries.fetchval", new_callable=AsyncMock, return_value=None):
            result = await remove_watchlist_item(
                user_id="550e8400-e29b-41d4-a716-446655440000",
                ticker="UNKNOWN",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_get_watchlist_with_group(self):
        from src.db.marketplace_queries import get_watchlist

        with patch("src.db.marketplace_queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            result = await get_watchlist(
                user_id="550e8400-e29b-41d4-a716-446655440000",
                group_name="favorites",
            )

        assert result == []
        sql = mock_f.call_args.args[0]
        assert "group_name = $2" in sql

    @pytest.mark.asyncio
    async def test_get_watchlist_all_groups(self):
        from src.db.marketplace_queries import get_watchlist

        with patch("src.db.marketplace_queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            result = await get_watchlist(
                user_id="550e8400-e29b-41d4-a716-446655440000",
            )

        assert result == []
        sql = mock_f.call_args.args[0]
        assert "ORDER BY w.group_name" in sql
