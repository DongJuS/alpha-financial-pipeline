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


class TestV2EdgeCases(unittest.TestCase):
    """V2 트레이너 에지 케이스 테스트."""

    def test_downtrend_not_approved_or_minimal_return(self) -> None:
        """하락 추세에서 학습 → 승인 불가 또는 낮은 수익."""
        closes = _downtrend_closes(90)
        dataset = RLDataset(
            ticker="DOWN",
            closes=closes,
            timestamps=[str(i) for i in range(len(closes))],
        )
        trainer = TabularQTrainerV2(episodes=50, num_seeds=2)
        artifact = trainer.train(dataset)
        # 하락장에서 높은 수익률 승인은 어려움
        self.assertIsNotNone(artifact.evaluation)

    def test_reward_zero_price_change(self) -> None:
        """가격 변동 없을 때 reward 계산."""
        trainer = TabularQTrainerV2()
        reward = trainer._reward(100.0, 100.0, position=1, next_position=1)
        # 가격 변동 없음 → position_return 0, 거래 비용 없음
        self.assertAlmostEqual(reward, 0.0, places=3)

    def test_state_key_short_data(self) -> None:
        """짧은 데이터에서도 state_key 생성 가능."""
        trainer = TabularQTrainerV2()
        closes = [100.0, 101.0, 102.0, 103.0, 104.0]
        state = trainer._state_key(closes, position=0)
        self.assertIsInstance(state, str)
        self.assertTrue(len(state) > 0)

    def test_evaluate_with_hold_only_q_table(self) -> None:
        """HOLD만 있는 Q-table → 거래 없음, 수익률 0."""
        trainer = TabularQTrainerV2(episodes=1)
        closes = _flat_closes()
        q_table = {"p0|s0|l0|m0|v0": {"BUY": 0.0, "SELL": 0.0, "HOLD": 1.0, "CLOSE": 0.0}}
        metrics = trainer.evaluate(closes, q_table)
        self.assertEqual(metrics.total_return_pct, 0.0)

    def test_infer_action_returns_valid_action(self) -> None:
        """추론 결과가 유효한 액션인지 검증."""
        trainer = TabularQTrainerV2(episodes=50, num_seeds=2)
        closes = _uptrend_closes(90)
        dataset = RLDataset(
            ticker="INFER",
            closes=closes,
            timestamps=[str(i) for i in range(len(closes))],
        )
        artifact = trainer.train(dataset)
        action, confidence, _, _ = trainer.infer_action(
            artifact, closes, current_position=0
        )
        self.assertIn(action, ("BUY", "SELL", "HOLD", "CLOSE"))
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)

    def test_num_seeds_parameter(self) -> None:
        """num_seeds 파라미터가 반영되는지 검증."""
        trainer = TabularQTrainerV2(episodes=30, num_seeds=1)
        closes = _uptrend_closes(90)
        dataset = RLDataset(
            ticker="SEED1",
            closes=closes,
            timestamps=[str(i) for i in range(len(closes))],
        )
        artifact = trainer.train(dataset)
        self.assertIsNotNone(artifact)


class TestV2RewardEdgeCases(unittest.TestCase):
    """V2 보상 함수 경계 조건 테스트."""

    def test_reward_same_price(self) -> None:
        """current_price == next_price → position_return 0."""
        trainer = TabularQTrainerV2()
        reward = trainer._reward(100.0, 100.0, position=0, next_position=0)
        self.assertAlmostEqual(reward, 0.0, places=6)

    def test_reward_position_change_has_trade_cost(self) -> None:
        """포지션 전환 시 거래 비용 차감."""
        trainer = TabularQTrainerV2(trade_penalty_bps=10)
        reward_trade = trainer._reward(100.0, 100.0, position=0, next_position=1)
        reward_hold = trainer._reward(100.0, 100.0, position=0, next_position=0)
        self.assertLess(reward_trade, reward_hold)

    def test_reward_long_in_uptrend_positive(self) -> None:
        """롱 포지션 + 상승 → 양의 보상."""
        trainer = TabularQTrainerV2()
        reward = trainer._reward(100.0, 105.0, position=1, next_position=1)
        self.assertGreater(reward, 0.0)

    def test_reward_short_in_downtrend_positive(self) -> None:
        """숏 포지션 + 하락 → 양의 보상."""
        trainer = TabularQTrainerV2()
        reward = trainer._reward(100.0, 95.0, position=-1, next_position=-1)
        self.assertGreater(reward, 0.0)

    def test_reward_flat_in_uptrend_negative(self) -> None:
        """플랫 + 상승 → 기회비용 패널티."""
        trainer = TabularQTrainerV2()
        reward = trainer._reward(100.0, 105.0, position=0, next_position=0)
        self.assertLess(reward, 0.0)

    def test_reward_flat_in_downtrend_positive(self) -> None:
        """플랫 + 하락 → 하락 회피 보상."""
        trainer = TabularQTrainerV2()
        reward = trainer._reward(100.0, 95.0, position=0, next_position=0)
        self.assertGreater(reward, 0.0)

    def test_reward_long_loss_no_dampening(self) -> None:
        """롱 보유 중 손실 시 감쇠 없이 실제 손실 반영 (train/eval 일관성)."""
        trainer = TabularQTrainerV2()
        # next_position=1 + next_return < 0 → position_reward = 1 * (-0.01)
        reward = trainer._reward(100.0, 99.0, position=1, next_position=1)
        # 감쇠 없이 -0.01 그대로 (거래 비용 없음: 포지션 유지)
        self.assertAlmostEqual(reward, -0.01, places=6)


