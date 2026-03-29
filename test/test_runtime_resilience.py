import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from scripts import run_rl_trading
from src.brokers.kis import KISPaperApiClient
from src.llm.gemini_client import GeminiClient, load_gemini_oauth_credentials
from src.services import llm_usage_limiter
from src.utils.config import has_kis_credentials


def _settings(
    *,
    app_key: str = "",
    app_secret: str = "",
    account_number: str = "",
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        kis_app_key=app_key,
        kis_app_secret=app_secret,
        kis_account_number=account_number,
        kis_paper_app_key="",
        kis_paper_app_secret="",
        kis_paper_account_number="",
        kis_real_app_key="",
        kis_real_app_secret="",
        kis_real_account_number="",
    )


class KISCredentialHelperTest(unittest.TestCase):
    def test_has_kis_credentials_rejects_placeholder_values(self) -> None:
        settings = _settings(app_key="YOUR_APP_KEY", app_secret="real-secret")
        self.assertFalse(has_kis_credentials(settings, "paper"))

    def test_has_kis_credentials_can_require_account_number(self) -> None:
        settings = _settings(
            app_key="real-app-key",
            app_secret="real-app-secret",
            account_number="50012345-01",
        )
        self.assertTrue(has_kis_credentials(settings, "paper"))
        self.assertTrue(has_kis_credentials(settings, "paper", require_account_number=True))


class FakeRedisUsageStore:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    async def eval(self, _script: str, _numkeys: int, key: str, limit: int, ttl: int) -> list[int]:
        current = self.counts.get(key, 0)
        if current >= int(limit):
            return [0, current]
        current += 1
        self.counts[key] = current
        self.expiries[key] = int(ttl)
        return [1, current]


class LLMUsageLimiterTest(unittest.IsolatedAsyncioTestCase):
    async def test_reserve_provider_call_enforces_daily_limit(self) -> None:
        fake_redis = FakeRedisUsageStore()
        settings = types.SimpleNamespace(
            llm_daily_provider_limit=2,
            llm_usage_timezone="Asia/Seoul",
        )

        with (
            patch("src.services.llm_usage_limiter.get_settings", return_value=settings),
            patch("src.services.llm_usage_limiter.get_redis", new=AsyncMock(return_value=fake_redis)),
        ):
            first = await llm_usage_limiter.reserve_provider_call("claude")
            second = await llm_usage_limiter.reserve_provider_call("claude")

            self.assertEqual(first, (1, 2))
            self.assertEqual(second, (2, 2))

            with self.assertRaisesRegex(RuntimeError, "일일 사용 한도"):
                await llm_usage_limiter.reserve_provider_call("claude")


class GeminiAuthResilienceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        GeminiClient.reset_global_state()
        load_gemini_oauth_credentials.cache_clear()

    def tearDown(self) -> None:
        GeminiClient.reset_global_state()
        load_gemini_oauth_credentials.cache_clear()

    @staticmethod
    def _build_client(side_effect: Exception) -> GeminiClient:
        client = GeminiClient.__new__(GeminiClient)
        client.model = "gemini-1.5-pro"
        client._auth_mode = "oauth"
        client._quota_exhausted = False
        client._model = types.SimpleNamespace(
            generate_content=Mock(side_effect=side_effect),
        )
        return client

    async def test_auth_error_disables_client_globally(self) -> None:
        client = self._build_client(RuntimeError("403 ACCESS_TOKEN_SCOPE_INSUFFICIENT"))

        with patch("src.llm.gemini_client.reserve_provider_call", new=AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, "비활성화"):
                await client.ask("hello")

        self.assertFalse(client.is_configured)
        self.assertIsNotNone(GeminiClient.disabled_reason())

        second = self._build_client(RuntimeError("should not run"))
        with patch("src.llm.gemini_client.reserve_provider_call", new=AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, "비활성화"):
                await second.ask("hello again")

        second._model.generate_content.assert_not_called()


class RLPrimeKisTicksTest(unittest.IsolatedAsyncioTestCase):
    async def test_prime_kis_ticks_skips_without_kis_credentials(self) -> None:
        fake_collector = types.SimpleNamespace(
            settings=_settings(),
            _account_scope=lambda: "paper",
            collect_realtime_ticks=AsyncMock(),
        )

        with (
            patch("scripts.run_rl_trading.market_session_status", AsyncMock(return_value="open")),
            patch("scripts.run_rl_trading.CollectorAgent", return_value=fake_collector),
        ):
            result = await run_rl_trading._prime_kis_ticks(["005930"], 30)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "missing_kis_credentials")
        fake_collector.collect_realtime_ticks.assert_not_awaited()


class KISTokenResolutionTest(unittest.IsolatedAsyncioTestCase):
    async def test_token_provider_receives_account_scope_keyword(self) -> None:
        token_provider = AsyncMock(return_value="token")
        settings = types.SimpleNamespace(
            kis_app_key="app-key",
            kis_app_secret="app-secret",
            kis_account_number="50012345-01",
            kis_paper_app_key="",
            kis_paper_app_secret="",
            kis_paper_account_number="",
            kis_real_app_key="",
            kis_real_app_secret="",
            kis_real_account_number="",
        )
        client = KISPaperApiClient(settings=settings, token_provider=token_provider)

        token = await client._resolve_token()

        self.assertEqual(token, "token")
        token_provider.assert_awaited_once_with(account_scope="paper")


if __name__ == "__main__":
    unittest.main()
