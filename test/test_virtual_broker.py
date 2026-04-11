"""
test/test_virtual_broker.py -- src/brokers/virtual_broker.py 단위 테스트

실제 DB 없이 mock으로 슬리피지/부분 체결/지연 시뮬레이션을 검증합니다.
"""

from __future__ import annotations

import random
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


def _make_mock_settings(**overrides):
    settings = MagicMock()
    settings.virtual_initial_capital = 10_000_000
    settings.virtual_slippage_bps = 5
    settings.virtual_fill_delay_max_sec = 0.0
    settings.virtual_partial_fill_enabled = False
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


def _make_broker(**settings_overrides):
    """VirtualBroker를 mock된 설정으로 생성합니다."""
    settings = _make_mock_settings(**settings_overrides)
    with patch("src.brokers.virtual_broker.get_settings", return_value=settings):
        from src.brokers.virtual_broker import VirtualBroker
        return VirtualBroker(**{k: v for k, v in settings_overrides.items()
                               if k in ("strategy_id", "initial_capital")})


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


# ── VirtualBrokerExecution 데이터클래스 ─────────────────────────────────────


class TestVirtualBrokerExecution:
    def test_construction(self):
        from src.brokers.virtual_broker import VirtualBrokerExecution

        ex = VirtualBrokerExecution(
            client_order_id="VB-abc123",
            ticker="005930.KS",
            side="BUY",
            requested_quantity=10,
            requested_price=70000,
            filled_quantity=10,
            avg_fill_price=70035,
            status="FILLED",
            slippage_bps=5.0,
        )
        assert ex.status == "FILLED"
        assert ex.slippage_bps == 5.0
        assert ex.rejection_reason is None


# ── _apply_slippage ─────────────────────────────────────────────────────────


class TestApplySlippage:
    def test_buy_slippage_increases_price(self):
        broker = _make_broker(virtual_slippage_bps=10)
        random.seed(42)
        fill_price = broker._apply_slippage(70000, "BUY")
        assert fill_price >= 70000

    def test_sell_slippage_decreases_price(self):
        broker = _make_broker(virtual_slippage_bps=10)
        random.seed(42)
        fill_price = broker._apply_slippage(70000, "SELL")
        assert fill_price <= 70000

    def test_zero_slippage(self):
        broker = _make_broker(virtual_slippage_bps=0)
        fill_price = broker._apply_slippage(70000, "BUY")
        assert fill_price == 70000

    def test_slippage_bounded(self):
        """슬리피지가 설정된 범위 내에 있는지 확인."""
        broker = _make_broker(virtual_slippage_bps=10)
        for _ in range(100):
            fill = broker._apply_slippage(70000, "BUY")
            max_price = int(round(70000 * (1 + 10 / 10_000)))
            assert 70000 <= fill <= max_price


# ── _calc_partial_fill ──────────────────────────────────────────────────────


class TestCalcPartialFill:
    def test_disabled_returns_full_quantity(self):
        broker = _make_broker(virtual_partial_fill_enabled=False)
        assert broker._calc_partial_fill(100) == 100

    def test_small_order_fully_filled(self):
        """10주 이하는 전량 체결."""
        broker = _make_broker(virtual_partial_fill_enabled=True)
        assert broker._calc_partial_fill(10) == 10
        assert broker._calc_partial_fill(5) == 5

    def test_large_order_partial_fill(self):
        """10주 초과 시 50~100% 범위에서 부분 체결."""
        broker = _make_broker(virtual_partial_fill_enabled=True)
        results = set()
        for i in range(200):
            random.seed(i)  # vary the seed each iteration
            filled = broker._calc_partial_fill(100)
            results.add(filled)
            assert 1 <= filled <= 100

        assert len(results) > 1

    def test_minimum_one_share(self):
        """부분 체결 시 최소 1주."""
        broker = _make_broker(virtual_partial_fill_enabled=True)
        for i in range(50):
            random.seed(i)
            filled = broker._calc_partial_fill(11)
            assert filled >= 1


# ── _simulate_delay ─────────────────────────────────────────────────────────


