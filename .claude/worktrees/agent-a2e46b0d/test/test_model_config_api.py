import unittest
from unittest.mock import AsyncMock, patch

from src.api.routers.models import get_model_config, update_model_config, ModelConfigUpdateRequest


class ModelConfigApiTest(unittest.IsolatedAsyncioTestCase):
    def _rows(self) -> list[dict]:
        return [
            {
                "config_key": "strategy_a_predictor_1",
                "strategy_code": "A",
                "role": "predictor",
                "role_label": "Predictor 1",
                "agent_id": "predictor_1",
                "llm_model": "claude-3-5-sonnet-latest",
                "persona": "가치 투자형",
                "execution_order": 1,
                "updated_at": "2026-03-13T13:00:00Z",
            },
            {
                "config_key": "strategy_b_synthesizer",
                "strategy_code": "B",
                "role": "synthesizer",
                "role_label": "Synthesizer",
                "agent_id": "consensus_synthesizer",
                "llm_model": "claude-3-5-sonnet-latest",
                "persona": "조정자",
                "execution_order": 4,
                "updated_at": "2026-03-13T13:00:00Z",
            },
        ]

    async def test_get_model_config_groups_strategy_rows(self) -> None:
        with (
            patch("src.api.routers.models.ensure_model_role_configs", new=AsyncMock(return_value=self._rows())),
            patch(
                "src.api.routers.models.provider_status",
                return_value=[
                    {"provider": "claude", "default_model": "claude-3-5-sonnet-latest", "configured": True},
                    {"provider": "gpt", "default_model": "gpt-4o-mini", "configured": False},
                ],
            ),
        ):
            response = await get_model_config({"sub": "admin", "is_admin": True})

        self.assertFalse(response.rule_based_fallback_allowed)
        self.assertEqual(len(response.strategy_a), 1)
        self.assertEqual(len(response.strategy_b), 1)
        self.assertEqual(response.strategy_b[0].agent_id, "consensus_synthesizer")

    async def test_update_model_config_returns_updated_rows(self) -> None:
        payload = ModelConfigUpdateRequest(
            items=[
                {
                    "config_key": "strategy_a_predictor_1",
                    "llm_model": "gpt-4o-mini",
                    "persona": "새 페르소나",
                }
            ]
        )
        with (
            patch("src.api.routers.models.update_model_role_configs", new=AsyncMock(return_value=self._rows())) as update_mock,
            patch("src.api.routers.models.ensure_model_role_configs", new=AsyncMock(return_value=self._rows())),
            patch(
                "src.api.routers.models.provider_status",
                return_value=[{"provider": "claude", "default_model": "claude-3-5-sonnet-latest", "configured": True}],
            ),
        ):
            response = await update_model_config(payload, {"sub": "admin", "is_admin": True})

        update_mock.assert_awaited_once()
        self.assertEqual(response.strategy_a[0].config_key, "strategy_a_predictor_1")


if __name__ == "__main__":
    unittest.main()
