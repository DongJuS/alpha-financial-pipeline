"""
test/test_rl_trading_v2_edge_cases.py — RL Trading V2 에지케이스 테스트

TabularQTrainerV2의 데이터 검증, 멀티시드 학습, approval threshold 등을 검증합니다.
src/ 코드는 수정하지 않으며, DB/Redis 연결 없이 동작합니다.
"""

from __future__ import annotations

import unittest

from src.agents.rl_trading import MIN_APPROVAL_RETURN_PCT, RLDataset
from src.agents.rl_trading_v2 import TabularQTrainerV2


def _make_dataset(length: int, ticker: str = "TEST") -> RLDataset:
    """지정 길이의 상승 추세 데이터셋을 생성합니다."""
    closes = [100.0 + (i * 0.5) for i in range(length)]
    timestamps = [f"2026-01-{(i % 28) + 1:02d}" for i in range(length)]
    return RLDataset(ticker=ticker, closes=closes, timestamps=timestamps)


def _make_strong_uptrend_dataset(length: int = 200, ticker: str = "STRONG_UP") -> RLDataset:
    """강한 상승 추세 데이터셋 (approval 통과용)."""
    closes = [100.0 + (i * 2.0) + ((i % 7) * 0.3) for i in range(length)]
    timestamps = [f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(length)]
    return RLDataset(ticker=ticker, closes=closes, timestamps=timestamps)


class TestTrainTooShortDataRaisesValueError(unittest.TestCase):
    """데이터 길이가 lookback + 10 이하이면 ValueError가 발생해야 한다."""

    def test_train_too_short_data_raises_value_error(self) -> None:
        trainer = TabularQTrainerV2(lookback=20)
        # lookback(20) + 10 = 30, 데이터 길이 30이면 <= 30이므로 ValueError
        dataset = _make_dataset(30)
        with self.assertRaises(ValueError) as ctx:
            trainer.train(dataset)
        self.assertIn("길이가 너무 짧습니다", str(ctx.exception))

    def test_train_exactly_lookback_plus_10_raises(self) -> None:
        """정확히 lookback + 10 길이도 ValueError."""
        trainer = TabularQTrainerV2(lookback=20)
        dataset = _make_dataset(30)  # == 20 + 10
        with self.assertRaises(ValueError):
            trainer.train(dataset)

    def test_train_lookback_plus_11_succeeds(self) -> None:
        """lookback + 11 길이면 통과."""
        trainer = TabularQTrainerV2(lookback=20, episodes=10, num_seeds=1)
        dataset = _make_dataset(31)  # > 20 + 10
        artifact = trainer.train(dataset)
        self.assertIsNotNone(artifact)


class TestTrainInvalidRatioRaisesValueError(unittest.TestCase):
    """train_ratio가 범위 밖이면 ValueError가 발생해야 한다."""

    def test_train_invalid_ratio_below_half(self) -> None:
        trainer = TabularQTrainerV2(episodes=10, num_seeds=1)
        dataset = _make_dataset(100)
        with self.assertRaises(ValueError) as ctx:
            trainer.train(dataset, train_ratio=0.3)
        self.assertIn("train_ratio", str(ctx.exception))

    def test_train_invalid_ratio_at_one(self) -> None:
        trainer = TabularQTrainerV2(episodes=10, num_seeds=1)
        dataset = _make_dataset(100)
        with self.assertRaises(ValueError) as ctx:
            trainer.train(dataset, train_ratio=1.0)
        self.assertIn("train_ratio", str(ctx.exception))

    def test_train_invalid_ratio_above_one(self) -> None:
        trainer = TabularQTrainerV2(episodes=10, num_seeds=1)
        dataset = _make_dataset(100)
        with self.assertRaises(ValueError):
            trainer.train(dataset, train_ratio=1.5)

    def test_train_valid_ratio_half(self) -> None:
        """train_ratio=0.5는 유효 (하한 경계)."""
        trainer = TabularQTrainerV2(episodes=10, num_seeds=1)
        dataset = _make_dataset(100)
        artifact = trainer.train(dataset, train_ratio=0.5)
        self.assertIsNotNone(artifact)


