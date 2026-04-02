import types
import unittest
from unittest.mock import AsyncMock, patch

from src.llm.gpt_client import GPTClient


class GPTClientCircuitBreakerTest(unittest.IsolatedAsyncioTestCase):
    def _build_client(self, side_effect: Exception) -> tuple[GPTClient, AsyncMock]:
        GPTClient._global_quota_exhausted = False
        create_mock = AsyncMock(side_effect=side_effect)
        client = GPTClient.__new__(GPTClient)
        client.model = "gpt-4o-mini"
        client.api_key = "dummy"
        client._quota_exhausted = False
        client._client = types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=create_mock),
            )
        )
        return client, create_mock

    async def test_quota_error_opens_circuit(self) -> None:
        client, create_mock = self._build_client(RuntimeError("insufficient_quota"))

        with patch("src.llm.gpt_client.reserve_provider_call", new=AsyncMock()):
            with self.assertRaises(RuntimeError):
                await client.ask("hello")
            self.assertFalse(client.is_configured)

        with patch("src.llm.gpt_client.reserve_provider_call", new=AsyncMock()):
            with self.assertRaises(RuntimeError):
                await client.ask("hello again")
        self.assertEqual(create_mock.await_count, 1)

    async def test_non_quota_error_does_not_open_circuit(self) -> None:
        client, create_mock = self._build_client(RuntimeError("network timeout"))

        with patch("src.llm.gpt_client.reserve_provider_call", new=AsyncMock()):
            with self.assertRaises(RuntimeError):
                await client.ask("hello")
            self.assertTrue(client.is_configured)
        self.assertEqual(create_mock.await_count, 1)

    async def test_codex_cli_fallback_uses_mapped_model(self) -> None:
        GPTClient._global_quota_exhausted = False
        client = GPTClient.__new__(GPTClient)
        client.model = "gpt-4o-mini"
        client.api_key = ""
        client._client = None
        client._quota_exhausted = False
        client._cli_command = ["codex", "exec", "-m", "gpt-5.4-mini"]
        client._auth_mode = "codex_cli"
        client._effective_model = "gpt-5.4-mini"
        client.cli_timeout_seconds = 90

        with patch(
            "src.llm.gpt_client.run_cli_prompt_with_output_file",
            new=AsyncMock(return_value="OK"),
        ) as run_mock, patch("src.llm.gpt_client.reserve_provider_call", new=AsyncMock()) as reserve_mock:
            self.assertTrue(client.is_configured)
            self.assertEqual(client.auth_mode, "codex_cli")
            self.assertEqual(client.effective_model, "gpt-5.4-mini")

            result = await client.ask("hello")

            self.assertEqual(result, "OK")
            run_mock.assert_awaited_once()
            reserve_mock.assert_awaited_once_with("codex")


if __name__ == "__main__":
    unittest.main()
