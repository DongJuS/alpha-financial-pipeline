"""ε-greedy split bandit 단위 테스트.

cold-start, greedy 선택, ε 탐색, 영속화, atomic write, snapshot, reward helper를 검증한다.
"""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

from src.agents.rl_split_bandit import (
    DEFAULT_RATIOS,
    ArmStats,
    BanditState,
    RLSplitBandit,
    _ratio_key,
    reward_from_walk_forward,
)


class RLSplitBanditConstructorTest(unittest.TestCase):
    def test_init_rejects_empty_ratios(self) -> None:
        with self.assertRaises(ValueError):
            RLSplitBandit(ratios=[])

    def test_init_rejects_negative_epsilon(self) -> None:
        with self.assertRaises(ValueError):
            RLSplitBandit(epsilon=-0.1)

    def test_init_rejects_epsilon_above_one(self) -> None:
        with self.assertRaises(ValueError):
            RLSplitBandit(epsilon=1.5)

    def test_default_ratios_are_round_to_two_decimals(self) -> None:
        bandit = RLSplitBandit(ratios=[0.500001, 0.6, 0.799999])
        self.assertEqual(bandit.ratios, (0.5, 0.6, 0.8))


class RLSplitBanditSelectTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage = Path(self._tmp.name)

    def _bandit(self, *, epsilon: float = 0.0, seed: int = 0) -> RLSplitBandit:
        return RLSplitBandit(
            storage_dir=self.storage,
            ratios=DEFAULT_RATIOS,
            epsilon=epsilon,
            rng=random.Random(seed),
        )

    def test_cold_start_visits_every_arm_first(self) -> None:
        bandit = self._bandit(epsilon=0.0)
        picked: list[float] = []
        for _ in range(len(DEFAULT_RATIOS)):
            ratio = bandit.select_ratio("X", "p")
            bandit.update("X", "p", ratio, reward=0.0)
            picked.append(ratio)
        self.assertEqual(sorted(picked), list(DEFAULT_RATIOS))

    def test_greedy_picks_highest_mean_reward_after_warmup(self) -> None:
        bandit = self._bandit(epsilon=0.0)
        # cold-start 4회, 0.6에만 높은 보상
        for ratio in DEFAULT_RATIOS:
            bandit.update("X", "p", ratio, reward=10.0 if ratio == 0.6 else 0.0)

        # epsilon=0이므로 무조건 best arm
        for _ in range(5):
            self.assertEqual(bandit.select_ratio("X", "p"), 0.6)

    def test_tie_break_prefers_smaller_ratio(self) -> None:
        bandit = self._bandit(epsilon=0.0)
        # 모든 arm에 동일 보상
        for ratio in DEFAULT_RATIOS:
            bandit.update("X", "p", ratio, reward=1.0)
        self.assertEqual(bandit.select_ratio("X", "p"), 0.5)

    def test_epsilon_one_explores_all_arms(self) -> None:
        bandit = self._bandit(epsilon=1.0, seed=42)
        # 0.6에만 큰 보상을 줘서 greedy면 항상 0.6이 나올 환경 만든 뒤
        for ratio in DEFAULT_RATIOS:
            bandit.update("X", "p", ratio, reward=100.0 if ratio == 0.6 else 0.0)

        seen: set[float] = set()
        for _ in range(200):
            seen.add(bandit.select_ratio("X", "p"))
        self.assertEqual(seen, set(DEFAULT_RATIOS))


class RLSplitBanditUpdateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage = Path(self._tmp.name)

    def test_update_increments_pulls_and_accumulates_reward(self) -> None:
        bandit = RLSplitBandit(storage_dir=self.storage, epsilon=0.0)
        bandit.update("X", "p", 0.7, reward=2.0)
        arm = bandit.update("X", "p", 0.7, reward=4.0)
        self.assertEqual(arm.pulls, 2)
        self.assertAlmostEqual(arm.total_reward, 6.0)
        self.assertAlmostEqual(arm.mean_reward, 3.0)
        self.assertAlmostEqual(arm.last_reward, 4.0)
        self.assertIsNotNone(arm.last_pulled_at)

    def test_update_rejects_unknown_ratio(self) -> None:
        bandit = RLSplitBandit(storage_dir=self.storage, epsilon=0.0)
        with self.assertRaises(ValueError):
            bandit.update("X", "p", 0.99, reward=1.0)


class RLSplitBanditPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage = Path(self._tmp.name)

    def test_persistence_round_trip(self) -> None:
        bandit_a = RLSplitBandit(storage_dir=self.storage, epsilon=0.0)
        bandit_a.update("005930.KS", "v2", 0.6, reward=3.0)
        bandit_a.update("005930.KS", "v2", 0.6, reward=5.0)

        bandit_b = RLSplitBandit(storage_dir=self.storage, epsilon=0.0)
        snapshot = bandit_b.snapshot("005930.KS", "v2")
        arm = snapshot["arms"][_ratio_key(0.6)]
        self.assertEqual(arm["pulls"], 2)
        self.assertAlmostEqual(arm["total_reward"], 8.0)
        self.assertAlmostEqual(arm["mean_reward"], 4.0)

    def test_load_corrupted_file_resets_state(self) -> None:
        bandit = RLSplitBandit(storage_dir=self.storage, epsilon=0.0)
        # 손상된 JSON 파일 미리 두고
        path = self.storage / "X__p.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json", encoding="utf-8")

        snapshot = bandit.snapshot("X", "p")
        # 모든 arm pulls=0
        for arm in snapshot["arms"].values():
            self.assertEqual(arm["pulls"], 0)

    def test_atomic_write_leaves_no_partial_files(self) -> None:
        bandit = RLSplitBandit(storage_dir=self.storage, epsilon=0.0)
        bandit.update("X", "p", 0.7, reward=1.0)
        leftovers = list(self.storage.glob("*.tmp"))
        self.assertEqual(leftovers, [])
        self.assertTrue((self.storage / "X__p.json").exists())

    def test_state_path_sanitizes_slashes(self) -> None:
        bandit = RLSplitBandit(storage_dir=self.storage, epsilon=0.0)
        bandit.update("a/b", "x/y", 0.7, reward=1.0)
        self.assertTrue((self.storage / "a_b__x_y.json").exists())


class RLSplitBanditSnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage = Path(self._tmp.name)

    def test_snapshot_includes_all_ratios_even_unpulled(self) -> None:
        bandit = RLSplitBandit(storage_dir=self.storage, epsilon=0.0)
        bandit.update("X", "p", 0.7, reward=1.0)
        snapshot = bandit.snapshot("X", "p")
        keys = set(snapshot["arms"].keys())
        self.assertEqual(keys, {_ratio_key(r) for r in DEFAULT_RATIOS})
        # 0.7만 pull, 나머지는 0
        self.assertEqual(snapshot["arms"][_ratio_key(0.7)]["pulls"], 1)
        self.assertEqual(snapshot["arms"][_ratio_key(0.5)]["pulls"], 0)

    def test_snapshot_best_ratio_reflects_top_mean(self) -> None:
        bandit = RLSplitBandit(storage_dir=self.storage, epsilon=0.0)
        bandit.update("X", "p", 0.5, reward=1.0)
        bandit.update("X", "p", 0.6, reward=5.0)
        snapshot = bandit.snapshot("X", "p")
        self.assertEqual(snapshot["best_ratio"], 0.6)

    def test_snapshot_best_ratio_none_when_no_pulls(self) -> None:
        bandit = RLSplitBandit(storage_dir=self.storage, epsilon=0.0)
        snapshot = bandit.snapshot("X", "p")
        self.assertIsNone(snapshot["best_ratio"])

    def test_snapshot_is_json_serializable(self) -> None:
        bandit = RLSplitBandit(storage_dir=self.storage, epsilon=0.0)
        bandit.update("X", "p", 0.7, reward=1.0)
        # raise되지 않아야 한다
        json.dumps(bandit.snapshot("X", "p"))


class RewardHelperTest(unittest.TestCase):
    def test_reward_from_walk_forward_combines_signals(self) -> None:
        r = reward_from_walk_forward(consistency_score=0.8, excess_return_pct=10.0)
        self.assertAlmostEqual(r, 0.6 * 0.8 + 0.4 * 0.1, places=6)

    def test_reward_handles_negative_excess(self) -> None:
        r = reward_from_walk_forward(consistency_score=0.5, excess_return_pct=-20.0)
        self.assertAlmostEqual(r, 0.6 * 0.5 + 0.4 * -0.2, places=6)


class ArmStatsRoundTripTest(unittest.TestCase):
    def test_to_from_dict(self) -> None:
        arm = ArmStats(
            ratio=0.6, pulls=3, total_reward=4.5, last_reward=2.1, last_pulled_at="2026-04-07T00:00:00+00:00"
        )
        restored = ArmStats.from_dict(arm.to_dict())
        self.assertEqual(restored.pulls, arm.pulls)
        self.assertAlmostEqual(restored.total_reward, arm.total_reward)
        self.assertAlmostEqual(restored.last_reward, arm.last_reward)
        self.assertEqual(restored.last_pulled_at, arm.last_pulled_at)


class BanditStateRoundTripTest(unittest.TestCase):
    def test_to_from_dict(self) -> None:
        state = BanditState(
            ticker="X",
            profile_id="p",
            arms={_ratio_key(0.7): ArmStats(ratio=0.7, pulls=1, total_reward=1.0)},
            updated_at="2026-04-07T00:00:00+00:00",
        )
        restored = BanditState.from_dict(state.to_dict())
        self.assertEqual(restored.ticker, "X")
        self.assertEqual(restored.profile_id, "p")
        self.assertIn(_ratio_key(0.7), restored.arms)


if __name__ == "__main__":
    unittest.main()
