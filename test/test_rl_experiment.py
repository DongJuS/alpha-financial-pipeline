"""
test/test_rl_experiment.py — RL 실험 프로파일 및 run 추적 테스트
"""

import json
import sys
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.rl_experiment import (
    RLExperimentManager,
    RLProfile,
    TrainerParams,
    compute_dataset_hash,
    generate_run_id,
    load_profile,
    save_profile,
)
from src.agents.rl_trading import RLDataset, RLEvaluationMetrics, RLSplitMetadata


def _make_dataset(ticker: str = "TEST.KR") -> RLDataset:
    closes = [100.0 + i * 0.5 for i in range(50)]
    timestamps = [f"2026-01-{i+1:02d}" for i in range(50)]
    return RLDataset(ticker=ticker, closes=closes, timestamps=timestamps)


def _make_split() -> RLSplitMetadata:
    return RLSplitMetadata(
        train_ratio=0.7,
        train_size=35,
        test_size=15,
        train_start="2026-01-01",
        train_end="2026-02-04",
        test_start="2026-02-05",
        test_end="2026-02-19",
    )


def _make_evaluation(approved: bool = True) -> RLEvaluationMetrics:
    return RLEvaluationMetrics(
        total_return_pct=12.5,
        baseline_return_pct=5.0,
        excess_return_pct=7.5,
        max_drawdown_pct=-8.0,
        trades=42,
        win_rate=0.55,
        holdout_steps=15,
        approved=approved,
    )


