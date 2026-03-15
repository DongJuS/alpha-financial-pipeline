"""
test/test_rl_experiment_manager.py — RL 실험 관리자 단위 테스트

RLExperimentManager의 주요 기능을 검증합니다.
- 프로파일 로드
- 실험 run 생성 및 파일 구조
- 결과 기록
- run 조회 및 필터링
- 인덱스 구축
- 정책과 실험 양방향 링크
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.agents.rl_experiment_manager import (
    RLDatasetMeta,
    RLExperimentConfig,
    RLExperimentManager,
    RLExperimentRun,
)
from src.agents.rl_trading import (
    RLDataset,
    RLEvaluationMetrics,
    RLPolicyArtifact,
    RLSplitMetadata,
)


class MockTrainer:
    """테스트용 mock trainer."""

    def __init__(
        self,
        lookback: int = 6,
        episodes: int = 60,
        learning_rate: float = 0.18,
        discount_factor: float = 0.92,
        epsilon: float = 0.15,
        trade_penalty_bps: int = 5,
        random_seed: int = 42,
    ) -> None:
        self.lookback = lookback
        self.episodes = episodes
        self.learning_rate = learning_rate
        self.discount_factor = discount_factor
        self.epsilon = epsilon
        self.trade_penalty_bps = trade_penalty_bps
        self.random_seed = random_seed


class TestRLExperimentManagerProfileLoading(unittest.TestCase):
    """프로파일 로딩 테스트."""

    def test_load_profile_tabular_q_v1(self) -> None:
        """tabular_q_v1_baseline 프로파일을 로드할 수 있다."""
        root = Path(__file__).resolve().parents[1]
        artifacts_dir = root / "artifacts" / "rl"
        manager = RLExperimentManager(artifacts_dir)

        profile = manager.load_profile("tabular_q_v1_baseline")

        self.assertEqual(profile["profile_id"], "tabular_q_v1_baseline")
        self.assertEqual(profile["algorithm"], "tabular_q_learning")
        self.assertEqual(profile["state_version"], "qlearn_v1")
        self.assertEqual(profile["trainer_params"]["lookback"], 6)
        self.assertEqual(profile["trainer_params"]["episodes"], 60)
        self.assertEqual(profile["trainer_params"]["learning_rate"], 0.18)

    def test_load_profile_tabular_q_v2(self) -> None:
        """tabular_q_v2_momentum 프로파일을 로드할 수 있다."""
        root = Path(__file__).resolve().parents[1]
        artifacts_dir = root / "artifacts" / "rl"
        manager = RLExperimentManager(artifacts_dir)

        profile = manager.load_profile("tabular_q_v2_momentum")

        self.assertEqual(profile["profile_id"], "tabular_q_v2_momentum")
        self.assertEqual(profile["algorithm"], "tabular_q_learning")
        self.assertEqual(profile["state_version"], "qlearn_v2")
        self.assertEqual(profile["trainer_params"]["lookback"], 20)
        self.assertEqual(profile["trainer_params"]["episodes"], 300)
        self.assertIn("opportunity_cost_factor", profile["trainer_params"])

    def test_load_nonexistent_profile_raises_error(self) -> None:
        """존재하지 않는 프로파일은 ValueError를 던진다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = RLExperimentManager(Path(tmpdir))

            with self.assertRaises(ValueError) as ctx:
                manager.load_profile("nonexistent_profile")

            self.assertIn("nonexistent_profile", str(ctx.exception))


