"""
test/test_rl_trading_v2.py — V2 RL trainer 단위 테스트

V1 test_rl_trading.py와 동일한 시나리오를 V2 트레이너로 검증합니다.
"""

from __future__ import annotations

import unittest

from src.agents.rl_trading import RLDataset
from src.agents.rl_trading_v2 import TabularQTrainerV2


def _uptrend_closes(length: int = 90) -> list[float]:
    return [100.0 + (idx * 1.7) + ((idx % 5) * 0.15) for idx in range(length)]


def _downtrend_closes(length: int = 90) -> list[float]:
    return [200.0 - (idx * 0.8) + ((idx % 3) * 0.1) for idx in range(length)]


def _flat_closes(length: int = 90) -> list[float]:
    return [100.0 for _ in range(length)]


def _volatile_uptrend_closes(length: int = 200) -> list[float]:
    """변동성 있는 상승 추세 — 실제 시장에 더 가까운 데이터."""
    import random
    rng = random.Random(12345)
    prices = [100.0]
    for _ in range(length - 1):
        # 평균 +0.05% drift + 1.5% noise
        daily_return = 0.0005 + rng.gauss(0, 0.015)
        prices.append(prices[-1] * (1.0 + daily_return))
    return prices


class TestV2TrainerUptrend(unittest.TestCase):
    """V2 트레이너가 명확한 상승 추세에서 거래하고 수익을 내는지 검증."""

    def test_learns_buy_signal_on_uptrend(self) -> None:
        closes = _uptrend_closes()
        dataset = RLDataset(
            ticker="TEST_UP",
            closes=closes,
            timestamps=[f"2026-01-{idx + 1:02d}" for idx in range(len(closes))],
        )
        trainer = TabularQTrainerV2(episodes=200, num_seeds=3)
        artifact = trainer.train(dataset)
        action, confidence, _, _ = trainer.infer_action(artifact, dataset.closes, current_position=0)

        self.assertTrue(artifact.evaluation.approved, f"수익률: {artifact.evaluation.total_return_pct}%")
        self.assertEqual(action, "BUY")
        self.assertGreaterEqual(confidence, 0.5)
        self.assertGreaterEqual(artifact.evaluation.total_return_pct, 5.0)
        self.assertGreater(artifact.evaluation.trades, 0, "거래가 0이면 안 됨")

    def test_makes_trades_not_zero(self) -> None:
        """V1 핵심 버그: 거래 수 0 — V2에서는 반드시 거래가 발생해야 함."""
        closes = _uptrend_closes(120)
        dataset = RLDataset(
            ticker="TEST_TRADES",
            closes=closes,
            timestamps=[f"2026-01-{(idx % 28) + 1:02d}" for idx in range(len(closes))],
        )
        trainer = TabularQTrainerV2(episodes=200, num_seeds=3)
        artifact = trainer.train(dataset)

        self.assertGreater(artifact.evaluation.trades, 0, "V2는 반드시 거래를 해야 함")


class TestV2TrainerFlat(unittest.TestCase):
    """플랫 시장에서 과도한 거래를 하지 않는지 검증."""

    def test_flat_market_not_approved(self) -> None:
        closes = _flat_closes()
        trainer = TabularQTrainerV2(episodes=50, num_seeds=2)
        metrics = trainer.evaluate(
            closes,
            {"p0|s0|l0|m0|v0": {"BUY": 0.0, "SELL": 0.0, "HOLD": 1.0}},
        )
        self.assertEqual(metrics.total_return_pct, 0.0)
        self.assertFalse(metrics.approved)


