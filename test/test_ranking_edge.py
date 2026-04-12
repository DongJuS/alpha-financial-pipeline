"""
test/test_ranking_edge.py — RankingCalculator tie-handling edge-case tests.

동일 값(tie) 이 있을 때 순위가 결정적(deterministic)으로 부여되는지,
빈 데이터에 대한 방어 처리가 올바른지 검증한다.
"""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from src.agents.ranking_calculator import RankingCalculator


class TestRankingEdgeCases(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.calculator = RankingCalculator(agent_id="test_ranking")
        self.ranking_date = date(2026, 4, 12)

    # ── 1. 시가총액 동일 값 tie-handling ────────────────────────────────

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_market_cap_ranking_deterministic_order(
        self, mock_fetch: AsyncMock
    ) -> None:
        """동일 market_cap 2종목에 대해 rank 1, 2가 결정적으로 부여되는지 검증."""
        mock_fetch.return_value = [
            {
                "ticker": "005930",
                "name": "삼성전자",
                "market_cap": 500_000_000_000_000,
                "change_pct": 1.0,
            },
            {
                "ticker": "000660",
                "name": "SK하이닉스",
                "market_cap": 500_000_000_000_000,
                "change_pct": 0.5,
            },
        ]

        results = await self.calculator.calculate_market_cap_ranking(
            ranking_date=self.ranking_date
        )
        assert len(results) == 2
        assert results[0].rank == 1
        assert results[1].rank == 2

        # 두 번 실행해도 같은 순서여야 한다 (deterministic)
        results2 = await self.calculator.calculate_market_cap_ranking(
            ranking_date=self.ranking_date
        )
        assert results[0].ticker == results2[0].ticker
        assert results[1].ticker == results2[1].ticker

    # ── 2. 거래량 동일 값 tie-handling ──────────────────────────────────

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_volume_ranking_deterministic_order(
        self, mock_fetch: AsyncMock
    ) -> None:
        """동일 total_volume 2종목에 대해 rank가 결정적으로 부여되는지 검증."""
        mock_fetch.return_value = [
            {
                "ticker": "005930",
                "name": "삼성전자",
                "total_volume": 10_000_000,
                "change_pct": 2.0,
            },
            {
                "ticker": "000660",
                "name": "SK하이닉스",
                "total_volume": 10_000_000,
                "change_pct": -1.0,
            },
        ]

        results = await self.calculator.calculate_volume_ranking(
            ranking_date=self.ranking_date
        )
        assert len(results) == 2
        assert results[0].rank == 1
        assert results[1].rank == 2

        # 두 번 실행해도 같은 순서여야 한다 (deterministic)
        results2 = await self.calculator.calculate_volume_ranking(
            ranking_date=self.ranking_date
        )
        assert results[0].ticker == results2[0].ticker
        assert results[1].ticker == results2[1].ticker

    # ── 3. rank 순서가 연속적인지 검증 ──────────────────────────────────

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_ranking_rank_is_sequential(self, mock_fetch: AsyncMock) -> None:
        """5개 종목(서로 다른 market_cap)의 rank가 [1,2,3,4,5]인지 검증."""
        mock_fetch.return_value = [
            {"ticker": "005930", "name": "삼성전자", "market_cap": 500_000, "change_pct": 1.0},
            {"ticker": "000660", "name": "SK하이닉스", "market_cap": 400_000, "change_pct": 0.5},
            {"ticker": "035420", "name": "NAVER", "market_cap": 300_000, "change_pct": -0.2},
            {"ticker": "035720", "name": "카카오", "market_cap": 200_000, "change_pct": 0.3},
            {"ticker": "051910", "name": "LG화학", "market_cap": 100_000, "change_pct": -1.0},
        ]

        results = await self.calculator.calculate_market_cap_ranking(
            ranking_date=self.ranking_date
        )
        assert len(results) == 5
        expected_ranks = [1, 2, 3, 4, 5]
        actual_ranks = [r.rank for r in results]
        assert actual_ranks == expected_ranks

    # ── 4. 섹터 히트맵 중복 섹터 없음 검증 ─────────────────────────────

    @patch("src.agents.ranking_calculator.get_redis", new_callable=AsyncMock)
    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_sector_heatmap_no_duplicate_sectors(
        self, mock_fetch: AsyncMock, mock_get_redis: AsyncMock
    ) -> None:
        """3개 섹터 데이터에 대해 반환된 리스트에 중복 섹터가 없는지 검증."""
        mock_fetch.return_value = [
            {
                "sector": "반도체",
                "stock_count": 15,
                "avg_change_pct": 1.5,
                "total_market_cap": 800_000_000_000_000,
                "total_volume": 50_000_000,
            },
            {
                "sector": "자동차",
                "stock_count": 10,
                "avg_change_pct": -0.3,
                "total_market_cap": 300_000_000_000_000,
                "total_volume": 30_000_000,
            },
            {
                "sector": "바이오",
                "stock_count": 20,
                "avg_change_pct": 2.1,
                "total_market_cap": 200_000_000_000_000,
                "total_volume": 40_000_000,
            },
        ]

        # get_redis 가 반환하는 redis mock 에 set 메서드 준비
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        result = await self.calculator.calculate_sector_heatmap(
            ranking_date=self.ranking_date
        )
        heatmap = result["data"]
        assert len(heatmap) == 3

        sectors = [item["sector"] for item in heatmap]
        assert len(sectors) == len(set(sectors)), "중복 섹터가 존재합니다"

    # ── 5. 빈 데이터 → 빈 리스트 반환 ──────────────────────────────────

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_ranking_empty_data_returns_empty(
        self, mock_fetch: AsyncMock
    ) -> None:
        """fetch가 빈 리스트를 반환하면 빈 리스트를 반환해야 한다."""
        mock_fetch.return_value = []

        market_cap_results = await self.calculator.calculate_market_cap_ranking(
            ranking_date=self.ranking_date
        )
        assert market_cap_results == []

        volume_results = await self.calculator.calculate_volume_ranking(
            ranking_date=self.ranking_date
        )
        assert volume_results == []


if __name__ == "__main__":
    unittest.main()