class TestRLExperimentManagerCreateRun(unittest.TestCase):
    """실험 run 생성 테스트."""

    def setUp(self) -> None:
        """임시 디렉토리 준비."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        """임시 디렉토리 정리."""
        self.temp_dir.cleanup()

    def _setup_profile(self) -> None:
        """테스트용 프로파일 생성."""
        profiles_dir = self.artifacts_dir / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile = {
            "profile_id": "test_profile",
            "algorithm": "tabular_q_learning",
            "state_version": "qlearn_v1",
            "trainer_params": {
                "lookback": 6,
                "episodes": 60,
                "learning_rate": 0.18,
            },
            "dataset": {"default_source": "yfinance", "default_range": "10y"},
            "evaluation": {"min_approval_return_pct": 5.0},
        }
        (profiles_dir / "test_profile.json").write_text(json.dumps(profile), encoding="utf-8")

    def test_create_run_returns_valid_run_id(self) -> None:
        """create_run이 올바른 형식의 run_id를 반환한다."""
        self._setup_profile()
        manager = RLExperimentManager(self.artifacts_dir)

        dataset = RLDataset(
            ticker="259960.KS",
            closes=[100.0 + i * 0.5 for i in range(100)],
            timestamps=[f"2026-01-{i % 28 + 1:02d}" for i in range(100)],
        )
        trainer = MockTrainer()

        run_id = manager.create_run("259960.KS", "test_profile", trainer, dataset)

        # run_id 형식 검증: <YYYYMMDD>T<HHMMSS>Z-<ticker>-<state_version>
        parts = run_id.split("-")
        self.assertEqual(len(parts), 3)
        self.assertIn("259960.KS", parts[1])
        self.assertIn("qlearn_v1", parts[2])

    def test_create_run_creates_directory_structure(self) -> None:
        """create_run이 올바른 디렉토리 구조를 생성한다."""
        self._setup_profile()
        manager = RLExperimentManager(self.artifacts_dir)

        dataset = RLDataset(
            ticker="TEST",
            closes=[100.0 + i for i in range(50)],
            timestamps=[f"2026-01-{i % 28 + 1:02d}" for i in range(50)],
        )
        trainer = MockTrainer()

        run_id = manager.create_run("TEST", "test_profile", trainer, dataset)
        run_dir = self.artifacts_dir / "experiments" / run_id

        self.assertTrue(run_dir.exists())
        self.assertTrue((run_dir / "config.json").exists())
        self.assertTrue((run_dir / "dataset_meta.json").exists())
        self.assertTrue((run_dir / "split.json").exists())

    def test_create_run_config_file_is_valid_json(self) -> None:
        """생성된 config.json은 유효한 JSON이다."""
        self._setup_profile()
        manager = RLExperimentManager(self.artifacts_dir)

        dataset = RLDataset(
            ticker="TEST",
            closes=[100.0 + i for i in range(50)],
            timestamps=[f"2026-01-{i % 28 + 1:02d}" for i in range(50)],
        )
        trainer = MockTrainer()

        run_id = manager.create_run("TEST", "test_profile", trainer, dataset)
        config_path = self.artifacts_dir / "experiments" / run_id / "config.json"

        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["profile_id"], "test_profile")
        self.assertEqual(config["algorithm"], "tabular_q_learning")
        self.assertIn("trainer_params", config)

    def test_create_run_with_overrides(self) -> None:
        """오버라이드를 지정하면 config에 반영된다."""
        self._setup_profile()
        manager = RLExperimentManager(self.artifacts_dir)

        dataset = RLDataset(
            ticker="TEST",
            closes=[100.0 + i for i in range(50)],
            timestamps=[f"2026-01-{i % 28 + 1:02d}" for i in range(50)],
        )
        trainer = MockTrainer()
        overrides = {"learning_rate": 0.25}

        run_id = manager.create_run("TEST", "test_profile", trainer, dataset, overrides=overrides)
        config_path = self.artifacts_dir / "experiments" / run_id / "config.json"

        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["overrides"]["learning_rate"], 0.25)


class TestRLExperimentManagerRecordResults(unittest.TestCase):
    """결과 기록 테스트."""

    def setUp(self) -> None:
        """임시 디렉토리 및 프로파일 준비."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self.temp_dir.name)
        self._setup_profile()

    def tearDown(self) -> None:
        """임시 디렉토리 정리."""
        self.temp_dir.cleanup()

    def _setup_profile(self) -> None:
        """테스트용 프로파일 생성."""
        profiles_dir = self.artifacts_dir / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile = {
            "profile_id": "test_profile",
            "algorithm": "tabular_q_learning",
            "state_version": "qlearn_v1",
            "trainer_params": {"lookback": 6, "episodes": 60},
            "dataset": {},
            "evaluation": {},
        }
        (profiles_dir / "test_profile.json").write_text(json.dumps(profile), encoding="utf-8")

    def test_record_results_creates_metrics_file(self) -> None:
        """record_results가 metrics.json을 생성한다."""
        manager = RLExperimentManager(self.artifacts_dir)

        dataset = RLDataset(
            ticker="TEST",
            closes=[100.0 + i for i in range(50)],
            timestamps=[f"2026-01-{i % 28 + 1:02d}" for i in range(50)],
        )
        trainer = MockTrainer()

        run_id = manager.create_run("TEST", "test_profile", trainer, dataset)

        artifact = RLPolicyArtifact(
            policy_id="rl_TEST_20260314T120000Z",
            ticker="TEST",
            created_at=datetime.now(timezone.utc).isoformat(),
            algorithm="tabular_q_learning",
            state_version="qlearn_v1",
            lookback=6,
            episodes=60,
            learning_rate=0.18,
            discount_factor=0.92,
            epsilon=0.15,
            trade_penalty_bps=5,
            q_table={},
            evaluation=RLEvaluationMetrics(
                total_return_pct=8.5,
                baseline_return_pct=3.0,
                excess_return_pct=5.5,
                max_drawdown_pct=-12.0,
                trades=10,
                win_rate=0.6,
                holdout_steps=20,
                approved=True,
            ),
        )

        metrics = artifact.evaluation
        split_meta = RLSplitMetadata(
            train_ratio=0.7,
            train_size=35,
            test_size=15,
            train_start="2026-01-01",
            train_end="2026-01-25",
            test_start="2026-01-26",
            test_end="2026-02-19",
        )

        manager.record_results(run_id, artifact, metrics, split_meta)

        metrics_path = self.artifacts_dir / "experiments" / run_id / "metrics.json"
        self.assertTrue(metrics_path.exists())

        metrics_data = json.loads(metrics_path.read_text(encoding="utf-8"))
        self.assertEqual(metrics_data["total_return_pct"], 8.5)
        self.assertTrue(metrics_data["approved"])

    def test_record_results_creates_artifact_link(self) -> None:
        """record_results가 artifact_link.json을 생성한다."""
        manager = RLExperimentManager(self.artifacts_dir)

        dataset = RLDataset(
            ticker="TEST",
            closes=[100.0 + i for i in range(50)],
            timestamps=[f"2026-01-{i % 28 + 1:02d}" for i in range(50)],
        )
        trainer = MockTrainer()

        run_id = manager.create_run("TEST", "test_profile", trainer, dataset)

        artifact = RLPolicyArtifact(
            policy_id="rl_TEST_20260314T120000Z",
            ticker="TEST",
            created_at=datetime.now(timezone.utc).isoformat(),
            algorithm="tabular_q_learning",
            state_version="qlearn_v1",
            lookback=6,
            episodes=60,
            learning_rate=0.18,
            discount_factor=0.92,
            epsilon=0.15,
            trade_penalty_bps=5,
            q_table={},
            evaluation=RLEvaluationMetrics(
                total_return_pct=8.5,
                baseline_return_pct=3.0,
                excess_return_pct=5.5,
                max_drawdown_pct=-12.0,
                trades=10,
                win_rate=0.6,
                holdout_steps=20,
                approved=True,
            ),
            artifact_path="/artifacts/rl/models/tabular/TEST/rl_TEST_20260314T120000Z.json",
        )

        metrics = artifact.evaluation
        split_meta = RLSplitMetadata(
            train_ratio=0.7,
            train_size=35,
            test_size=15,
            train_start="2026-01-01",
            train_end="2026-01-25",
            test_start="2026-01-26",
            test_end="2026-02-19",
        )

        manager.record_results(run_id, artifact, metrics, split_meta)

        link_path = self.artifacts_dir / "experiments" / run_id / "artifact_link.json"
        self.assertTrue(link_path.exists())

        link = json.loads(link_path.read_text(encoding="utf-8"))
        self.assertEqual(link["policy_id"], "rl_TEST_20260314T120000Z")


