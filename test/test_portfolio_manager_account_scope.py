import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from src.agents.portfolio_manager import PortfolioManagerAgent
from src.db.models import PredictionSignal


class PortfolioManagerAccountScopeTest(unittest.IsolatedAsyncioTestCase):
    async def test_process_signal_reads_and_writes_real_scope_separately(self) -> None:
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

        with (
            patch.object(
                agent,
                "_resolve_name_and_price",
                new=AsyncMock(return_value=("삼성전자", 70_000)),
            ),
            patch("src.agents.portfolio_manager.get_position", new=AsyncMock(return_value=None)) as get_position_mock,
            patch("src.agents.portfolio_manager.portfolio_total_value", new=AsyncMock(return_value=1_000_000)) as total_value_mock,
            patch("src.agents.portfolio_manager.save_position", new=AsyncMock()) as save_position_mock,
            patch("src.agents.portfolio_manager.insert_trade", new=AsyncMock()) as insert_trade_mock,
        ):
            await agent.process_signal(
                signal,
                risk_config={
                    "is_paper_trading": False,
                    "max_position_pct": 50,
                    "paper_seed_capital": 10_000_000,
                },
            )

        get_position_mock.assert_awaited_once_with("005930", account_scope="real")
        total_value_mock.assert_awaited_once_with(account_scope="real")
        save_position_mock.assert_awaited_once()
        self.assertEqual(save_position_mock.await_args.kwargs["account_scope"], "real")
        insert_order = insert_trade_mock.await_args.args[0]
        self.assertEqual(insert_order.account_scope, "real")


if __name__ == "__main__":
    unittest.main()
