"""
test/test_ranking_deterministic_order.py — 랭킹 결정적 정렬(tie-handling) 검증

동일 값(tie)이 있을 때 ORDER BY에 secondary sort(ticker ASC / sector ASC)가
포함되어 결정적 정렬이 보장되는지 검증합니다.
SQL 문자열을 캡처하여 secondary sort 키가 존재하는지 확인합니다.
"""
from __future__ import annotations

import pytest
from datetime import date
from unittest.mock import AsyncMock, patch

from src.agents.ranking_calculator import RankingCalculator


# ── Market Cap Tie ──────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestMarketCapTieHandling:
    """시가총액 동점 시 ticker ASC로 결정적 정렬."""

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_market_cap_ranking_tie_uses_ticker_order(self, mock_fetch):
        """동일 market_cap인 두 종목이 ticker 알파벳 순으로 정렬되는지 확인."""
        mock_fetch.return_value = [
            {"ticker": "000010", "name": "종목A", "market_cap": 1_000_000_000, "change_pct": 1.0},
            {"ticker": "000020", "name": "종목B", "market_cap": 1_000_000_000, "change_pct": 2.0},
        ]
        calc = RankingCalculator()
        rankings = await calc.calculate_market_cap_ranking(date(2026, 4, 12))

        # SQL에 secondary sort가 포함되어 있는지 확인
        sql = mock_fetch.call_args[0][0]
        assert "ORDER BY sm.market_cap DESC, i.ticker ASC" in sql

        # 결과 순서 확인 (mock은 DB가 이미 정렬한 것처럼 반환)
        assert rankings[0].ticker == "000010"
        assert rankings[1].ticker == "000020"
        assert rankings[0].rank == 1
        assert rankings[1].rank == 2


# ── Volume Tie ──────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestVolumeTieHandling:
    """거래량 동점 시 ticker ASC로 결정적 정렬."""

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_volume_ranking_tie_uses_ticker_order(self, mock_fetch):
        """동일 거래량인 종목들이 ticker 알파벳 순으로 정렬되는지 확인."""
        mock_fetch.return_value = [
            {"ticker": "000100", "name": "종목A", "total_volume": 5_000_000, "change_pct": 1.0},
            {"ticker": "000200", "name": "종목B", "total_volume": 5_000_000, "change_pct": 2.0},
            {"ticker": "000300", "name": "종목C", "total_volume": 5_000_000, "change_pct": 3.0},
        ]
        calc = RankingCalculator()
        rankings = await calc.calculate_volume_ranking(date(2026, 4, 12))

        sql = mock_fetch.call_args[0][0]
        assert "ORDER BY total_volume DESC, i.ticker ASC" in sql

        assert rankings[0].ticker == "000100"
        assert rankings[1].ticker == "000200"
        assert rankings[2].ticker == "000300"


# ── Turnover Tie ────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestTurnoverTieHandling:
    """거래대금 동점 시 ticker ASC로 결정적 정렬."""

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_turnover_ranking_tie_uses_ticker_order(self, mock_fetch):
        """동일 거래대금 시 ticker 순으로 정렬되는지 SQL 검증."""
        mock_fetch.return_value = [
            {"ticker": "005930", "name": "삼성전자", "total_turnover": 100_000_000, "change_pct": 0.5},
            {"ticker": "035420", "name": "NAVER", "total_turnover": 100_000_000, "change_pct": 0.3},
        ]
        calc = RankingCalculator()
        rankings = await calc.calculate_turnover_ranking(date(2026, 4, 12))

        sql = mock_fetch.call_args[0][0]
        assert "ORDER BY total_turnover DESC, i.ticker ASC" in sql

        assert rankings[0].ticker == "005930"
        assert rankings[1].ticker == "035420"


# ── Gainer Tie ──────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestGainerTieHandling:
    """상승률 동점 시 ticker ASC로 결정적 정렬."""

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_gainer_ranking_tie_uses_ticker_order(self, mock_fetch):
        """동일 상승률 시 ticker 순으로 정렬되는지 확인."""
        mock_fetch.return_value = [
            {"ticker": "000050", "name": "종목A", "change_pct": 10.0},
            {"ticker": "000060", "name": "종목B", "change_pct": 10.0},
        ]
        calc = RankingCalculator()
        rankings = await calc.calculate_gainer_ranking(date(2026, 4, 12))

        sql = mock_fetch.call_args[0][0]
        assert "ORDER BY o.change_pct DESC, i.ticker ASC" in sql

        assert rankings[0].ticker == "000050"
        assert rankings[1].ticker == "000060"
        assert rankings[0].change_pct == rankings[1].change_pct


# ── Loser Tie ───────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestLoserTieHandling:
    """하락률 동점 시 ticker ASC로 결정적 정렬."""

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_loser_ranking_tie_uses_ticker_order(self, mock_fetch):
        """동일 하락률 시 ticker 순으로 정렬되는지 확인."""
        mock_fetch.return_value = [
            {"ticker": "000070", "name": "종목A", "change_pct": -15.0},
            {"ticker": "000080", "name": "종목B", "change_pct": -15.0},
        ]
        calc = RankingCalculator()
        rankings = await calc.calculate_loser_ranking(date(2026, 4, 12))

        sql = mock_fetch.call_args[0][0]
        assert "ORDER BY o.change_pct ASC, i.ticker ASC" in sql

        assert rankings[0].ticker == "000070"
        assert rankings[1].ticker == "000080"
        assert rankings[0].change_pct == rankings[1].change_pct


# ── Sector Heatmap Tie ──────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestSectorHeatmapTieHandling:
    """섹터 히트맵 동일 시가총액 시 sector ASC로 결정적 정렬."""

    @patch("src.agents.ranking_calculator.get_redis", new_callable=AsyncMock)
    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_sector_heatmap_tie_uses_sector_order(self, mock_fetch, mock_redis):
        """동일 total_market_cap 섹터가 sector 알파벳 순으로 정렬되는지 확인."""
        mock_fetch.return_value = [
            {
                "sector": "건설",
                "stock_count": 10,
                "avg_change_pct": 1.0,
                "total_market_cap": 500_000_000_000,
                "total_volume": 10_000_000,
            },
            {
                "sector": "반도체",
                "stock_count": 8,
                "avg_change_pct": 2.0,
                "total_market_cap": 500_000_000_000,
                "total_volume": 20_000_000,
            },
        ]
        mock_redis_instance = AsyncMock()
        mock_redis.return_value = mock_redis_instance

        calc = RankingCalculator()
        result = await calc.calculate_sector_heatmap(date(2026, 4, 12))

        sql = mock_fetch.call_args[0][0]
        assert "ORDER BY total_market_cap DESC, sm.sector ASC" in sql

        assert result["data"][0]["sector"] == "건설"
        assert result["data"][1]["sector"] == "반도체"