class TestRLExperimentManagerLoadRun(unittest.TestCase):
    """run 로딩 테스트."""

    def setUp(self) -> None:
        """임시 디렉토리 및 프로파일 준비."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self.temp_dir.name)
        self._setup_profile()

    def tearDown(self) -> None:
        """임시 디렉토리 정리."""
        self.temp_dir.cleanup()

    def _setup_profile(self) -> None:
        """테스트용 프로파일 생성."""
        profiles_dir = self.artifacts_dir / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile = {
            "profile_id": "test_profile",
            "algorithm": "tabular_q_learning",
            "state_version": "qlearn_v1",
            "trainer_params": {"lookback": 6},
            "dataset": {},
            "evaluation": {},
        }
        (profiles_dir / "test_profile.json").write_text(json.dumps(profile), encoding="utf-8")

    def _create_sample_run(self) -> str:
        """샘플 run을 생성하고 run_id를 반환."""
        manager = RLExperimentManager(self.artifacts_dir)

        dataset = RLDataset(
            ticker="TEST",
            closes=[100.0 + i for i in range(50)],
            timestamps=[f"2026-01-{i % 28 + 1:02d}" for i in range(50)],
        )
        trainer = MockTrainer()

        run_id = manager.create_run("TEST", "test_profile", trainer, dataset)

        artifact = RLPolicyArtifact(
            policy_id="rl_TEST_20260314T120000Z",
            ticker="TEST",
            created_at=datetime.now(timezone.utc).isoformat(),
            algorithm="tabular_q_learning",
            state_version="qlearn_v1",
            lookback=6,
            episodes=60,
            learning_rate=0.18,
            discount_factor=0.92,
            epsilon=0.15,
            trade_penalty_bps=5,
            q_table={},
            evaluation=RLEvaluationMetrics(
                total_return_pct=8.5,
                baseline_return_pct=3.0,
                excess_return_pct=5.5,
                max_drawdown_pct=-12.0,
                trades=10,
                win_rate=0.6,
                holdout_steps=20,
                approved=True,
            ),
        )

        metrics = artifact.evaluation
        split_meta = RLSplitMetadata(
            train_ratio=0.7,
            train_size=35,
            test_size=15,
            train_start="2026-01-01",
            train_end="2026-01-25",
            test_start="2026-01-26",
            test_end="2026-02-19",
        )

        manager.record_results(run_id, artifact, metrics, split_meta)

        return run_id

    def test_load_run_returns_valid_run(self) -> None:
        """load_run이 유효한 RLExperimentRun을 반환한다."""
        manager = RLExperimentManager(self.artifacts_dir)
        run_id = self._create_sample_run()

        run = manager.load_run(run_id)

        self.assertEqual(run.run_id, run_id)
        self.assertEqual(run.config.profile_id, "test_profile")
        self.assertEqual(run.metrics.total_return_pct, 8.5)
        self.assertTrue(run.approved)

    def test_load_run_includes_all_metadata(self) -> None:
        """load_run이 모든 메타데이터를 포함한다."""
        manager = RLExperimentManager(self.artifacts_dir)
        run_id = self._create_sample_run()

        run = manager.load_run(run_id)

        self.assertIsNotNone(run.dataset_meta)
        self.assertEqual(run.dataset_meta.ticker, "TEST")
        self.assertIsNotNone(run.split_metadata)
        self.assertEqual(run.split_metadata.train_ratio, 0.7)


class TestRLExperimentManagerListRuns(unittest.TestCase):
    """run 조회 및 필터링 테스트."""

    def setUp(self) -> None:
        """임시 디렉토리 및 프로파일 준비."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self.temp_dir.name)
        self._setup_profiles()

    def tearDown(self) -> None:
        """임시 디렉토리 정리."""
        self.temp_dir.cleanup()

    def _setup_profiles(self) -> None:
        """테스트용 프로파일들 생성."""
        profiles_dir = self.artifacts_dir / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)

        for profile_id in ["test_profile_a", "test_profile_b"]:
            profile = {
                "profile_id": profile_id,
                "algorithm": "tabular_q_learning",
                "state_version": "qlearn_v1",
                "trainer_params": {"lookback": 6},
                "dataset": {},
                "evaluation": {},
            }
            (profiles_dir / f"{profile_id}.json").write_text(
                json.dumps(profile), encoding="utf-8"
            )

    def _create_sample_run(
        self, ticker: str, profile_id: str, approved: bool = True
    ) -> str:
        """샘플 run을 생성."""
        manager = RLExperimentManager(self.artifacts_dir)

        dataset = RLDataset(
            ticker=ticker,
            closes=[100.0 + i for i in range(50)],
            timestamps=[f"2026-01-{i % 28 + 1:02d}" for i in range(50)],
        )
        trainer = MockTrainer()

        run_id = manager.create_run(ticker, profile_id, trainer, dataset)

        artifact = RLPolicyArtifact(
            policy_id=f"rl_{ticker}_20260314T120000Z",
            ticker=ticker,
            created_at=datetime.now(timezone.utc).isoformat(),
            algorithm="tabular_q_learning",
            state_version="qlearn_v1",
            lookback=6,
            episodes=60,
            learning_rate=0.18,
            discount_factor=0.92,
            epsilon=0.15,
            trade_penalty_bps=5,
            q_table={},
            evaluation=RLEvaluationMetrics(
                total_return_pct=8.5 if approved else -2.0,
                baseline_return_pct=3.0,
                excess_return_pct=5.5 if approved else -5.0,
                max_drawdown_pct=-12.0,
                trades=10,
                win_rate=0.6,
                holdout_steps=20,
                approved=approved,
            ),
        )

        metrics = artifact.evaluation
        split_meta = RLSplitMetadata(
            train_ratio=0.7,
            train_size=35,
            test_size=15,
            train_start="2026-01-01",
            train_end="2026-01-25",
            test_start="2026-01-26",
            test_end="2026-02-19",
        )

        manager.record_results(run_id, artifact, metrics, split_meta)

        return run_id

    def test_list_runs_returns_all_runs(self) -> None:
        """list_runs가 모든 run을 반환한다."""
        self._create_sample_run("TEST1", "test_profile_a")
        self._create_sample_run("TEST2", "test_profile_b")

        manager = RLExperimentManager(self.artifacts_dir)
        runs = manager.list_runs()

        self.assertEqual(len(runs), 2)

    def test_list_runs_filters_by_profile(self) -> None:
        """list_runs가 profile_id로 필터링할 수 있다."""
        self._create_sample_run("TEST1", "test_profile_a")
        self._create_sample_run("TEST2", "test_profile_b")

        manager = RLExperimentManager(self.artifacts_dir)
        runs = manager.list_runs(profile_id="test_profile_a")

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].config.profile_id, "test_profile_a")

    def test_list_runs_filters_approved_only(self) -> None:
        """list_runs가 approved_only로 필터링할 수 있다."""
        self._create_sample_run("TEST1", "test_profile_a", approved=True)
        self._create_sample_run("TEST2", "test_profile_b", approved=False)

        manager = RLExperimentManager(self.artifacts_dir)
        runs = manager.list_runs(approved_only=True)

        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0].approved)


