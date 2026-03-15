import unittest
from unittest.mock import AsyncMock, patch

from src.api.routers.portfolio import get_config


class PortfolioConfigApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_config_includes_market_hours_policy_defaults(self) -> None:
        with (
            patch("src.api.routers.portfolio.fetchrow", new=AsyncMock(return_value=None)),
            patch("src.api.routers.portfolio.market_session_status", new=AsyncMock(return_value="after_hours")),
        ):
            response = await get_config({"sub": "admin", "is_admin": True})

        self.assertTrue(response["market_hours_enforced"])
        self.assertEqual(response["market_status"], "after_hours")
        self.assertTrue(response["enable_paper_trading"])
        self.assertEqual(response["primary_account_scope"], "paper")

    async def test_get_config_merges_market_status_with_database_row(self) -> None:
        with (
            patch(
                "src.api.routers.portfolio.fetchrow",
                new=AsyncMock(
                    return_value={
                        "strategy_blend_ratio": 0.7,
                        "max_position_pct": 15,
                        "daily_loss_limit_pct": 2,
                        "is_paper_trading": False,
                        "enable_paper_trading": True,
                        "enable_real_trading": True,
                        "primary_account_scope": "real",
                    }
                ),
            ),
            patch("src.api.routers.portfolio.market_session_status", new=AsyncMock(return_value="open")),
        ):
            response = await get_config({"sub": "admin", "is_admin": True})

        self.assertTrue(response["market_hours_enforced"])
        self.assertEqual(response["market_status"], "open")
        self.assertFalse(response["is_paper_trading"])
        self.assertEqual(response["primary_account_scope"], "real")


if __name__ == "__main__":
    unittest.main()