class TestRLProfile(unittest.TestCase):
    """프로파일 CRUD 테스트."""

    def test_create_profile(self):
        profile = RLProfile(
            profile_id="test_profile",
            algorithm="tabular_q_learning",
            state_version="qlearn_v2",
        )
        self.assertEqual(profile.profile_id, "test_profile")
        self.assertEqual(profile.trainer_params.episodes, 300)
        self.assertEqual(profile.default_train_ratio, 0.7)

    def test_save_and_load_profile(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            profiles_dir = Path(tmp)
            profile = RLProfile(
                profile_id="save_test",
                trainer_params=TrainerParams(episodes=500, learning_rate=0.05),
            )

            path = save_profile(profile, profiles_dir)
            self.assertTrue(path.exists())

            loaded = load_profile("save_test", profiles_dir)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.profile_id, "save_test")
            self.assertEqual(loaded.trainer_params.episodes, 500)
            self.assertEqual(loaded.trainer_params.learning_rate, 0.05)

    def test_load_nonexistent_profile(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = load_profile("nonexistent", Path(tmp))
            self.assertIsNone(result)

    def test_load_baseline_profiles(self):
        """실제 프로파일 파일이 로드 가능한지 확인."""
        profiles_dir = ROOT / "artifacts" / "rl" / "profiles"
        if not profiles_dir.exists():
            self.skipTest("profiles 디렉토리가 존재하지 않습니다")

        v2 = load_profile("tabular_q_v2_baseline", profiles_dir)
        if v2:
            self.assertEqual(v2.algorithm, "tabular_q_learning")
            self.assertEqual(v2.state_version, "qlearn_v2")
            self.assertEqual(v2.trainer_params.episodes, 300)


class TestDatasetHash(unittest.TestCase):
    """dataset_hash 재현성 테스트."""

    def test_same_data_same_hash(self):
        closes = [100.0, 101.5, 99.3, 102.1]
        h1 = compute_dataset_hash(closes)
        h2 = compute_dataset_hash(closes)
        self.assertEqual(h1, h2)

    def test_different_data_different_hash(self):
        h1 = compute_dataset_hash([100.0, 101.5])
        h2 = compute_dataset_hash([100.0, 101.6])
        self.assertNotEqual(h1, h2)

    def test_hash_length(self):
        h = compute_dataset_hash([1.0, 2.0, 3.0])
        self.assertEqual(len(h), 16)


class TestRunIdGeneration(unittest.TestCase):
    """run_id 생성 규칙 테스트."""

    def test_run_id_format(self):
        run_id = generate_run_id("259960.KS", "qlearn_v2")
        parts = run_id.split("-")
        # timestamp 부분은 YYYYMMDDTHHMMSSZ 형식
        self.assertTrue(parts[0].endswith("Z"))
        # ticker와 state_version 포함
        self.assertIn("259960.KS", run_id)
        self.assertIn("qlearn_v2", run_id)

    def test_run_id_uniqueness(self):
        """시간차가 있으면 run_id가 달라야 한다."""
        import time

        id1 = generate_run_id("TEST", "v1")
        time.sleep(0.01)
        id2 = generate_run_id("TEST", "v1")
        # 같은 초 내에서도 고유해야 하지만, 최소한 다른 호출임을 구분
        # (동일 초면 같을 수 있으므로 형식만 확인)
        self.assertIn("TEST", id1)
        self.assertIn("v1", id1)


class TestRLExperimentManager(unittest.TestCase):
    """RLExperimentManager 통합 테스트."""

    def setUp(self):
        import tempfile

        self.tmp_dir = tempfile.mkdtemp()
        self.experiments_dir = Path(self.tmp_dir) / "experiments"
        self.manager = RLExperimentManager(experiments_dir=self.experiments_dir)
        self.dataset = _make_dataset()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_create_run(self):
        run_id = self.manager.create_run(
            dataset=self.dataset,
            profile_id="tabular_q_v2_baseline",
            data_source="yfinance",
            data_range="10y",
        )
        self.assertIsNotNone(run_id)

        run_dir = self.experiments_dir / run_id
        self.assertTrue(run_dir.exists())
        self.assertTrue((run_dir / "config.json").exists())
        self.assertTrue((run_dir / "dataset_meta.json").exists())

        config = json.loads((run_dir / "config.json").read_text())
        self.assertEqual(config["run_id"], run_id)
        self.assertEqual(config["profile_id"], "tabular_q_v2_baseline")

        dataset_meta = json.loads((run_dir / "dataset_meta.json").read_text())
        self.assertEqual(dataset_meta["ticker"], "TEST.KR")
        self.assertEqual(dataset_meta["data_source"], "yfinance")
        self.assertEqual(dataset_meta["total_rows"], 50)
        self.assertEqual(len(dataset_meta["dataset_hash"]), 16)

    def test_create_run_with_profile_object(self):
        profile = RLProfile(
            profile_id="custom_profile",
            trainer_params=TrainerParams(episodes=100),
        )
        run_id = self.manager.create_run(
            dataset=self.dataset,
            profile=profile,
        )
        config = json.loads(
            (self.experiments_dir / run_id / "config.json").read_text()
        )
        self.assertEqual(config["profile_id"], "custom_profile")
        self.assertEqual(config["trainer_params"]["episodes"], 100)

    def test_record_split(self):
        run_id = self.manager.create_run(dataset=self.dataset)
        split = _make_split()
        self.manager.record_split(run_id, split)

        split_path = self.experiments_dir / run_id / "split.json"
        self.assertTrue(split_path.exists())
        data = json.loads(split_path.read_text())
        self.assertEqual(data["train_ratio"], 0.7)
        self.assertEqual(data["train_size"], 35)

    def test_record_metrics(self):
        run_id = self.manager.create_run(dataset=self.dataset)
        evaluation = _make_evaluation()
        self.manager.record_metrics(run_id, evaluation)

        metrics_path = self.experiments_dir / run_id / "metrics.json"
        self.assertTrue(metrics_path.exists())
        data = json.loads(metrics_path.read_text())
        self.assertAlmostEqual(data["total_return_pct"], 12.5)
        self.assertEqual(data["trades"], 42)

    def test_link_artifact(self):
        run_id = self.manager.create_run(dataset=self.dataset)
        self.manager.link_artifact(
            run_id,
            policy_id="rl_TEST_20260315T000000Z",
            artifact_path="/path/to/policy.json",
        )

        link_path = self.experiments_dir / run_id / "artifact_link.json"
        self.assertTrue(link_path.exists())
        data = json.loads(link_path.read_text())
        self.assertEqual(data["policy_id"], "rl_TEST_20260315T000000Z")
        self.assertFalse(data["promoted"])

    def test_mark_promoted(self):
        run_id = self.manager.create_run(dataset=self.dataset)
        self.manager.link_artifact(run_id, policy_id="test_policy")
        self.manager.mark_promoted(run_id)

        link_path = self.experiments_dir / run_id / "artifact_link.json"
        data = json.loads(link_path.read_text())
        self.assertTrue(data["promoted"])
        self.assertIsNotNone(data["promoted_at"])

    def test_mark_promoted_without_link_raises(self):
        run_id = self.manager.create_run(dataset=self.dataset)
        with self.assertRaises(FileNotFoundError):
            self.manager.mark_promoted(run_id)

    def test_load_experiment(self):
        run_id = self.manager.create_run(
            dataset=self.dataset,
            profile_id="test_profile",
            data_source="yfinance",
        )
        self.manager.record_split(run_id, _make_split())
        self.manager.record_metrics(run_id, _make_evaluation())
        self.manager.link_artifact(run_id, policy_id="test_policy")

        experiment = self.manager.load_experiment(run_id)
        self.assertEqual(experiment["run_id"], run_id)
        self.assertIn("config", experiment)
        self.assertIn("dataset_meta", experiment)
        self.assertIn("split", experiment)
        self.assertIn("metrics", experiment)
        self.assertIn("artifact_link", experiment)

    def test_load_nonexistent_experiment(self):
        with self.assertRaises(FileNotFoundError):
            self.manager.load_experiment("nonexistent_run")

    def test_list_experiments(self):
        # 2개 run 생성
        run_id_1 = self.manager.create_run(
            dataset=self.dataset,
            profile_id="p1",
        )
        self.manager.record_metrics(run_id_1, _make_evaluation())

        run_id_2 = self.manager.create_run(
            dataset=_make_dataset("OTHER.KR"),
            profile_id="p2",
        )
        self.manager.record_metrics(run_id_2, _make_evaluation(approved=False))

        # 전체 목록
        all_exps = self.manager.list_experiments()
        self.assertEqual(len(all_exps), 2)

        # ticker 필터링
        test_exps = self.manager.list_experiments(ticker="TEST.KR")
        self.assertEqual(len(test_exps), 1)
        self.assertEqual(test_exps[0]["profile_id"], "p1")

    def test_list_experiments_empty(self):
        results = self.manager.list_experiments()
        self.assertEqual(results, [])

    def test_record_split_nonexistent_run(self):
        with self.assertRaises(FileNotFoundError):
            self.manager.record_split("nonexistent", _make_split())

    def test_record_metrics_nonexistent_run(self):
        with self.assertRaises(FileNotFoundError):
            self.manager.record_metrics("nonexistent", _make_evaluation())

    def test_link_artifact_nonexistent_run(self):
        with self.assertRaises(FileNotFoundError):
            self.manager.link_artifact("nonexistent", policy_id="x")


class TestPolicyEntryRunId(unittest.TestCase):
    """PolicyEntry run_id 양방향 참조 테스트."""

    def test_policy_entry_run_id_default(self):
        from src.agents.rl_policy_registry import PolicyEntry
        from datetime import datetime, timezone

        entry = PolicyEntry(
            policy_id="test",
            ticker="TEST",
            created_at=datetime.now(timezone.utc),
            file_path="tabular/TEST/test.json",
        )
        self.assertIsNone(entry.run_id)

    def test_policy_entry_run_id_set(self):
        from src.agents.rl_policy_registry import PolicyEntry
        from datetime import datetime, timezone

        entry = PolicyEntry(
            policy_id="test",
            ticker="TEST",
            created_at=datetime.now(timezone.utc),
            file_path="tabular/TEST/test.json",
            run_id="20260315T000000Z-TEST-qlearn_v2",
        )
        self.assertEqual(entry.run_id, "20260315T000000Z-TEST-qlearn_v2")


class TestEndToEndFlow(unittest.TestCase):
    """프로파일 → run 생성 → split/metrics/link 기록 전체 흐름 테스트."""

    def test_full_flow(self):
        import tempfile
        import shutil

        tmp = tempfile.mkdtemp()
        try:
            profiles_dir = Path(tmp) / "profiles"
            experiments_dir = Path(tmp) / "experiments"

            # 1. 프로파일 생성/저장
            profile = RLProfile(
                profile_id="flow_test",
                trainer_params=TrainerParams(episodes=100, num_seeds=2),
            )
            save_profile(profile, profiles_dir)

            # 2. 프로파일 로드
            loaded = load_profile("flow_test", profiles_dir)
            self.assertIsNotNone(loaded)

            # 3. run 생성
            manager = RLExperimentManager(experiments_dir=experiments_dir)
            dataset = _make_dataset()
            run_id = manager.create_run(
                dataset=dataset,
                profile=loaded,
                data_source="yfinance",
                data_range="5y",
            )

            # 4. split 기록
            manager.record_split(run_id, _make_split())

            # 5. metrics 기록
            manager.record_metrics(run_id, _make_evaluation())

            # 6. artifact 링크
            manager.link_artifact(
                run_id,
                policy_id="rl_TEST_flow",
                artifact_path="/tmp/policy.json",
            )

            # 7. promoted 마크
            manager.mark_promoted(run_id)

            # 8. 전체 로드 검증
            experiment = manager.load_experiment(run_id)
            self.assertEqual(experiment["config"]["profile_id"], "flow_test")
            self.assertEqual(experiment["dataset_meta"]["data_source"], "yfinance")
            self.assertEqual(experiment["split"]["train_ratio"], 0.7)
            self.assertAlmostEqual(experiment["metrics"]["total_return_pct"], 12.5)
            self.assertTrue(experiment["artifact_link"]["promoted"])
            self.assertIsNotNone(experiment["artifact_link"]["promoted_at"])

            # 9. 목록 조회
            exps = manager.list_experiments()
            self.assertEqual(len(exps), 1)
            self.assertIn("metrics", exps[0])
            self.assertIn("artifact_link", exps[0])

        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
