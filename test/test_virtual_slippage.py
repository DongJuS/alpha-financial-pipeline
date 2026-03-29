"""
test/test_virtual_slippage.py — VirtualBroker 슬리피지/체결 지연 시뮬레이션 테스트
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.utils.config import get_settings

ENV_PATCH = {
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
    "JWT_SECRET": "test-secret",
    "VIRTUAL_SLIPPAGE_BPS": "10",
    "VIRTUAL_FILL_DELAY_MAX_SEC": "3.0",
    "VIRTUAL_PARTIAL_FILL_ENABLED": "false",
    "VIRTUAL_INITIAL_CAPITAL": "10000000",
}


class TestVirtualBrokerSlippage(unittest.TestCase):
    """VirtualBroker 슬리피지 적용 테스트."""

    def setUp(self):
        get_settings.cache_clear()

    def tearDown(self):
        get_settings.cache_clear()

    @patch.dict("os.environ", ENV_PATCH)
    def test_buy_slippage_increases_price(self):
        """매수 시 슬리피지가 가격을 높이는지 확인합니다."""
        from src.brokers.virtual_broker import VirtualBroker

        broker = VirtualBroker()
        broker.slippage_bps = 10

        prices = set()
        for _ in range(100):
            fill_price = broker._apply_slippage(70000, "BUY")
            prices.add(fill_price)
            self.assertGreaterEqual(fill_price, 70000)

        # 100번 중 적어도 일부는 슬리피지가 적용되어야 함
        self.assertGreater(len(prices), 1)

    @patch.dict("os.environ", ENV_PATCH)
    def test_sell_slippage_decreases_price(self):
        """매도 시 슬리피지가 가격을 낮추는지 확인합니다."""
        from src.brokers.virtual_broker import VirtualBroker

        broker = VirtualBroker()
        broker.slippage_bps = 10

        for _ in range(50):
            fill_price = broker._apply_slippage(70000, "SELL")
            self.assertLessEqual(fill_price, 70000)

    @patch.dict("os.environ", ENV_PATCH)
    def test_zero_slippage(self):
        """슬리피지 0bps면 원래 가격을 반환합니다."""
        from src.brokers.virtual_broker import VirtualBroker

        broker = VirtualBroker()
        broker.slippage_bps = 0

        self.assertEqual(broker._apply_slippage(70000, "BUY"), 70000)
        self.assertEqual(broker._apply_slippage(70000, "SELL"), 70000)


class TestVirtualBrokerPartialFill(unittest.TestCase):
    """VirtualBroker 부분 체결 테스트."""

    def setUp(self):
        get_settings.cache_clear()

    def tearDown(self):
        get_settings.cache_clear()

    @patch.dict("os.environ", ENV_PATCH)
    def test_partial_fill_disabled_returns_full_qty(self):
        """부분 체결 비활성화 시 전량 반환."""
        from src.brokers.virtual_broker import VirtualBroker

        broker = VirtualBroker()
        broker.partial_fill_enabled = False

        self.assertEqual(broker._calc_partial_fill(100), 100)
        self.assertEqual(broker._calc_partial_fill(1), 1)

    @patch.dict("os.environ", ENV_PATCH)
    def test_partial_fill_enabled_small_order(self):
        """소량 주문(10주 이하)은 부분 체결 없이 전량."""
        from src.brokers.virtual_broker import VirtualBroker

        broker = VirtualBroker()
        broker.partial_fill_enabled = True

        self.assertEqual(broker._calc_partial_fill(5), 5)
        self.assertEqual(broker._calc_partial_fill(10), 10)

    @patch.dict("os.environ", ENV_PATCH)
    def test_partial_fill_enabled_large_order(self):
        """대량 주문은 50~100% 범위로 부분 체결."""
        from src.brokers.virtual_broker import VirtualBroker

        broker = VirtualBroker()
        broker.partial_fill_enabled = True

        results = set()
        for _ in range(100):
            qty = broker._calc_partial_fill(100)
            results.add(qty)
            self.assertGreaterEqual(qty, 1)
            self.assertLessEqual(qty, 100)

        # 다양한 체결 수량이 나와야 함
        self.assertGreater(len(results), 1)


class TestVirtualBrokerConfig(unittest.TestCase):
    """VirtualBroker 설정 로딩 테스트."""

    def setUp(self):
        get_settings.cache_clear()

    def tearDown(self):
        get_settings.cache_clear()

    @patch.dict("os.environ", ENV_PATCH)
    def test_default_config(self):
        from src.brokers.virtual_broker import VirtualBroker

        broker = VirtualBroker()
        self.assertEqual(broker.slippage_bps, 10)
        self.assertAlmostEqual(broker.fill_delay_max_sec, 3.0)
        self.assertFalse(broker.partial_fill_enabled)
        self.assertEqual(broker.initial_capital, 10_000_000)

    @patch.dict("os.environ", {**ENV_PATCH, "VIRTUAL_SLIPPAGE_BPS": "25"})
    def test_custom_slippage(self):
        from src.brokers.virtual_broker import VirtualBroker

        broker = VirtualBroker()
        self.assertEqual(broker.slippage_bps, 25)

    @patch.dict("os.environ", ENV_PATCH)
    def test_custom_initial_capital(self):
        from src.brokers.virtual_broker import VirtualBroker

        broker = VirtualBroker(initial_capital=50_000_000)
        self.assertEqual(broker.initial_capital, 50_000_000)

    @patch.dict("os.environ", ENV_PATCH)
    def test_strategy_id_assignment(self):
        from src.brokers.virtual_broker import VirtualBroker

        broker = VirtualBroker(strategy_id="RL")
        self.assertEqual(broker.strategy_id, "RL")


class TestAccountScopeVirtual(unittest.TestCase):
    """account_scope.py virtual 확장 테스트."""

    def test_normalize_virtual(self):
        from src.utils.account_scope import normalize_account_scope
        self.assertEqual(normalize_account_scope("virtual"), "virtual")

    def test_normalize_paper(self):
        from src.utils.account_scope import normalize_account_scope
        self.assertEqual(normalize_account_scope("paper"), "paper")

    def test_normalize_real(self):
        from src.utils.account_scope import normalize_account_scope
        self.assertEqual(normalize_account_scope("real"), "real")

    def test_normalize_none(self):
        from src.utils.account_scope import normalize_account_scope
        self.assertEqual(normalize_account_scope(None), "paper")

    def test_is_virtual_scope(self):
        from src.utils.account_scope import is_virtual_scope
        self.assertTrue(is_virtual_scope("virtual"))
        self.assertFalse(is_virtual_scope("paper"))
        self.assertFalse(is_virtual_scope("real"))
        self.assertFalse(is_virtual_scope(None))


class TestBuildBrokerForScope(unittest.TestCase):
    """build_broker_for_scope virtual 분기 테스트."""

    def setUp(self):
        get_settings.cache_clear()

    def tearDown(self):
        get_settings.cache_clear()

    @patch.dict("os.environ", ENV_PATCH)
    def test_build_virtual_broker(self):
        from src.brokers import build_broker_for_scope
        from src.brokers.virtual_broker import VirtualBroker

        broker = build_broker_for_scope("virtual", strategy_id="A")
        self.assertIsInstance(broker, VirtualBroker)
        self.assertEqual(broker.strategy_id, "A")

    @patch.dict("os.environ", ENV_PATCH)
    def test_build_paper_broker(self):
        from src.brokers import build_broker_for_scope
        from src.brokers.paper import PaperBroker

        broker = build_broker_for_scope("paper")
        self.assertIsInstance(broker, PaperBroker)


if __name__ == "__main__":
    unittest.main()
