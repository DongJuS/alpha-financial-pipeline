"""
test/test_strategy_promotion.py — 전략 승격 파이프라인 테스트
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.utils.config import get_settings

ENV_PATCH = {
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
    "JWT_SECRET": "test-secret",
    "PROMOTION_CRITERIA_OVERRIDE": "{}",
    "STRATEGY_MODES": '{"A": ["virtual"], "B": ["paper", "virtual"]}',
}


class TestPromotionCriteria(unittest.TestCase):
    """승격 기준 로딩 테스트."""

    def setUp(self):
        get_settings.cache_clear()

    def tearDown(self):
        get_settings.cache_clear()

    @patch.dict("os.environ", ENV_PATCH)
    def test_default_criteria_virtual_to_paper(self):
        from src.utils.strategy_promotion import StrategyPromoter
        promoter = StrategyPromoter()
        criteria = promoter.get_promotion_criteria("virtual", "paper")
        self.assertEqual(criteria["min_days"], 30)
        self.assertEqual(criteria["min_trades"], 20)
        self.assertAlmostEqual(criteria["min_sharpe"], 0.5)

    @patch.dict("os.environ", ENV_PATCH)
    def test_default_criteria_paper_to_real(self):
        from src.utils.strategy_promotion import StrategyPromoter
        promoter = StrategyPromoter()
        criteria = promoter.get_promotion_criteria("paper", "real")
        self.assertEqual(criteria["min_days"], 60)
        self.assertEqual(criteria["min_trades"], 50)

    @patch.dict("os.environ", {**ENV_PATCH, "PROMOTION_CRITERIA_OVERRIDE": '{"virtual_to_paper": {"min_days": 10}}'})
    def test_criteria_override(self):
        """환경변수 오버라이드가 적용되는지 확인합니다."""
        from src.utils.strategy_promotion import StrategyPromoter
        promoter = StrategyPromoter()
        criteria = promoter.get_promotion_criteria("virtual", "paper")
        self.assertEqual(criteria["min_days"], 10)
        # 나머지 기본값은 유지
        self.assertEqual(criteria["min_trades"], 20)

    @patch.dict("os.environ", ENV_PATCH)
    def test_invalid_promotion_path(self):
        from src.utils.strategy_promotion import StrategyPromoter
        promoter = StrategyPromoter()
        criteria = promoter.get_promotion_criteria("real", "virtual")
        self.assertEqual(criteria, {})


class TestPromotionReadiness(unittest.TestCase):
    """승격 준비 상태 평가 테스트."""

    def setUp(self):
        get_settings.cache_clear()

    def tearDown(self):
        get_settings.cache_clear()

    @patch.dict("os.environ", ENV_PATCH)
    @patch("src.utils.strategy_promotion.StrategyPromoter._count_trading_days", new_callable=AsyncMock, return_value=45)
    @patch("src.utils.strategy_promotion.StrategyPromoter._fetch_strategy_trades", new_callable=AsyncMock)
    def test_promotion_ready(self, mock_trades, mock_days):
        """모든 기준 충족 시 ready=True를 반환하는지 확인합니다."""
        import asyncio
        from src.utils.strategy_promotion import StrategyPromoter

        mock_trades.return_value = self._build_good_trades()

        promoter = StrategyPromoter()
        result = asyncio.run(
            promoter.evaluate_promotion_readiness("A", "virtual", "paper")
        )
        self.assertTrue(result.ready)
        self.assertEqual(len(result.failures), 0)

    @patch.dict("os.environ", ENV_PATCH)
    @patch("src.utils.strategy_promotion.StrategyPromoter._count_trading_days", new_callable=AsyncMock, return_value=5)
    @patch("src.utils.strategy_promotion.StrategyPromoter._fetch_strategy_trades", new_callable=AsyncMock, return_value=[])
    def test_promotion_not_ready_insufficient_days(self, mock_trades, mock_days):
        """운용 일수 미달 시 ready=False를 반환하는지 확인합니다."""
        import asyncio
        from src.utils.strategy_promotion import StrategyPromoter

        promoter = StrategyPromoter()
        result = asyncio.run(
            promoter.evaluate_promotion_readiness("A", "virtual", "paper")
        )
        self.assertFalse(result.ready)
        self.assertTrue(any("운용 일수" in f for f in result.failures))

    @patch.dict("os.environ", ENV_PATCH)
    def test_invalid_promotion_path_returns_not_ready(self):
        """유효하지 않은 승격 경로는 ready=False를 반환합니다."""
        import asyncio
        from src.utils.strategy_promotion import StrategyPromoter

        promoter = StrategyPromoter()
        result = asyncio.run(
            promoter.evaluate_promotion_readiness("A", "real", "virtual")
        )
        self.assertFalse(result.ready)
        self.assertIn("유효하지 않은", result.message)

    @staticmethod
    def _build_good_trades() -> list[dict]:
        """좋은 성과의 거래 이력을 생성합니다."""
        from datetime import datetime, timedelta
        trades = []
        base = datetime(2024, 1, 1)
        for i in range(25):
            trades.append({
                "ticker": "005930",
                "side": "BUY",
                "price": 70000,
                "quantity": 10,
                "amount": 700000,
                "executed_at": base + timedelta(days=i * 2),
            })
            trades.append({
                "ticker": "005930",
                "side": "SELL",
                "price": 72000,
                "quantity": 10,
                "amount": 720000,
                "executed_at": base + timedelta(days=i * 2 + 1),
            })
        return trades


class TestPromoteStrategy(unittest.TestCase):
    """전략 승격 실행 테스트."""

    def setUp(self):
        get_settings.cache_clear()

    def tearDown(self):
        get_settings.cache_clear()

    @patch.dict("os.environ", ENV_PATCH)
    @patch("src.utils.strategy_promotion.StrategyPromoter._record_promotion", new_callable=AsyncMock)
    @patch("src.utils.strategy_promotion.StrategyPromoter._count_trading_days", new_callable=AsyncMock, return_value=5)
    @patch("src.utils.strategy_promotion.StrategyPromoter._fetch_strategy_trades", new_callable=AsyncMock, return_value=[])
    def test_promote_fails_without_force(self, mock_trades, mock_days, mock_record):
        """기준 미충족 + force=False면 승격 실패."""
        import asyncio
        from src.utils.strategy_promotion import StrategyPromoter

        promoter = StrategyPromoter()
        result = asyncio.run(
            promoter.promote_strategy("A", "virtual", "paper", force=False)
        )
        self.assertFalse(result.success)
        mock_record.assert_not_called()

    @patch.dict("os.environ", ENV_PATCH)
    @patch("src.utils.strategy_promotion.StrategyPromoter._record_promotion", new_callable=AsyncMock)
    @patch("src.utils.strategy_promotion.StrategyPromoter._count_trading_days", new_callable=AsyncMock, return_value=5)
    @patch("src.utils.strategy_promotion.StrategyPromoter._fetch_strategy_trades", new_callable=AsyncMock, return_value=[])
    def test_promote_succeeds_with_force(self, mock_trades, mock_days, mock_record):
        """기준 미충족이라도 force=True면 승격 성공."""
        import asyncio
        from src.utils.strategy_promotion import StrategyPromoter

        promoter = StrategyPromoter()
        result = asyncio.run(
            promoter.promote_strategy("A", "virtual", "paper", force=True)
        )
        self.assertTrue(result.success)
        mock_record.assert_called_once()


if __name__ == "__main__":
    unittest.main()