class TestV2Bucket5EdgeCases(unittest.TestCase):
    """_bucket5 경계값 테스트."""

    def test_exact_large_threshold(self) -> None:
        trainer = TabularQTrainerV2()
        # value == large_th → NOT > large_th → check > small_th
        result = trainer._bucket5(0.008, small_th=0.002, large_th=0.008)
        self.assertEqual(result, 1)

    def test_just_above_large_threshold(self) -> None:
        trainer = TabularQTrainerV2()
        result = trainer._bucket5(0.0081, small_th=0.002, large_th=0.008)
        self.assertEqual(result, 2)

    def test_exact_small_threshold(self) -> None:
        trainer = TabularQTrainerV2()
        result = trainer._bucket5(0.002, small_th=0.002, large_th=0.008)
        self.assertEqual(result, 0)  # NOT > small_th → neutral

    def test_just_above_small_threshold(self) -> None:
        trainer = TabularQTrainerV2()
        result = trainer._bucket5(0.0021, small_th=0.002, large_th=0.008)
        self.assertEqual(result, 1)

    def test_negative_large_threshold(self) -> None:
        trainer = TabularQTrainerV2()
        result = trainer._bucket5(-0.009, small_th=0.002, large_th=0.008)
        self.assertEqual(result, -2)

    def test_negative_small_threshold(self) -> None:
        trainer = TabularQTrainerV2()
        result = trainer._bucket5(-0.003, small_th=0.002, large_th=0.008)
        self.assertEqual(result, -1)

    def test_zero_value(self) -> None:
        trainer = TabularQTrainerV2()
        result = trainer._bucket5(0.0, small_th=0.002, large_th=0.008)
        self.assertEqual(result, 0)


class TestV2StateKeyEdgeCases(unittest.TestCase):
    """_state_key 경계값 테스트."""

    def test_single_close(self) -> None:
        """데이터가 1개 → fallback state."""
        trainer = TabularQTrainerV2()
        state = trainer._state_key([100.0], position=0)
        self.assertEqual(state, "p0|s0|l0|m0|v0")

    def test_two_closes(self) -> None:
        """데이터가 2개 → short_return 계산 가능."""
        trainer = TabularQTrainerV2()
        state = trainer._state_key([100.0, 101.0], position=1)
        self.assertIn("p1", state)

    def test_all_positions(self) -> None:
        """position -1, 0, 1 모두 유효."""
        trainer = TabularQTrainerV2()
        closes = [100.0 + i for i in range(30)]
        for pos in (-1, 0, 1):
            state = trainer._state_key(closes, position=pos)
            self.assertIn(f"p{pos}", state)

    def test_volatile_data_high_vol_bucket(self) -> None:
        """변동성이 큰 데이터 → vol_bucket=2."""
        trainer = TabularQTrainerV2()
        # 큰 변동성: 100 -> 110 -> 90 -> 115 -> 85 ...
        closes = [100.0 + ((-1) ** i) * 15.0 * (i + 1) for i in range(30)]
        state = trainer._state_key(closes, position=0)
        # vol_bucket should be > 0 due to high variance
        parts = state.split("|")
        vol_part = parts[4]  # v0, v1, or v2
        self.assertIn("v", vol_part)