class TestSimulateDelay:
    @pytest.mark.asyncio
    async def test_zero_delay_returns_zero(self):
        broker = _make_broker(virtual_fill_delay_max_sec=0.0)
        delay = await broker._simulate_delay()
        assert delay == 0.0

    @pytest.mark.asyncio
    async def test_positive_delay_bounded(self):
        broker = _make_broker(virtual_fill_delay_max_sec=0.01)
        delay = await broker._simulate_delay()
        assert 0 <= delay <= 0.01


# ── execute_order ───────────────────────────────────────────────────────────


class TestExecuteOrder:
    @pytest.mark.asyncio
    async def test_buy_order_returns_filled(self):
        broker = _make_broker(
            virtual_slippage_bps=0,
            virtual_fill_delay_max_sec=0.0,
            virtual_partial_fill_enabled=False,
        )
        broker.strategy_id = "RL"

        with (
            patch("src.brokers.virtual_broker.execute", new_callable=AsyncMock),
            patch("src.brokers.virtual_broker.fetchrow", new_callable=AsyncMock, return_value=None),
        ):
            result = await broker.execute_order(
                ticker="005930.KS",
                side="BUY",
                quantity=10,
                price=70000,
                name="삼성전자",
            )

        assert result.status == "FILLED"
        assert result.filled_quantity == 10
        assert result.avg_fill_price == 70000
        assert result.strategy_id == "RL"

    @pytest.mark.asyncio
    async def test_sell_order(self):
        broker = _make_broker(
            virtual_slippage_bps=0,
            virtual_fill_delay_max_sec=0.0,
        )

        mock_existing = FakeRecord({"id": 1, "quantity": 20, "avg_price": 70000})

        with (
            patch("src.brokers.virtual_broker.execute", new_callable=AsyncMock),
            patch("src.brokers.virtual_broker.fetchrow", new_callable=AsyncMock, return_value=mock_existing),
        ):
            result = await broker.execute_order(
                ticker="005930.KS",
                side="SELL",
                quantity=10,
                price=71000,
            )

        assert result.status == "FILLED"
        assert result.side == "SELL"

    @pytest.mark.asyncio
    async def test_client_order_id_format(self):
        broker = _make_broker(
            virtual_fill_delay_max_sec=0.0,
            virtual_slippage_bps=0,
        )

        with (
            patch("src.brokers.virtual_broker.execute", new_callable=AsyncMock),
            patch("src.brokers.virtual_broker.fetchrow", new_callable=AsyncMock, return_value=None),
        ):
            result = await broker.execute_order(
                ticker="005930.KS",
                side="BUY",
                quantity=1,
                price=70000,
            )

        assert result.client_order_id.startswith("VB-")


# ── get_positions ───────────────────────────────────────────────────────────


class TestGetPositions:
    @pytest.mark.asyncio
    async def test_returns_dict_list(self):
        broker = _make_broker(strategy_id="RL")

        data = {
            "ticker": "005930.KS",
            "name": "삼성전자",
            "quantity": 10,
            "avg_price": 70000,
            "current_price": 70500,
        }

        with patch("src.brokers.virtual_broker.fetch", new_callable=AsyncMock, return_value=[FakeRecord(data)]):
            positions = await broker.get_positions()

        assert len(positions) == 1
        assert positions[0]["ticker"] == "005930.KS"

    @pytest.mark.asyncio
    async def test_empty_positions(self):
        broker = _make_broker()

        with patch("src.brokers.virtual_broker.fetch", new_callable=AsyncMock, return_value=[]):
            positions = await broker.get_positions()

        assert positions == []


# ── VirtualBroker 초기화 ────────────────────────────────────────────────────


class TestVirtualBrokerInit:
    def test_default_settings(self):
        broker = _make_broker()
        assert broker.initial_capital == 10_000_000
        assert broker.slippage_bps == 5
        assert broker.strategy_id is None

    def test_custom_strategy_id(self):
        settings = _make_mock_settings()
        with patch("src.brokers.virtual_broker.get_settings", return_value=settings):
            from src.brokers.virtual_broker import VirtualBroker
            broker = VirtualBroker(strategy_id="RL")
        assert broker.strategy_id == "RL"

    def test_custom_initial_capital(self):
        settings = _make_mock_settings()
        with patch("src.brokers.virtual_broker.get_settings", return_value=settings):
            from src.brokers.virtual_broker import VirtualBroker
            broker = VirtualBroker(initial_capital=5_000_000)
        assert broker.initial_capital == 5_000_000