class TestV2TrainerVolatile(unittest.TestCase):
    """변동성 있는 상승 추세에서 V2가 양의 수익을 내는지 검증."""

    def test_volatile_uptrend_positive_return(self) -> None:
        closes = _volatile_uptrend_closes(200)
        dataset = RLDataset(
            ticker="TEST_VOL",
            closes=closes,
            timestamps=[f"2026-{(idx // 28) + 1:02d}-{(idx % 28) + 1:02d}" for idx in range(len(closes))],
        )
        trainer = TabularQTrainerV2(episodes=300, num_seeds=5)
        artifact = trainer.train(dataset)

        self.assertGreater(artifact.evaluation.trades, 0, "변동성 시장에서도 거래 필요")
        self.assertGreater(artifact.evaluation.total_return_pct, 0, "양의 수익 필요")


class TestV2StateRepresentation(unittest.TestCase):
    """V2 상태 표현이 V1보다 더 세분화되는지 검증."""

    def test_state_key_has_momentum_and_volatility(self) -> None:
        closes = _uptrend_closes(30)
        trainer = TabularQTrainerV2()
        state = trainer._state_key(closes, position=0)
        parts = state.split("|")
        self.assertEqual(len(parts), 5, f"V2 상태는 5개 구성요소: {state}")
        self.assertTrue(parts[0].startswith("p"))
        self.assertTrue(parts[1].startswith("s"))
        self.assertTrue(parts[2].startswith("l"))
        self.assertTrue(parts[3].startswith("m"))
        self.assertTrue(parts[4].startswith("v"))

    def test_v2_state_space_larger_than_v1(self) -> None:
        """V2가 V1보다 더 많은 고유 상태를 생성하는지 확인."""
        closes = _uptrend_closes(200)
        v2_trainer = TabularQTrainerV2()
        v2_states = set()
        for idx in range(v2_trainer.lookback, len(closes)):
            for pos in (0, 1):
                v2_states.add(v2_trainer._state_key(closes[:idx + 1], pos))

        # V2는 최소 6개 이상의 고유 상태를 가져야 함 (V1은 ~4개)
        # 일정한 상승 추세에서는 상태가 적을 수 있으나 실제 변동 데이터에서는 더 많음
        self.assertGreaterEqual(len(v2_states), 6, f"V2 고유 상태: {len(v2_states)}")


class TestV2RewardFunction(unittest.TestCase):
    """V2 리워드 함수가 기회비용을 반영하는지 검증."""

    def test_opportunity_cost_penalizes_missing_uptrend(self) -> None:
        trainer = TabularQTrainerV2()
        # 시장이 1% 올랐는데 보유 안 함 → 패널티
        reward_flat = trainer._reward(100.0, 101.0, position=0, next_position=0)
        # 시장이 1% 올랐고 보유 중 → 수익
        reward_hold = trainer._reward(100.0, 101.0, position=1, next_position=1)

        self.assertLess(reward_flat, 0, "비보유 시 상승장 → 음의 리워드(기회비용)")
        self.assertGreater(reward_hold, 0, "보유 시 상승장 → 양의 리워드")

    def test_avoidance_bonus_rewards_missing_downtrend(self) -> None:
        trainer = TabularQTrainerV2()
        # 시장이 1% 내렸는데 숏 중 → 숏 수익 보상
        reward_short = trainer._reward(100.0, 99.0, position=-1, next_position=-1)
        # 시장이 1% 내렸는데 보유 안 함 → 하락장 회피 보상 (양수)
        reward_flat = trainer._reward(100.0, 99.0, position=0, next_position=0)
        # 시장이 1% 내렸고 롱 보유 중 → 손실
        reward_hold = trainer._reward(100.0, 99.0, position=1, next_position=1)

        self.assertGreater(reward_short, 0, "숏 포지션 시 하락장 → 큰 리워드")
        self.assertGreater(reward_flat, 0, "비보유 시 하락장 → 하락 리스크 회피 보상 (양수)")
        self.assertLess(reward_hold, 0, "롱 보유 시 하락장 → 음의 리워드 (손실)")
        self.assertGreater(reward_short, reward_flat, "강극 하락 시엔 숏 수익이 단순 회피 보상보다 큼")


if __name__ == "__main__":
    unittest.main()