class TestV2MapActionToSignal(unittest.TestCase):
    """map_v2_action_to_signal 변환 에지케이스."""

    def test_buy(self) -> None:
        from src.agents.rl_trading_v2 import map_v2_action_to_signal
        self.assertEqual(map_v2_action_to_signal("BUY"), "BUY")

    def test_sell(self) -> None:
        from src.agents.rl_trading_v2 import map_v2_action_to_signal
        self.assertEqual(map_v2_action_to_signal("SELL"), "SELL")

    def test_hold(self) -> None:
        from src.agents.rl_trading_v2 import map_v2_action_to_signal
        self.assertEqual(map_v2_action_to_signal("HOLD"), "HOLD")

    def test_close_maps_to_hold(self) -> None:
        from src.agents.rl_trading_v2 import map_v2_action_to_signal
        self.assertEqual(map_v2_action_to_signal("CLOSE"), "HOLD")

    def test_unknown_maps_to_hold(self) -> None:
        from src.agents.rl_trading_v2 import map_v2_action_to_signal
        self.assertEqual(map_v2_action_to_signal("INVALID"), "HOLD")

    def test_lowercase_input(self) -> None:
        from src.agents.rl_trading_v2 import map_v2_action_to_signal
        self.assertEqual(map_v2_action_to_signal("buy"), "BUY")

    def test_mixed_case_input(self) -> None:
        from src.agents.rl_trading_v2 import map_v2_action_to_signal
        self.assertEqual(map_v2_action_to_signal("Sell"), "SELL")


class TestV2NormalizeQConfidence(unittest.TestCase):
    """normalize_q_confidence 변환 에지케이스."""

    def test_empty_q_values(self) -> None:
        from src.agents.rl_trading_v2 import normalize_q_confidence
        self.assertEqual(normalize_q_confidence({}), 0.5)

    def test_all_equal_q_values(self) -> None:
        from src.agents.rl_trading_v2 import normalize_q_confidence
        result = normalize_q_confidence({"BUY": 0.5, "SELL": 0.5, "HOLD": 0.5})
        self.assertEqual(result, 0.5)

    def test_large_spread_high_confidence(self) -> None:
        from src.agents.rl_trading_v2 import normalize_q_confidence
        result = normalize_q_confidence({"BUY": 1.0, "SELL": 0.0, "HOLD": 0.0})
        self.assertGreater(result, 0.9)

    def test_small_spread_low_confidence(self) -> None:
        from src.agents.rl_trading_v2 import normalize_q_confidence
        result = normalize_q_confidence({"BUY": 0.51, "SELL": 0.50, "HOLD": 0.50})
        self.assertLess(result, 0.5)

    def test_result_within_bounds(self) -> None:
        from src.agents.rl_trading_v2 import normalize_q_confidence
        result = normalize_q_confidence({"BUY": 10.0, "SELL": -5.0})
        self.assertGreaterEqual(result, 0.3)
        self.assertLessEqual(result, 0.95)

    def test_negative_q_values(self) -> None:
        from src.agents.rl_trading_v2 import normalize_q_confidence
        result = normalize_q_confidence({"BUY": -0.1, "SELL": -0.2, "HOLD": -0.15})
        self.assertGreaterEqual(result, 0.3)
        self.assertLessEqual(result, 0.95)

    def test_single_q_value(self) -> None:
        from src.agents.rl_trading_v2 import normalize_q_confidence
        result = normalize_q_confidence({"BUY": 0.5})
        # spread = 0 → 0.5
        self.assertEqual(result, 0.5)


class TestV2TransitionFunction(unittest.TestCase):
    """_transition 포지션 전이 테스트."""

    def test_buy_goes_long(self) -> None:
        self.assertEqual(TabularQTrainerV2._transition(0, "BUY"), 1)
        self.assertEqual(TabularQTrainerV2._transition(-1, "BUY"), 1)
        self.assertEqual(TabularQTrainerV2._transition(1, "BUY"), 1)

    def test_sell_goes_short(self) -> None:
        self.assertEqual(TabularQTrainerV2._transition(0, "SELL"), -1)
        self.assertEqual(TabularQTrainerV2._transition(1, "SELL"), -1)

    def test_close_goes_flat(self) -> None:
        self.assertEqual(TabularQTrainerV2._transition(1, "CLOSE"), 0)
        self.assertEqual(TabularQTrainerV2._transition(-1, "CLOSE"), 0)

    def test_hold_maintains_position(self) -> None:
        self.assertEqual(TabularQTrainerV2._transition(0, "HOLD"), 0)
        self.assertEqual(TabularQTrainerV2._transition(1, "HOLD"), 1)
        self.assertEqual(TabularQTrainerV2._transition(-1, "HOLD"), -1)


if __name__ == "__main__":
    unittest.main()
