import unittest
from datetime import date
import types
from unittest.mock import AsyncMock, patch

from src.agents.portfolio_manager import PortfolioManagerAgent
from src.brokers.paper import PaperBrokerExecution
from src.db.models import PredictionSignal


class PortfolioManagerAccountScopeTest(unittest.IsolatedAsyncioTestCase):
    async def test_process_signal_reads_and_writes_real_scope_separately(self) -> None:
        agent = PortfolioManagerAgent()
        agent.real_broker = types.SimpleNamespace(
            execute_order=AsyncMock(
                return_value=PaperBrokerExecution(
                    client_order_id="real-test",
                    account_scope="real",
                    status="PENDING",
                    ticker="005930",
                    side="BUY",
                    quantity=1,
                    price=70_000,
                    cash_balance=0,
                    total_equity=0,
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
            trading_date=date.today(),
        )

        with (
            patch.object(
                agent,
                "_resolve_name_and_price",
                new=AsyncMock(return_value=("삼성전자", 70_000)),
            ),
            patch("src.agents.portfolio_manager.get_position", new=AsyncMock(return_value=None)) as get_position_mock,
            patch("src.agents.portfolio_manager.portfolio_total_value", new=AsyncMock(return_value=1_000_000)) as total_value_mock,
        ):
            result = await agent.process_signal(
                signal,
                risk_config={
                    "enable_paper_trading": False,
                    "enable_real_trading": True,
                    "primary_account_scope": "real",
                    "max_position_pct": 50,
                    "paper_seed_capital": 10_000_000,
                },
            )

        get_position_mock.assert_awaited_once_with("005930", account_scope="real")
        total_value_mock.assert_awaited_once_with(account_scope="real")
        agent.real_broker.execute_order.assert_awaited_once()
        self.assertEqual(agent.real_broker.execute_order.await_args.args[0].account_scope, "real")
        self.assertEqual(result["account_scope"], "real")


if __name__ == "__main__":
    unittest.main()
