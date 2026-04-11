"""
test/test_db_models.py -- src/db/models.py Pydantic 모델 단위 테스트
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

pytestmark = [pytest.mark.unit]


# ── MarketDataPoint ─────────────────────────────────────────────────────────


class TestMarketDataPoint:
    def test_valid_construction(self):
        from src.db.models import MarketDataPoint

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
        )
        assert point.instrument_id == "005930.KS"
        assert point.close == 70500

    def test_ticker_property(self):
        from src.db.models import MarketDataPoint

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
        )
        assert point.ticker == "005930"

    def test_timestamp_kst_property(self):
        from src.db.models import MarketDataPoint

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
        )
        ts = point.timestamp_kst
        assert isinstance(ts, datetime)
        assert ts.year == 2026
        assert ts.month == 4
        assert ts.day == 10

    def test_interval_property(self):
        from src.db.models import MarketDataPoint

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
        )
        assert point.interval == "daily"

    def test_invalid_market_rejected(self):
        from src.db.models import MarketDataPoint

        with pytest.raises(ValidationError):
            MarketDataPoint(
                instrument_id="AAPL.US",
                name="Apple",
                market="NYSE",  # not in Literal["KOSPI", "KOSDAQ"]
                traded_at=date(2026, 4, 10),
                open=150,
                high=155,
                low=148,
                close=152,
                volume=50000,
            )

    def test_negative_volume_rejected(self):
        from src.db.models import MarketDataPoint

        with pytest.raises(ValidationError):
            MarketDataPoint(
                instrument_id="005930.KS",
                name="삼성전자",
                market="KOSPI",
                traded_at=date(2026, 4, 10),
                open=70000,
                high=71000,
                low=69000,
                close=70500,
                volume=-1,
            )

    def test_change_pct_sanitization(self):
        """inf / nan 등의 change_pct 값이 sanitize 처리되는지 확인."""
        from src.db.models import MarketDataPoint

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
            change_pct=float("inf"),
        )
        # sanitize_change_pct should handle inf
        assert point.change_pct is None or point.change_pct != float("inf")


# ── PredictionSignal ────────────────────────────────────────────────────────


class TestPredictionSignal:
    def test_valid_construction(self):
        from src.db.models import PredictionSignal

        signal = PredictionSignal(
            agent_id="test_agent",
            llm_model="claude-3-5-sonnet",
            strategy="A",
            ticker="005930.KS",
            signal="BUY",
            confidence=0.85,
            trading_date=date(2026, 4, 10),
        )
        assert signal.signal == "BUY"
        assert signal.confidence == 0.85

    def test_confidence_bounds(self):
        from src.db.models import PredictionSignal

        with pytest.raises(ValidationError):
            PredictionSignal(
                agent_id="test",
                llm_model="claude",
                ticker="005930",
                signal="BUY",
                confidence=1.5,
                trading_date=date(2026, 4, 10),
            )

    def test_invalid_signal_type(self):
        from src.db.models import PredictionSignal

        with pytest.raises(ValidationError):
            PredictionSignal(
                agent_id="test",
                llm_model="claude",
                ticker="005930",
                signal="STRONG_BUY",  # not in Literal
                trading_date=date(2026, 4, 10),
            )


# ── PaperOrderRequest ──────────────────────────────────────────────────────


class TestPaperOrderRequest:
    def test_valid_order(self):
        from src.db.models import PaperOrderRequest

        order = PaperOrderRequest(
            ticker="005930.KS",
            name="삼성전자",
            signal="BUY",
            quantity=10,
            price=70000,
        )
        assert order.quantity == 10
        assert order.account_scope == "paper"

    def test_minimum_quantity(self):
        from src.db.models import PaperOrderRequest

        with pytest.raises(ValidationError):
            PaperOrderRequest(
                ticker="005930",
                name="삼성전자",
                signal="BUY",
                quantity=0,
                price=70000,
            )


# ── StockMasterRecord ──────────────────────────────────────────────────────


class TestStockMasterRecord:
    def test_valid_record(self):
        from src.db.models import StockMasterRecord

        rec = StockMasterRecord(
            ticker="005930",
            name="삼성전자",
            market="KOSPI",
        )
        assert rec.is_active is True
        assert rec.tier == "universe"
        assert rec.is_etf is False

    def test_tier_values(self):
        from src.db.models import StockMasterRecord

        for tier in ["core", "extended", "universe"]:
            rec = StockMasterRecord(
                ticker="005930",
                name="삼성전자",
                market="KOSPI",
                tier=tier,
            )
            assert rec.tier == tier


# ── MacroIndicator ──────────────────────────────────────────────────────────


class TestMacroIndicator:
    def test_valid_indicator(self):
        from src.db.models import MacroIndicator

        ind = MacroIndicator(
            category="index",
            symbol="SPX",
            name="S&P 500",
            value=5200.0,
            snapshot_date=date(2026, 4, 10),
        )
        assert ind.source == "fdr"

    def test_invalid_category(self):
        from src.db.models import MacroIndicator

        with pytest.raises(ValidationError):
            MacroIndicator(
                category="crypto",
                symbol="BTC",
                name="Bitcoin",
                value=60000.0,
                snapshot_date=date(2026, 4, 10),
            )


# ── DailyRanking ────────────────────────────────────────────────────────────


class TestDailyRanking:
    def test_valid_ranking(self):
        from src.db.models import DailyRanking

        ranking = DailyRanking(
            ranking_date=date(2026, 4, 10),
            ranking_type="market_cap",
            rank=1,
            ticker="005930",
            name="삼성전자",
            value=500_000_000_000.0,
        )
        assert ranking.rank == 1

    def test_rank_must_be_positive(self):
        from src.db.models import DailyRanking

        with pytest.raises(ValidationError):
            DailyRanking(
                ranking_date=date(2026, 4, 10),
                ranking_type="market_cap",
                rank=0,
                ticker="005930",
                name="삼성전자",
            )


# ── AgentHeartbeatRecord ────────────────────────────────────────────────────


class TestAgentHeartbeatRecord:
    def test_defaults(self):
        from src.db.models import AgentHeartbeatRecord

        hb = AgentHeartbeatRecord(agent_id="test_agent")
        assert hb.status == "healthy"
        assert hb.last_action is None

    def test_status_values(self):
        from src.db.models import AgentHeartbeatRecord

        for status in ["healthy", "degraded", "error", "dead"]:
            hb = AgentHeartbeatRecord(agent_id="test", status=status)
            assert hb.status == status
