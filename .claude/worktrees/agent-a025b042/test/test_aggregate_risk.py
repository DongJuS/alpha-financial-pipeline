"""
test/test_aggregate_risk.py — 합산 리스크 모니터링 테스트
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ENV_PATCH = {
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
    "JWT_SECRET": "test-secret",
    "MAX_SINGLE_STOCK_EXPOSURE_PCT": "30.0",
    "MAX_STRATEGY_OVERLAP_COUNT": "3",
}


class TestAggregateRiskMonitorConfig(unittest.TestCase):
    """AggregateRiskMonitor 설정 테스트."""

    @patch.dict("os.environ", ENV_PATCH)
    def test_default_limits(self):
        from src.utils.aggregate_risk import AggregateRiskMonitor
        monitor = AggregateRiskMonitor()
        self.assertAlmostEqual(monitor.max_single_stock_pct, 30.0)
        self.assertEqual(monitor.max_overlap_count, 3)

    @patch.dict("os.environ", {**ENV_PATCH, "MAX_SINGLE_STOCK_EXPOSURE_PCT": "50.0"})
    def test_custom_limits(self):
        from src.utils.aggregate_risk import AggregateRiskMonitor
        monitor = AggregateRiskMonitor()
        self.assertAlmostEqual(monitor.max_single_stock_pct, 50.0)


class TestExposureCheck(unittest.TestCase):
    """종목별 노출 조회 테스트."""

    @patch.dict("os.environ", ENV_PATCH)
    @patch("src.utils.aggregate_risk.AggregateRiskMonitor._total_aum", new_callable=AsyncMock, return_value=10_000_000)
    @patch("src.utils.aggregate_risk.fetch")
    def test_check_total_exposure_within_limit(self, mock_fetch, mock_aum):
        """노출 한도 이내인 경우 over_limit=False."""
        import asyncio

        mock_fetch.return_value = [
            {"ticker": "005930", "strategy_id": "A", "account_scope": "virtual",
             "quantity": 10, "current_price": 70000, "market_value": 700000},
            {"ticker": "005930", "strategy_id": "B", "account_scope": "virtual",
             "quantity": 5, "current_price": 70000, "market_value": 350000},
        ]

        from src.utils.aggregate_risk import AggregateRiskMonitor
        monitor = AggregateRiskMonitor()
        result = asyncio.get_event_loop().run_until_complete(
            monitor.check_total_exposure("005930")
        )

        self.assertEqual(result.total_quantity, 15)
        self.assertEqual(result.total_market_value, 1_050_000)
        self.assertAlmostEqual(result.exposure_pct, 10.5)
        self.assertFalse(result.over_limit)

    @patch.dict("os.environ", ENV_PATCH)
    @patch("src.utils.aggregate_risk.AggregateRiskMonitor._total_aum", new_callable=AsyncMock, return_value=1_000_000)
    @patch("src.utils.aggregate_risk.fetch")
    def test_check_total_exposure_over_limit(self, mock_fetch, mock_aum):
        """노출 한도 초과 시 over_limit=True."""
        import asyncio

        mock_fetch.return_value = [
            {"ticker": "005930", "strategy_id": "A", "account_scope": "virtual",
             "quantity": 100, "current_price": 70000, "market_value": 7_000_000},
        ]

        from src.utils.aggregate_risk import AggregateRiskMonitor
        monitor = AggregateRiskMonitor()
        result = asyncio.get_event_loop().run_until_complete(
            monitor.check_total_exposure("005930")
        )

        self.assertTrue(result.over_limit)
        self.assertGreater(result.exposure_pct, 30.0)


class TestStrategyCorrelation(unittest.TestCase):
    """전략 간 종목 중복도 분석 테스트."""

    @patch.dict("os.environ", ENV_PATCH)
    @patch("src.utils.aggregate_risk.fetch")
    def test_no_overlaps(self, mock_fetch):
        """중복 종목이 없을 때 빈 결과를 반환합니다."""
        import asyncio

        mock_fetch.return_value = []

        from src.utils.aggregate_risk import AggregateRiskMonitor
        monitor = AggregateRiskMonitor()
        result = asyncio.get_event_loop().run_until_complete(
            monitor.check_strategy_correlation()
        )

        self.assertEqual(result["overlap_tickers"], 0)
        self.assertEqual(len(result["details"]), 0)

    @patch.dict("os.environ", ENV_PATCH)
    @patch("src.utils.aggregate_risk.fetch")
    def test_with_overlaps(self, mock_fetch):
        """중복 종목이 있을 때 정확한 결과를 반환합니다."""
        import asyncio

        mock_fetch.return_value = [
            {"ticker": "005930", "strategy_count": 3, "strategies": ["A", "B", "RL"]},
            {"ticker": "035420", "strategy_count": 2, "strategies": ["A", "B"]},
        ]

        from src.utils.aggregate_risk import AggregateRiskMonitor
        monitor = AggregateRiskMonitor()
        result = asyncio.get_event_loop().run_until_complete(
            monitor.check_strategy_correlation()
        )

        self.assertEqual(result["overlap_tickers"], 2)
        self.assertEqual(result["max_overlap"]["ticker"], "005930")


if __name__ == "__main__":
    unittest.main()
