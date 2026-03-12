import types
import unittest
from unittest.mock import AsyncMock

from src.llm.gpt_client import GPTClient


class GPTClientCircuitBreakerTest(unittest.IsolatedAsyncioTestCase):
    def _build_client(self, side_effect: Exception) -> tuple[GPTClient, AsyncMock]:
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

        with self.assertRaises(RuntimeError):
            await client.ask("hello")
        self.assertFalse(client.is_configured)

        with self.assertRaises(RuntimeError):
            await client.ask("hello again")
        self.assertEqual(create_mock.await_count, 1)

    async def test_non_quota_error_does_not_open_circuit(self) -> None:
        client, create_mock = self._build_client(RuntimeError("network timeout"))

        with self.assertRaises(RuntimeError):
            await client.ask("hello")
        self.assertTrue(client.is_configured)
        self.assertEqual(create_mock.await_count, 1)


if __name__ == "__main__":
    unittest.main()
