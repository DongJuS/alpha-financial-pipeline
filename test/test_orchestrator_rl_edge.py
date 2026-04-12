"""
test/test_orchestrator_rl_edge.py — Orchestrator / RL 에지케이스 테스트

QA Round 2: 가중치 정규화, 독립 포트폴리오 플래그, RL 환경 경계 조건,
Q-value tie-breaking, 정책 모드 ticker 격리를 검증한다.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.agents.orchestrator import OrchestratorAgent
from src.agents.rl_environment import TradingEnv, TradingEnvConfig, ACTION_BUY
from src.agents.rl_trading_v2 import TabularQTrainerV2
from src.agents.rl_shadow_inference import ShadowInferenceEngine


# ── Orchestrator: 가중치 정규화 ─────────────────────────────────────────────


class TestOrchestratorWeights(unittest.TestCase):
    """_normalize_active_weights 메서드의 경계 조건 검증."""

    def test_normalize_active_weights_all_zero(self):
        """모든 전략 가중치가 0이면 균등 분배 (1/N)."""
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.0, "B": 0.0, "RL": 0.0},
        )
        result = orch._normalize_active_weights({"A", "B", "RL"})

        self.assertEqual(len(result), 3)
        for strategy, weight in result.items():
            self.assertAlmostEqual(weight, 1.0 / 3.0, places=10)
        self.assertAlmostEqual(sum(result.values()), 1.0)

    def test_normalize_active_weights_preserves_ratio(self):
        """비활성 전략 제외 후 활성 전략 간 비율이 보존된다.

        A=0.6, B=0.2 → active={A,B} → A=0.75, B=0.25 (3:1 비율, 합=1.0)
        """
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.6, "B": 0.2, "RL": 0.0},
        )
        result = orch._normalize_active_weights({"A", "B"})

        self.assertAlmostEqual(result["A"], 0.75, places=10)
        self.assertAlmostEqual(result["B"], 0.25, places=10)
        self.assertAlmostEqual(sum(result.values()), 1.0)
        self.assertNotIn("RL", result)

    def test_independent_portfolio_flag_creates_per_strategy_dicts(self):
        """independent_portfolio=True로 생성 시 per-strategy 딕셔너리가 존재한다."""
        orch = OrchestratorAgent(independent_portfolio=True)

        self.assertTrue(orch.independent_portfolio)
        self.assertIsInstance(orch._strategy_portfolios, dict)
        self.assertIsInstance(orch._strategy_virtual_brokers, dict)
        # 초기에는 비어 있어야 한다 (등록 전)
        self.assertEqual(len(orch._strategy_portfolios), 0)
        self.assertEqual(len(orch._strategy_virtual_brokers), 0)


# ── RL Environment 에지케이스 ────────────────────────────────────────────────


class TestTradingEnvEdge(unittest.TestCase):
    """TradingEnv의 경계 조건 검증."""

    def test_trading_env_action_out_of_bounds(self):
        """유효하지 않은 action(99)은 HOLD로 처리된다.

        _apply_action의 else 분기: 알 수 없는 action → current_pos 유지 (HOLD 동작).
        """
        closes = [100.0 + i * 0.1 for i in range(30)]
        config = TradingEnvConfig(closes=closes, lookback=20)
        env = TradingEnv(config=config)
        env.reset()

        # action=99는 유효 범위(0-3) 밖이지만, HOLD로 처리된다
        obs, reward, terminated, truncated, info = env.step(99)

        # 예외 없이 정상 반환되어야 한다
        self.assertFalse(truncated)
        # HOLD 동작이므로 포지션 변화 없음 (초기 position=0 유지)
        self.assertEqual(info["position"], 0)

    def test_trading_env_minimal_data(self):
        """lookback=20일 때 최소 데이터(22개)로 에피소드가 정상 종료된다."""
        # lookback + 2 = 22가 최소
        closes = [100.0] * 22
        config = TradingEnvConfig(closes=closes, lookback=20)
        env = TradingEnv(config=config)
        obs, info = env.reset()

        # reset 후 step_idx = lookback(20), 데이터 길이=22 → 1스텝만 가능
        obs, reward, terminated, truncated, info = env.step(ACTION_BUY)

        # step_idx가 마지막(21)에 도달했으므로 terminated
        self.assertTrue(terminated)
        self.assertFalse(truncated)


# ── RL V2 Q-value tie-breaking ───────────────────────────────────────────────


class TestRLV2Edge(unittest.TestCase):
    """TabularQTrainerV2의 tie-breaking 검증."""

    def test_rl_v2_q_value_tie_breaking(self):
        """동일 Q-value일 때 알파벳순 첫 번째 action(BUY)이 선택된다.

        sorted(items, key=lambda item: (-item[1], item[0]))에서
        Q-value가 같으면 item[0](action 이름)의 오름차순 → BUY가 첫 번째.
        """
        trainer = TabularQTrainerV2()
        q_table = {
            "s0": {"BUY": 1.0, "SELL": 1.0, "HOLD": 1.0, "CLOSE": 1.0},
        }

        result = trainer.best_action(q_table, "s0")
        self.assertEqual(result, "BUY")

        # 결정적(deterministic) 결과 검증: 여러 번 호출해도 동일
        for _ in range(10):
            self.assertEqual(trainer.best_action(q_table, "s0"), "BUY")


# ── Shadow Inference: 정책 모드 ticker 격리 ──────────────────────────────────


class TestPolicyModeEdge(unittest.IsolatedAsyncioTestCase):
    """get_policy_mode의 ticker별 격리 검증."""

    async def test_policy_mode_different_ticker(self):
        """policy_v1이 005930에 학습되었을 때, 000660으로 조회하면 inactive.

        해당 ticker에 대한 DB entry도 shadow_records도 없으므로 "inactive".
        """
        from unittest.mock import AsyncMock
        mock_store = MagicMock()
        mock_store.list_policies = AsyncMock(return_value=[])

        engine = ShadowInferenceEngine(policy_store=mock_store)

        from src.agents.rl_shadow_inference import ShadowRecord
        from datetime import date

        engine._shadow_records["policy_v1"] = [
            ShadowRecord(
                policy_id="policy_v1",
                ticker="005930",
                signal="BUY",
                confidence=0.8,
                close_price=70000.0,
                trading_date=date(2026, 4, 12),
            )
        ]

        # 000660으로 조회 → shadow_records에 000660 record 없음 → inactive
        mode = await engine.get_policy_mode("policy_v1", "000660")
        self.assertEqual(mode, "inactive")

        # 반면 005930은 shadow record가 있으므로 "shadow"
        mode_005930 = await engine.get_policy_mode("policy_v1", "005930")
        self.assertEqual(mode_005930, "shadow")


if __name__ == "__main__":
    unittest.main()