class TestRLExperimentManagerBuildIndex(unittest.TestCase):
    """인덱스 구축 테스트."""

    def setUp(self) -> None:
        """임시 디렉토리 및 프로파일 준비."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self.temp_dir.name)
        self._setup_profile()

    def tearDown(self) -> None:
        """임시 디렉토리 정리."""
        self.temp_dir.cleanup()

    def _setup_profile(self) -> None:
        """테스트용 프로파일 생성."""
        profiles_dir = self.artifacts_dir / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile = {
            "profile_id": "test_profile",
            "algorithm": "tabular_q_learning",
            "state_version": "qlearn_v1",
            "trainer_params": {"lookback": 6},
            "dataset": {},
            "evaluation": {},
        }
        (profiles_dir / "test_profile.json").write_text(json.dumps(profile), encoding="utf-8")

    def _create_sample_run(self, ticker: str, return_pct: float) -> str:
        """샘플 run을 생성."""
        manager = RLExperimentManager(self.artifacts_dir)

        dataset = RLDataset(
            ticker=ticker,
            closes=[100.0 + i for i in range(50)],
            timestamps=[f"2026-01-{i % 28 + 1:02d}" for i in range(50)],
        )
        trainer = MockTrainer()

        run_id = manager.create_run(ticker, "test_profile", trainer, dataset)

        artifact = RLPolicyArtifact(
            policy_id=f"rl_{ticker}_20260314T120000Z",
            ticker=ticker,
            created_at=datetime.now(timezone.utc).isoformat(),
            algorithm="tabular_q_learning",
            state_version="qlearn_v1",
            lookback=6,
            episodes=60,
            learning_rate=0.18,
            discount_factor=0.92,
            epsilon=0.15,
            trade_penalty_bps=5,
            q_table={},
            evaluation=RLEvaluationMetrics(
                total_return_pct=return_pct,
                baseline_return_pct=3.0,
                excess_return_pct=return_pct - 3.0,
                max_drawdown_pct=-12.0,
                trades=10,
                win_rate=0.6,
                holdout_steps=20,
                approved=return_pct >= 5.0,
            ),
        )

        metrics = artifact.evaluation
        split_meta = RLSplitMetadata(
            train_ratio=0.7,
            train_size=35,
            test_size=15,
            train_start="2026-01-01",
            train_end="2026-01-25",
            test_start="2026-01-26",
            test_end="2026-02-19",
        )

        manager.record_results(run_id, artifact, metrics, split_meta)

        return run_id

    def test_build_index_creates_index_file(self) -> None:
        """build_index가 index.json 파일을 생성한다."""
        self._create_sample_run("TEST", 8.5)

        manager = RLExperimentManager(self.artifacts_dir)
        index = manager.build_index()

        index_path = self.artifacts_dir / "experiments" / "index.json"
        self.assertTrue(index_path.exists())

    def test_build_index_includes_statistics(self) -> None:
        """build_index가 통계 정보를 포함한다."""
        self._create_sample_run("TEST1", 8.5)
        self._create_sample_run("TEST2", 3.0)

        manager = RLExperimentManager(self.artifacts_dir)
        index = manager.build_index()

        self.assertEqual(index["total_runs"], 2)
        self.assertEqual(index["approved_runs"], 1)

    def test_build_index_groups_by_ticker(self) -> None:
        """build_index가 종목별로 분류한다."""
        self._create_sample_run("TEST1", 8.5)
        self._create_sample_run("TEST2", 7.2)

        manager = RLExperimentManager(self.artifacts_dir)
        index = manager.build_index()

        self.assertIn("TEST1", index["runs_by_ticker"])
        self.assertIn("TEST2", index["runs_by_ticker"])


class TestRLExperimentManagerLinking(unittest.TestCase):
    """정책과 실험 양방향 링크 테스트."""

    def setUp(self) -> None:
        """임시 디렉토리 및 프로파일 준비."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self.temp_dir.name)
        self._setup_profile()

    def tearDown(self) -> None:
        """임시 디렉토리 정리."""
        self.temp_dir.cleanup()

    def _setup_profile(self) -> None:
        """테스트용 프로파일 생성."""
        profiles_dir = self.artifacts_dir / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile = {
            "profile_id": "test_profile",
            "algorithm": "tabular_q_learning",
            "state_version": "qlearn_v1",
            "trainer_params": {"lookback": 6},
            "dataset": {},
            "evaluation": {},
        }
        (profiles_dir / "test_profile.json").write_text(json.dumps(profile), encoding="utf-8")

    def test_link_to_policy_creates_link_file(self) -> None:
        """link_to_policy가 artifact_link.json을 생성한다."""
        manager = RLExperimentManager(self.artifacts_dir)

        dataset = RLDataset(
            ticker="TEST",
            closes=[100.0 + i for i in range(50)],
            timestamps=[f"2026-01-{i % 28 + 1:02d}" for i in range(50)],
        )
        trainer = MockTrainer()

        run_id = manager.create_run("TEST", "test_profile", trainer, dataset)
        manager.link_to_policy(run_id, "rl_TEST_20260314T120000Z")

        link_path = self.artifacts_dir / "experiments" / run_id / "artifact_link.json"
        self.assertTrue(link_path.exists())

        link = json.loads(link_path.read_text(encoding="utf-8"))
        self.assertEqual(link["policy_id"], "rl_TEST_20260314T120000Z")


