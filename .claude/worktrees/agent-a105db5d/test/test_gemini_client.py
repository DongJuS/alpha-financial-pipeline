import types
import unittest
from unittest.mock import patch

from src.llm.gemini_client import GeminiClient, load_gemini_oauth_credentials


class GeminiClientCircuitBreakerTest(unittest.IsolatedAsyncioTestCase):
    def _build_client(self, side_effect: Exception) -> GeminiClient:
        GeminiClient._global_quota_exhausted = False
        client = GeminiClient.__new__(GeminiClient)
        client.model = "gemini-1.5-pro"
        client.api_key = "dummy"
        client._auth_mode = "oauth"
        client._quota_exhausted = False
        client._model = types.SimpleNamespace(
            generate_content=lambda prompt: (_ for _ in ()).throw(side_effect),
        )
        return client

    def tearDown(self) -> None:
        load_gemini_oauth_credentials.cache_clear()
        GeminiClient._global_quota_exhausted = False

    async def test_quota_error_opens_circuit(self) -> None:
        client = self._build_client(RuntimeError("RESOURCE_EXHAUSTED: quota exceeded"))

        with self.assertRaises(RuntimeError):
            await client.ask("hello")
        self.assertFalse(client.is_configured)

        with self.assertRaises(RuntimeError):
            await client.ask("hello again")

    async def test_non_quota_error_keeps_client_available(self) -> None:
        client = self._build_client(RuntimeError("temporary backend error"))

        with self.assertRaises(RuntimeError):
            await client.ask("hello")
        self.assertTrue(client.is_configured)

    def test_prefers_oauth_over_api_key(self) -> None:
        fake_credentials = object()

        class FakeModel:
            def __init__(self, model: str) -> None:
                self.model = model

        with (
            patch("src.llm.gemini_client.get_settings", return_value=types.SimpleNamespace(gemini_api_key="api-key")),
            patch("src.llm.gemini_client.load_gemini_oauth_credentials", return_value=(fake_credentials, "demo-project")),
            patch("google.generativeai.configure") as configure,
            patch("google.generativeai.GenerativeModel", side_effect=FakeModel),
        ):
            client = GeminiClient()

        self.assertTrue(client.is_configured)
        self.assertEqual(client.auth_mode, "oauth")
        configure.assert_called_once_with(credentials=fake_credentials)

    def test_falls_back_to_api_key_when_oauth_is_unavailable(self) -> None:
        class FakeModel:
            def __init__(self, model: str) -> None:
                self.model = model

        with (
            patch("src.llm.gemini_client.get_settings", return_value=types.SimpleNamespace(gemini_api_key="api-key")),
            patch("src.llm.gemini_client.load_gemini_oauth_credentials", return_value=(None, None)),
            patch("google.generativeai.configure") as configure,
            patch("google.generativeai.GenerativeModel", side_effect=FakeModel),
        ):
            client = GeminiClient()

        self.assertTrue(client.is_configured)
        self.assertEqual(client.auth_mode, "api_key")
        configure.assert_called_once_with(api_key="api-key")


if __name__ == "__main__":
    unittest.main()