class TestMultiSeedSelectsBestHoldout(unittest.TestCase):
    """멀티시드 학습에서 최고 holdout 성과의 정책이 선택되어야 한다."""

    def test_multi_seed_selects_best_holdout(self) -> None:
        dataset = _make_dataset(120, ticker="MULTI_SEED")

        # num_seeds=1 vs num_seeds=5 결과가 다를 수 있음을 검증
        trainer_single = TabularQTrainerV2(episodes=50, num_seeds=1, random_seed=42)
        artifact_single = trainer_single.train(dataset)

        trainer_multi = TabularQTrainerV2(episodes=50, num_seeds=5, random_seed=42)
        artifact_multi = trainer_multi.train(dataset)

        # 멀티시드는 5개 중 최고를 선택하므로 single보다 같거나 나은 holdout 성과
        self.assertGreaterEqual(
            artifact_multi.evaluation.total_return_pct,
            artifact_single.evaluation.total_return_pct,
            "멀티시드(5)는 단일 시드보다 같거나 나은 holdout 성과를 가져야 함",
        )

    def test_multi_seed_all_produce_valid_artifact(self) -> None:
        """num_seeds 값에 관계없이 유효한 artifact가 반환되어야 한다."""
        dataset = _make_dataset(100, ticker="VALID")
        for num_seeds in (1, 2, 5):
            trainer = TabularQTrainerV2(episodes=30, num_seeds=num_seeds)
            artifact = trainer.train(dataset)
            self.assertIsNotNone(artifact.q_table)
            self.assertIsNotNone(artifact.evaluation)


class TestApprovalThresholdNotMet(unittest.TestCase):
    """holdout_steps < 5, return 부족, drawdown 초과 시 approved=False."""

    def test_approval_threshold_not_met(self) -> None:
        trainer = TabularQTrainerV2()
        # 플랫 시장: 수익률 0% (MIN_APPROVAL_RETURN_PCT=5.0 미만)
        flat_closes = [100.0 for _ in range(90)]
        q_table = {
            "p0|s0|l0|m0|v0": {
                "BUY": 0.0,
                "SELL": 0.0,
                "HOLD": 1.0,
                "CLOSE": 0.0,
            }
        }
        metrics = trainer.evaluate(flat_closes, q_table)
        self.assertFalse(metrics.approved)
        self.assertLess(metrics.total_return_pct, MIN_APPROVAL_RETURN_PCT)

    def test_approval_fails_on_insufficient_holdout_steps(self) -> None:
        """holdout_steps < 5이면 approved=False."""
        trainer = TabularQTrainerV2(lookback=20)
        # 데이터가 lookback + 5 = 25개이면 holdout_steps = 25 - 20 - 1 = 4 (< 5)
        short_closes = [100.0 + i * 2.0 for i in range(25)]
        q_table: dict[str, dict[str, float]] = {}
        metrics = trainer.evaluate(short_closes, q_table)
        self.assertLess(metrics.holdout_steps, 5)
        self.assertFalse(metrics.approved)


class TestApprovalThresholdMet(unittest.TestCase):
    """모든 조건(holdout_steps >= 5, return >= MIN, drawdown >= -50) 충족 시 approved=True."""

    def test_approval_threshold_met(self) -> None:
        dataset = _make_strong_uptrend_dataset(200)
        trainer = TabularQTrainerV2(episodes=200, num_seeds=5)
        artifact = trainer.train(dataset)

        # 강한 상승 추세에서 학습하면 approved=True가 되어야 함
        self.assertTrue(
            artifact.evaluation.approved,
            f"strong uptrend에서 approved=True여야 함. "
            f"return={artifact.evaluation.total_return_pct}%, "
            f"drawdown={artifact.evaluation.max_drawdown_pct}%, "
            f"holdout_steps={artifact.evaluation.holdout_steps}",
        )
        self.assertGreaterEqual(artifact.evaluation.holdout_steps, 5)
        self.assertGreaterEqual(
            artifact.evaluation.total_return_pct, MIN_APPROVAL_RETURN_PCT
        )
        self.assertGreaterEqual(artifact.evaluation.max_drawdown_pct, -50.0)


if __name__ == "__main__":
    unittest.main()
