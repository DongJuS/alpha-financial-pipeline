import types
import unittest
from unittest.mock import AsyncMock, patch

from src.utils.readiness import evaluate_real_trading_readiness


class RealTradingReadinessTest(unittest.IsolatedAsyncioTestCase):
    async def test_readiness_passes_when_all_checks_are_ok(self) -> None:
        settings = types.SimpleNamespace(
            kis_app_key="real_key_123",
            kis_app_secret="real_secret_123",
            kis_account_number="5012345601",
            jwt_secret="super-secret-value",
            real_trading_confirmation_code="CONFIRM_REAL_TRADING_2026_STRONG",
            telegram_bot_token="123456:ABC_DEF_real",
            telegram_chat_id="-1001234567890",
            anthropic_api_key="ant-real-key",
            openai_api_key="sk-real-key",
            gemini_api_key="gem-real-key",
        )
        redis_client = types.SimpleNamespace(ping=AsyncMock(return_value=True))

        with (
            patch("src.utils.readiness.get_settings", return_value=settings),
            patch("src.utils.readiness.fetchval", new=AsyncMock(return_value=1)),
            patch("src.utils.readiness.get_redis", new=AsyncMock(return_value=redis_client)),
            patch(
                "src.utils.readiness.fetchrow",
                new=AsyncMock(return_value={"max_position_pct": 20, "daily_loss_limit_pct": 3}),
            ),
        ):
            result = await evaluate_real_trading_readiness()

        self.assertTrue(result["ready"])
        self.assertTrue(result["critical_ok"])
        self.assertTrue(result["high_ok"])

    async def test_readiness_fails_with_placeholders_and_risky_limits(self) -> None:
        settings = types.SimpleNamespace(
            kis_app_key="PSXxxxxxxxx",
            kis_app_secret="xxxxxxxx",
            kis_account_number="",
            jwt_secret="change-this-to-a-long-random-secret-in-production",
            real_trading_confirmation_code="CONFIRM_REAL_TRADING_2026",
            telegram_bot_token="",
            telegram_chat_id="",
            anthropic_api_key="",
            openai_api_key="",
            gemini_api_key="",
        )
        redis_client = types.SimpleNamespace(ping=AsyncMock(return_value=True))

        with (
            patch("src.utils.readiness.get_settings", return_value=settings),
            patch("src.utils.readiness.fetchval", new=AsyncMock(return_value=1)),
            patch("src.utils.readiness.get_redis", new=AsyncMock(return_value=redis_client)),
            patch(
                "src.utils.readiness.fetchrow",
                new=AsyncMock(return_value={"max_position_pct": 80, "daily_loss_limit_pct": 20}),
            ),
        ):
            result = await evaluate_real_trading_readiness()

        self.assertFalse(result["ready"])
        self.assertFalse(result["critical_ok"])


if __name__ == "__main__":
    unittest.main()