class TestRLExperimentManagerDatasetHash(unittest.TestCase):
    """데이터셋 해시 계산 테스트."""

    def test_compute_dataset_hash_consistency(self) -> None:
        """동일한 데이터셋은 동일한 해시를 생성한다."""
        dataset1 = RLDataset(
            ticker="TEST",
            closes=[100.0, 101.0, 102.0, 103.0],
            timestamps=["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        )
        dataset2 = RLDataset(
            ticker="TEST",
            closes=[100.0, 101.0, 102.0, 103.0],
            timestamps=["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        )

        hash1 = RLExperimentManager._compute_dataset_hash(dataset1)
        hash2 = RLExperimentManager._compute_dataset_hash(dataset2)

        self.assertEqual(hash1, hash2)

    def test_compute_dataset_hash_different_for_different_data(self) -> None:
        """다른 데이터셋은 다른 해시를 생성한다."""
        dataset1 = RLDataset(
            ticker="TEST",
            closes=[100.0, 101.0, 102.0, 103.0],
            timestamps=["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        )
        dataset2 = RLDataset(
            ticker="TEST",
            closes=[100.0, 101.0, 102.0, 104.0],
            timestamps=["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        )

        hash1 = RLExperimentManager._compute_dataset_hash(dataset1)
        hash2 = RLExperimentManager._compute_dataset_hash(dataset2)

        self.assertNotEqual(hash1, hash2)

    def test_compute_dataset_hash_format(self) -> None:
        """해시는 12자 hex 문자열이다."""
        dataset = RLDataset(
            ticker="TEST",
            closes=[100.0, 101.0, 102.0, 103.0],
            timestamps=["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        )

        hash_str = RLExperimentManager._compute_dataset_hash(dataset)

        self.assertEqual(len(hash_str), 12)
        self.assertTrue(all(c in "0123456789abcdef" for c in hash_str))


class TestRLExperimentManagerRunIdFormat(unittest.TestCase):
    """run_id 생성 형식 테스트."""

    def test_generate_run_id_format(self) -> None:
        """run_id는 올바른 형식이다."""
        run_id = RLExperimentManager._generate_run_id("259960.KS", "qlearn_v1")

        parts = run_id.split("-")
        self.assertEqual(len(parts), 3)

        # 첫 번째: YYYYMMDD T HHMMSS Z
        timestamp = parts[0]
        self.assertTrue(timestamp[8] == "T")
        self.assertTrue(timestamp.endswith("Z"))

        # 두 번째: ticker
        self.assertEqual(parts[1], "259960.KS")

        # 세 번째: state_version
        self.assertEqual(parts[2], "qlearn_v1")

    def test_generate_run_id_uniqueness(self) -> None:
        """여러 번 생성하면 다른 run_id가 생성된다."""
        import time

        run_id1 = RLExperimentManager._generate_run_id("TEST", "qlearn_v1")
        time.sleep(0.01)  # 시간 차이 생성
        run_id2 = RLExperimentManager._generate_run_id("TEST", "qlearn_v1")

        # 타임스탐프가 다르면 다른 run_id
        self.assertNotEqual(run_id1, run_id2)


if __name__ == "__main__":
    unittest.main()
