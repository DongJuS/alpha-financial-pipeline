"""
test/test_db_queries.py -- src/db/queries.py 주요 함수 단위 테스트

DB 없이 실행 가능하도록 src.utils.db_client의 함수를 mock합니다.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


# ── 공통 mock 헬퍼 ──────────────────────────────────────────────────────────


class FakeRecord:
    """asyncpg.Record를 흉내 내어 dict(rec)이 동작하는 가짜 레코드."""

    def __init__(self, d: dict):
        self._d = d

    def __iter__(self):
        return iter(self._d.items())

    def keys(self):
        return self._d.keys()

    def values(self):
        return self._d.values()

    def items(self):
        return self._d.items()

    def __getitem__(self, k):
        return self._d[k]

    def get(self, k, default=None):
        return self._d.get(k, default)

    def __contains__(self, k):
        return k in self._d


# ── upsert_market_data ──────────────────────────────────────────────────────


class TestUpsertMarketData:
    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self):
        from src.db.queries import upsert_market_data

        result = await upsert_market_data([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_upsert_calls_executemany(self):
        from src.db.models import MarketDataPoint
        from src.db.queries import upsert_market_data

        points = [
            MarketDataPoint(
                instrument_id="005930.KS",
                name="삼성전자",
                market="KOSPI",
                traded_at=date(2026, 4, 10),
                open=70000,
                high=71000,
                low=69000,
                close=70500,
                volume=100000,
            )
        ]

        with patch("src.db.queries.executemany", new_callable=AsyncMock) as mock_exec:
            result = await upsert_market_data(points)

        assert result == 1
        mock_exec.assert_awaited_once()
        sql = mock_exec.call_args.args[0]
        assert "ON CONFLICT" in sql
        assert "instrument_id" in sql


# ── insert_tick_batch ───────────────────────────────────────────────────────


class TestInsertTickBatch:
    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self):
        from src.db.queries import insert_tick_batch

        result = await insert_tick_batch([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_insert_calls_executemany(self):
        from src.db.queries import insert_tick_batch

        tick = MagicMock()
        tick.instrument_id = "005930.KS"
        tick.timestamp_kst = datetime(2026, 4, 10, 10, 30)
        tick.price = 70500
        tick.volume = 100
        tick.change_pct = 0.5
        tick.source = "ws"

        with patch("src.db.queries.executemany", new_callable=AsyncMock) as mock_exec:
            result = await insert_tick_batch([tick])

        assert result == 1
        mock_exec.assert_awaited_once()
        sql = mock_exec.call_args.args[0]
        assert "tick_data" in sql
        assert "DO NOTHING" in sql


# ── get_ohlcv_bars ──────────────────────────────────────────────────────────


class TestGetOhlcvBars:
    @pytest.mark.asyncio
    async def test_invalid_interval_raises(self):
        from src.db.queries import get_ohlcv_bars

        with pytest.raises(ValueError, match="지원하지 않는 interval"):
            await get_ohlcv_bars(
                "005930.KS",
                "2min",
                datetime(2026, 4, 10, 9, 0),
                datetime(2026, 4, 10, 15, 30),
            )

    @pytest.mark.asyncio
    async def test_valid_intervals_accepted(self):
        from src.db.queries import get_ohlcv_bars

        for interval in ["1min", "5min", "15min", "1hour"]:
            with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
                result = await get_ohlcv_bars(
                    "005930.KS",
                    interval,
                    datetime(2026, 4, 10, 9, 0),
                    datetime(2026, 4, 10, 15, 30),
                )
                assert result == []
                mock_f.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_formatted_rows(self):
        from src.db.queries import get_ohlcv_bars

        mock_row = FakeRecord({
            "bucket": datetime(2026, 4, 10, 10, 0),
            "open": 70000,
            "high": 71000,
            "low": 69000,
            "close": 70500,
            "volume": 50000,
        })

        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[mock_row]):
            result = await get_ohlcv_bars(
                "005930.KS",
                "1min",
                datetime(2026, 4, 10, 9, 0),
                datetime(2026, 4, 10, 15, 30),
            )

        assert len(result) == 1
        assert result[0]["timestamp_kst"] == datetime(2026, 4, 10, 10, 0)
        assert result[0]["open"] == 70000
        assert result[0]["close"] == 70500


# ── list_tickers ────────────────────────────────────────────────────────────


class TestListTickers:
    @pytest.mark.asyncio
    async def test_returns_dict_list(self):
        from src.db.queries import list_tickers

        data = {"instrument_id": "005930.KS", "ticker": "005930", "name": "삼성전자", "market": "KOSPI",
                "priority": 10, "max_weight_pct": None}

        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[FakeRecord(data)]):
            result = await list_tickers(mode="paper", limit=10)

        assert len(result) == 1
        assert result[0]["instrument_id"] == "005930.KS"

    @pytest.mark.asyncio
    async def test_default_limit(self):
        from src.db.queries import list_tickers

        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            await list_tickers()

        sql = mock_f.call_args.args[0]
        assert "LIMIT" in sql
        # args[1] = mode ("paper"), args[2] = limit (30)
        assert mock_f.call_args.args[1] == "paper"
        assert mock_f.call_args.args[2] == 30


# ── latest_close_price ──────────────────────────────────────────────────────


class TestLatestClosePrice:
    @pytest.mark.asyncio
    async def test_returns_float(self):
        from src.db.queries import latest_close_price

        with patch("src.db.queries.fetchval", new_callable=AsyncMock, return_value=70500.0):
            result = await latest_close_price("005930.KS")

        assert result == 70500.0

    @pytest.mark.asyncio
    async def test_returns_none_when_no_data(self):
        from src.db.queries import latest_close_price

        with patch("src.db.queries.fetchval", new_callable=AsyncMock, return_value=None):
            result = await latest_close_price("UNKNOWN")

        assert result is None


# ── insert_prediction ───────────────────────────────────────────────────────


class TestInsertPrediction:
    @pytest.mark.asyncio
    async def test_returns_prediction_id(self):
        from src.db.models import PredictionSignal
        from src.db.queries import insert_prediction

        signal = PredictionSignal(
            agent_id="test_agent",
            llm_model="claude-3-5-sonnet-latest",
            strategy="A",
            ticker="005930.KS",
            signal="BUY",
            confidence=0.85,
            target_price=75000,
            stop_loss=68000,
            reasoning_summary="테스트",
            trading_date=date(2026, 4, 10),
        )

        with patch("src.db.queries.fetchval", new_callable=AsyncMock, return_value=42):
            result = await insert_prediction(signal)

        assert result == 42


# ── get_position / save_position ────────────────────────────────────────────


class TestPositionCRUD:
    @pytest.mark.asyncio
    async def test_get_position_returns_dict(self):
        from src.db.queries import get_position

        data = {
            "ticker": "005930.KS",
            "name": "삼성전자",
            "quantity": 10,
            "avg_price": 70000,
            "current_price": 70500,
            "is_paper": True,
            "account_scope": "paper",
        }

        with patch("src.db.queries.fetchrow", new_callable=AsyncMock, return_value=FakeRecord(data)):
            result = await get_position("005930.KS", "paper")

        assert result is not None
        assert result["ticker"] == "005930.KS"
        assert result["quantity"] == 10

    @pytest.mark.asyncio
    async def test_get_position_returns_none(self):
        from src.db.queries import get_position

        with patch("src.db.queries.fetchrow", new_callable=AsyncMock, return_value=None):
            result = await get_position("UNKNOWN", "paper")

        assert result is None

    @pytest.mark.asyncio
    async def test_save_position_zero_quantity_deletes(self):
        from src.db.queries import save_position

        with patch("src.db.queries.execute", new_callable=AsyncMock) as mock_exec:
            await save_position(
                ticker="005930.KS",
                name="삼성전자",
                quantity=0,
                avg_price=70000,
                current_price=70500,
                is_paper=True,
            )

        mock_exec.assert_awaited_once()
        sql = mock_exec.call_args.args[0]
        assert "DELETE" in sql

    @pytest.mark.asyncio
    async def test_save_position_positive_quantity_upserts(self):
        from src.db.queries import save_position

        with patch("src.db.queries.execute", new_callable=AsyncMock) as mock_exec:
            await save_position(
                ticker="005930.KS",
                name="삼성전자",
                quantity=10,
                avg_price=70000,
                current_price=70500,
                is_paper=True,
            )

        mock_exec.assert_awaited_once()
        sql = mock_exec.call_args.args[0]
        assert "INSERT" in sql
        assert "ON CONFLICT" in sql


# ── portfolio_total_value ───────────────────────────────────────────────────


class TestPortfolioTotalValue:
    @pytest.mark.asyncio
    async def test_returns_int(self):
        from src.db.queries import portfolio_total_value

        with patch("src.db.queries.fetchval", new_callable=AsyncMock, return_value=7050000):
            result = await portfolio_total_value("paper")

        assert result == 7050000

    @pytest.mark.asyncio
    async def test_returns_zero_for_none(self):
        from src.db.queries import portfolio_total_value

        with patch("src.db.queries.fetchval", new_callable=AsyncMock, return_value=None):
            result = await portfolio_total_value("paper")

        assert result == 0


# ── portfolio_position_stats ────────────────────────────────────────────────


class TestPortfolioPositionStats:
    @pytest.mark.asyncio
    async def test_returns_stats_dict(self):
        from src.db.queries import portfolio_position_stats

        data = {
            "market_value": 7050000,
            "unrealized_pnl": 50000,
            "position_count": 2,
        }

        with patch("src.db.queries.fetchrow", new_callable=AsyncMock, return_value=FakeRecord(data)):
            result = await portfolio_position_stats("paper")

        assert result["market_value"] == 7050000
        assert result["unrealized_pnl"] == 50000
        assert result["position_count"] == 2

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_positions(self):
        from src.db.queries import portfolio_position_stats

        with patch("src.db.queries.fetchrow", new_callable=AsyncMock, return_value=None):
            result = await portfolio_position_stats("paper")

        assert result["market_value"] == 0
        assert result["unrealized_pnl"] == 0
        assert result["position_count"] == 0


# ── get_portfolio_config ────────────────────────────────────────────────────


class TestGetPortfolioConfig:
    @pytest.mark.asyncio
    async def test_returns_defaults_when_no_row(self):
        from src.db.queries import get_portfolio_config

        with patch("src.db.queries.fetchrow", new_callable=AsyncMock, return_value=None):
            result = await get_portfolio_config()

        assert result["strategy_blend_ratio"] == 0.5
        assert result["is_paper_trading"] is True
        assert result["primary_account_scope"] == "paper"

    @pytest.mark.asyncio
    async def test_returns_config_from_db(self):
        from src.db.queries import get_portfolio_config

        data = {
            "strategy_blend_ratio": 0.6,
            "max_position_pct": 25,
            "daily_loss_limit_pct": 5,
            "is_paper_trading": False,
            "enable_paper_trading": True,
            "enable_real_trading": True,
            "primary_account_scope": "real",
        }

        with patch("src.db.queries.fetchrow", new_callable=AsyncMock, return_value=FakeRecord(data)):
            result = await get_portfolio_config()

        assert result["strategy_blend_ratio"] == 0.6
        assert result["primary_account_scope"] == "real"


# ── insert_trade ────────────────────────────────────────────────────────────


class TestInsertTrade:
    @pytest.mark.asyncio
    async def test_insert_trade_calls_execute(self):
        from src.db.models import PaperOrderRequest
        from src.db.queries import insert_trade

        order = PaperOrderRequest(
            ticker="005930.KS",
            name="삼성전자",
            signal="BUY",
            quantity=10,
            price=70000,
            signal_source="A",
            account_scope="paper",
        )

        with patch("src.db.queries.execute", new_callable=AsyncMock) as mock_exec:
            await insert_trade(order)

        mock_exec.assert_awaited_once()
        sql = mock_exec.call_args.args[0]
        assert "trade_history" in sql


# ── fetch_trade_rows ────────────────────────────────────────────────────────


class TestFetchTradeRows:
    @pytest.mark.asyncio
    async def test_returns_dict_list(self):
        from src.db.queries import fetch_trade_rows

        data = {
            "ticker": "005930.KS",
            "side": "BUY",
            "price": 70000,
            "quantity": 10,
            "amount": 700000,
            "executed_at": datetime(2026, 4, 10, 10, 30),
        }

        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[FakeRecord(data)]):
            result = await fetch_trade_rows(days=30)

        assert len(result) == 1
        assert result[0]["ticker"] == "005930.KS"

    @pytest.mark.asyncio
    async def test_account_scope_normalized(self):
        from src.db.queries import fetch_trade_rows

        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            await fetch_trade_rows(days=30, account_scope="paper")

        args = mock_f.call_args.args
        assert args[1] == "paper"


# ── DB 쿼리 에지케이스 (Agent 4 QA Round 2) ──────────────────────────────────


class TestUpsertMarketDataEdgeCases:
    """upsert_market_data 에지케이스: 빈 결과, 대량 데이터 등."""

    @pytest.mark.asyncio
    async def test_single_point_tuple_contains_all_fields(self):
        """executemany에 전달되는 튜플이 9개 필드를 갖는지 확인."""
        from src.db.models import MarketDataPoint
        from src.db.queries import upsert_market_data

        point = MarketDataPoint(
            instrument_id="005930.KS",
            name="삼성전자",
            market="KOSPI",
            traded_at=date(2026, 4, 10),
            open=70000,
            high=71000,
            low=69000,
            close=70500,
            volume=100000,
            change_pct=1.5,
            adj_close=70500,
        )

        with patch("src.db.queries.executemany", new_callable=AsyncMock) as mock_exec:
            await upsert_market_data([point])

        args_list = mock_exec.call_args.args[1]
        row = args_list[0]
        assert len(row) == 9  # instrument_id, traded_at, open, high, low, close, volume, change_pct, adj_close
        assert row[0] == "005930.KS"
        assert row[1] == date(2026, 4, 10)
        assert row[6] == 100000  # volume

    @pytest.mark.asyncio
    async def test_large_batch_returns_correct_count(self):
        """대량 데이터 배치에서도 정확한 건수 반환."""
        from src.db.models import MarketDataPoint
        from src.db.queries import upsert_market_data

        points = [
            MarketDataPoint(
                instrument_id=f"{i:06d}.KS",
                name=f"종목{i}",
                market="KOSPI",
                traded_at=date(2026, 4, 10),
                open=10000,
                high=11000,
                low=9000,
                close=10500,
                volume=1000,
            )
            for i in range(100)
        ]

        with patch("src.db.queries.executemany", new_callable=AsyncMock):
            result = await upsert_market_data(points)

        assert result == 100


class TestGetOhlcvBarsEdgeCases:
    """get_ohlcv_bars 에지케이스: 유효/무효 interval, 결과 매핑."""

    @pytest.mark.asyncio
    async def test_unsupported_intervals(self):
        """지원하지 않는 다양한 interval 문자열이 모두 ValueError를 발생."""
        from src.db.queries import get_ohlcv_bars

        for bad_interval in ["2min", "30min", "daily", "1sec", ""]:
            with pytest.raises(ValueError, match="지원하지 않는 interval"):
                await get_ohlcv_bars(
                    "005930.KS", bad_interval,
                    datetime(2026, 4, 10, 9, 0), datetime(2026, 4, 10, 15, 0),
                )

    @pytest.mark.asyncio
    async def test_multiple_rows_returned_in_order(self):
        """여러 행이 올바른 순서로 매핑되는지 확인."""
        from src.db.queries import get_ohlcv_bars

        rows = [
            FakeRecord({"bucket": datetime(2026, 4, 10, 10, i), "open": 100+i, "high": 110, "low": 90, "close": 105, "volume": 500})
            for i in range(3)
        ]

        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=rows):
            result = await get_ohlcv_bars("005930.KS", "1min", datetime(2026, 4, 10, 9, 0), datetime(2026, 4, 10, 15, 0))

        assert len(result) == 3
        assert result[0]["open"] == 100
        assert result[2]["open"] == 102
        assert all("timestamp_kst" in r and "volume" in r for r in result)


class TestFetchRecentMarketDataEdgeCases:
    """fetch_recent_market_data 에지케이스: 빈 결과, 기본 days."""

    @pytest.mark.asyncio
    async def test_default_days_is_30(self):
        """days=None일 때 기본값 30일이 적용."""
        from src.db.queries import fetch_recent_market_data

        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            await fetch_recent_market_data("005930.KS")

        args = mock_f.call_args.args
        assert args[2] == 30  # days 파라미터

    @pytest.mark.asyncio
    async def test_with_limit_parameter(self):
        """limit 파라미터가 SQL에 반영되는지 확인."""
        from src.db.queries import fetch_recent_market_data

        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_f:
            await fetch_recent_market_data("005930.KS", days=7, limit=5)

        sql = mock_f.call_args.args[0]
        assert "LIMIT" in sql
        args = mock_f.call_args.args
        assert 5 in args  # limit value in params

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self):
        """DB에 데이터가 없을 때 빈 리스트 반환."""
        from src.db.queries import fetch_recent_market_data

        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]):
            result = await fetch_recent_market_data("NONEXISTENT")

        assert result == []


class TestSavePositionEdgeCases:
    """save_position 에지케이스: quantity 경계, scope 정규화."""

    @pytest.mark.asyncio
    async def test_negative_quantity_deletes(self):
        """음수 quantity도 삭제 동작을 트리거."""
        from src.db.queries import save_position

        with patch("src.db.queries.execute", new_callable=AsyncMock) as mock_exec:
            await save_position(
                ticker="005930.KS", name="삼성전자",
                quantity=-1, avg_price=70000, current_price=70500,
                is_paper=True,
            )

        sql = mock_exec.call_args.args[0]
        assert "DELETE" in sql

    @pytest.mark.asyncio
    async def test_strategy_id_passed_to_upsert(self):
        """strategy_id가 있을 때 INSERT 파라미터에 포함."""
        from src.db.queries import save_position

        with patch("src.db.queries.execute", new_callable=AsyncMock) as mock_exec:
            await save_position(
                ticker="005930.KS", name="삼성전자",
                quantity=10, avg_price=70000, current_price=70500,
                is_paper=True, strategy_id="A",
            )

        args = mock_exec.call_args.args
        assert "A" in args  # strategy_id가 파라미터에 포함


class TestPortfolioConfigEdgeCases:
    """get_portfolio_config 에지케이스: NULL 필드 기본값 처리."""

    @pytest.mark.asyncio
    async def test_missing_enable_fields_inferred(self):
        """enable_paper_trading/enable_real_trading이 None이면 is_paper_trading에서 유추."""
        from src.db.queries import get_portfolio_config

        data = {
            "strategy_blend_ratio": 0.5,
            "max_position_pct": 20,
            "daily_loss_limit_pct": 3,
            "is_paper_trading": True,
            "enable_paper_trading": None,
            "enable_real_trading": None,
            "primary_account_scope": "",
        }

        with patch("src.db.queries.fetchrow", new_callable=AsyncMock, return_value=FakeRecord(data)):
            result = await get_portfolio_config()

        assert result["enable_paper_trading"] is True
        assert result["enable_real_trading"] is False
        assert result["primary_account_scope"] == "paper"

    @pytest.mark.asyncio
    async def test_real_mode_config(self):
        """primary_account_scope=real 설정 확인."""
        from src.db.queries import get_portfolio_config

        data = {
            "strategy_blend_ratio": 0.6,
            "max_position_pct": 25,
            "daily_loss_limit_pct": 5,
            "is_paper_trading": False,
            "enable_paper_trading": True,
            "enable_real_trading": True,
            "primary_account_scope": "real",
        }

        with patch("src.db.queries.fetchrow", new_callable=AsyncMock, return_value=FakeRecord(data)):
            result = await get_portfolio_config()

        assert result["primary_account_scope"] == "real"
        assert result["is_paper_trading"] is False
