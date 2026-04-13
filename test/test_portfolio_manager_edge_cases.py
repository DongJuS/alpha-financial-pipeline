"""
test/test_portfolio_manager_edge_cases.py — PortfolioManager 에지케이스 테스트

process_signal의 HOLD/가격없음/매도미보유/비중초과, circuit breaker 등을 검증합니다.
src/ 코드는 수정하지 않으며, mock으로 DB/Redis/broker를 격리합니다.
"""

from __future__ import annotations

from datetime import date
import unittest
from unittest.mock import AsyncMock, patch

from src.agents.portfolio_manager import PortfolioManagerAgent
from src.db.models import PredictionSignal


class TestProcessSignalHoldReturnsNone(unittest.IsolatedAsyncioTestCase):
    """HOLD 시그널 시 process_signal은 즉시 None을 반환해야 한다."""

    async def test_process_signal_hold_returns_none(self) -> None:
        agent = PortfolioManagerAgent()
        signal = PredictionSignal(
            agent_id="predictor_1",
            llm_model="manual",
            strategy="A",
            ticker="005930",
            signal="HOLD",
            confidence=0.9,
            trading_date=date.today(),
        )
        # HOLD이면 _resolve_name_and_price조차 호출하지 않아야 함
        with patch.object(
            agent, "_resolve_name_and_price", new=AsyncMock()
        ) as mock_resolve:
            result = await agent.process_signal(signal, risk_config={})

        self.assertIsNone(result)
        mock_resolve.assert_not_called()


class TestProcessSignalNoPriceReturnsNone(unittest.IsolatedAsyncioTestCase):
    """가격 데이터 없을 때 (price <= 0) process_signal은 None을 반환해야 한다."""

    async def test_process_signal_no_price_returns_none(self) -> None:
        agent = PortfolioManagerAgent()
        signal = PredictionSignal(
            agent_id="predictor_1",
            llm_model="manual",
            strategy="A",
            ticker="999999",
            signal="BUY",
            confidence=0.8,
            trading_date=date.today(),
        )
        with patch.object(
            agent,
            "_resolve_name_and_price",
            new=AsyncMock(return_value=("알수없음", 0)),
        ):
            result = await agent.process_signal(signal, risk_config={})

        self.assertIsNone(result)


class TestCircuitBreakerBlocksOnDailyLossLimit(unittest.IsolatedAsyncioTestCase):
    """일일 손실 한도 초과 시 circuit breaker가 주문을 차단해야 한다."""

    async def test_circuit_breaker_blocks_on_daily_loss_limit(self) -> None:
        agent = PortfolioManagerAgent()
        signal = PredictionSignal(
            agent_id="predictor_1",
            llm_model="manual",
            strategy="A",
            ticker="005930",
            signal="BUY",
            confidence=0.7,
            trading_date=date.today(),
        )

        with (
            patch(
                "src.agents.portfolio_manager.get_portfolio_config",
                new=AsyncMock(
                    return_value={
                        "daily_loss_limit_pct": 3,
                        "max_position_pct": 20,
                        "enable_paper_trading": True,
                        "enable_real_trading": False,
                        "primary_account_scope": "paper",
                    }
                ),
            ),
            patch(
                "src.agents.portfolio_manager.market_session_status",
                new=AsyncMock(return_value="open"),
            ),
            patch(
                "src.agents.portfolio_manager.publish_message",
                new=AsyncMock(),
            ),
            patch(
                "src.agents.portfolio_manager.set_heartbeat",
                new=AsyncMock(),
            ),
            patch(
                "src.agents.portfolio_manager.insert_heartbeat",
                new=AsyncMock(),
            ),
            patch.object(
                agent,
                "_is_daily_loss_blocked",
                new=AsyncMock(return_value=(True, -4.5)),
            ),
            patch.object(
                agent, "process_signal", new=AsyncMock()
            ) as mock_process,
        ):
            orders = await agent.process_predictions([signal])

        self.assertEqual(orders, [])
        mock_process.assert_not_called()


class TestSellNoPositionSkips(unittest.IsolatedAsyncioTestCase):
    """매도 시 포지션 미보유면 None 반환 (스킵)."""

    async def test_sell_no_position_skips(self) -> None:
        agent = PortfolioManagerAgent()
        signal = PredictionSignal(
            agent_id="predictor_1",
            llm_model="manual",
            strategy="A",
            ticker="005930",
            signal="SELL",
            confidence=0.85,
            trading_date=date.today(),
        )
        with (
            patch.object(
                agent,
                "_resolve_name_and_price",
                new=AsyncMock(return_value=("삼성전자", 70_000)),
            ),
            patch(
                "src.agents.portfolio_manager.get_position",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = await agent.process_signal(signal, risk_config={})

        self.assertIsNone(result)


class TestBuyPositionWeightOverflowCheck(unittest.IsolatedAsyncioTestCase):
    """BUY 시 포지션 비중이 max_position_pct를 초과하면 주문이 스킵되어야 한다."""

    async def test_buy_position_weight_overflow_check(self) -> None:
        agent = PortfolioManagerAgent()
        signal = PredictionSignal(
            agent_id="predictor_1",
            llm_model="manual",
            strategy="A",
            ticker="005930",
            signal="BUY",
            confidence=0.8,
            trading_date=date.today(),
        )
        # 이미 9주 보유, 가격 10,000원. total_value=100,000원, seed=100,000원
        # current_value = 9 * 10,000 = 90,000
        # next_value = 90,000 + 1 * 10,000 = 100,000
        # denominator = max(100,000, 100,000, 1) = 100,000
        # next_weight_pct = (100,000 / 100,000) * 100 = 100% > 20%
        with (
            patch.object(
                agent,
                "_resolve_name_and_price",
                new=AsyncMock(return_value=("삼성전자", 10_000)),
            ),
            patch(
                "src.agents.portfolio_manager.get_position",
                new=AsyncMock(
                    return_value={
                        "quantity": 9,
                        "current_price": 10_000,
                        "avg_price": 10_000,
                    }
                ),
            ),
            patch(
                "src.agents.portfolio_manager.portfolio_total_value",
                new=AsyncMock(return_value=100_000),
            ),
            patch.object(
                agent.paper_broker, "execute_order", new=AsyncMock()
            ) as mock_execute,
        ):
            result = await agent.process_signal(
                signal,
                risk_config={
                    "max_position_pct": 20,
                    "enable_paper_trading": True,
                    "enable_real_trading": False,
                    "primary_account_scope": "paper",
                    "paper_seed_capital": 100_000,
                },
            )

        self.assertIsNone(result)
        mock_execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
