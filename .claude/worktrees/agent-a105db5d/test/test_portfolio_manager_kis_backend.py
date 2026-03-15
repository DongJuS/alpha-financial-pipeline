import types
import unittest
from unittest.mock import AsyncMock, patch

from src.agents.portfolio_manager import PortfolioManagerAgent
from src.db.models import PredictionSignal


class PortfolioManagerKISBackendTest(unittest.IsolatedAsyncioTestCase):
    async def test_process_signal_accepts_pending_paper_execution(self) -> None:
        agent = PortfolioManagerAgent()
        agent.paper_broker = types.SimpleNamespace(
            execute_order=AsyncMock(
                return_value=types.SimpleNamespace(
                    status="PENDING",
                    rejection_reason=None,
                )
            )
        )
        signal = PredictionSignal(
            agent_id="predictor_1",
            llm_model="manual",
            strategy="A",
            ticker="005930",
            signal="BUY",
            confidence=0.8,
            target_price=70000,
            trading_date=__import__("datetime").date.today(),
        )

        with (
            patch.object(agent, "_resolve_name_and_price", new=AsyncMock(return_value=("삼성전자", 70000))),
            patch("src.agents.portfolio_manager.get_position", new=AsyncMock(return_value=None)),
            patch("src.agents.portfolio_manager.get_trading_account", new=AsyncMock(return_value={"seed_capital": 10_000_000})),
            patch("src.agents.portfolio_manager.portfolio_total_value", new=AsyncMock(return_value=0)),
        ):
            result = await agent.process_signal(
                signal,
                risk_config={
                    "enable_paper_trading": True,
                    "enable_real_trading": False,
                    "primary_account_scope": "paper",
                    "max_position_pct": 20,
                    "daily_loss_limit_pct": 3,
                },
            )

        self.assertEqual(
            result,
            {"ticker": "005930", "side": "BUY", "quantity": 1, "price": 70000, "account_scope": "paper"},
        )
        agent.paper_broker.execute_order.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
