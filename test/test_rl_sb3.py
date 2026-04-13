"""
test/test_rl_sb3.py — SB3 통합 Trainer 테스트

SB3Trainer의 생성, 학습, 평가, 추론, walk-forward 어댑터를 검증합니다.
DQN / A2C / PPO 3개 알고리즘 모두 동일한 인터페이스로 동작하는지 확인합니다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.rl_trading import RLDataset, RLEvaluationMetrics, RLPolicyArtifact

# SB3 의존: 설치 안 되어 있으면 전체 스킵
sb3 = pytest.importorskip("stable_baselines3", reason="stable-baselines3 required")

from src.agents.rl_trading_sb3 import SB3Trainer, SUPPORTED_ALGORITHMS


# ── Helpers ──────────────────────────────────────────────────────────────────


def _uptrend_closes(length: int = 120, start: float = 100.0) -> list[float]:
    """상승 추세 종가 데이터."""
    return [start + i * 0.5 for i in range(length)]


def _downtrend_closes(length: int = 120, start: float = 200.0) -> list[float]:
    return [start - i * 0.3 for i in range(length)]


def _make_dataset(closes: list[float] | None = None, ticker: str = "TEST") -> RLDataset:
    closes = closes or _uptrend_closes()
    timestamps = [f"t{i}" for i in range(len(closes))]
    return RLDataset(ticker=ticker, closes=closes, timestamps=timestamps)


def _make_trainer(algorithm: str = "dqn", **kwargs) -> SB3Trainer:
    """빠른 학습을 위해 최소 파라미터로 생성."""
    defaults = {
        "lookback": 20,
        "num_episodes": 2,
        "num_seeds": 1,
        "net_arch": [32],
        "learning_rate": 1e-3,
    }
    # DQN needs smaller buffer for short data
    if algorithm == "dqn":
        defaults["buffer_size"] = 500
        defaults["batch_size"] = 32
        defaults["target_update_interval"] = 50
        defaults["train_freq"] = 2
    # PPO needs n_steps that fit our data length
    elif algorithm == "ppo":
        defaults["n_steps_ppo"] = 64
        defaults["batch_size"] = 32
        defaults["n_epochs"] = 2
    # A2C needs small n_steps
    elif algorithm == "a2c":
        defaults["n_steps_a2c"] = 5

    defaults.update(kwargs)
    return SB3Trainer(algorithm=algorithm, **defaults)


# ── Construction Tests ───────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestSB3TrainerConstruction:
    """SB3Trainer 생성 테스트."""

    def test_create_dqn_trainer(self):
        trainer = SB3Trainer(algorithm="dqn")
        assert trainer.algorithm == "dqn"

    def test_create_a2c_trainer(self):
        trainer = SB3Trainer(algorithm="a2c")
        assert trainer.algorithm == "a2c"

    def test_create_ppo_trainer(self):
        trainer = SB3Trainer(algorithm="ppo")
        assert trainer.algorithm == "ppo"

    def test_unsupported_algorithm_raises(self):
        with pytest.raises(ValueError, match="Unsupported algorithm"):
            SB3Trainer(algorithm="sac")

    def test_supported_algorithms_constant(self):
        assert "dqn" in SUPPORTED_ALGORITHMS
        assert "a2c" in SUPPORTED_ALGORITHMS
        assert "ppo" in SUPPORTED_ALGORITHMS

    def test_default_params(self):
        trainer = SB3Trainer(algorithm="dqn")
        assert trainer.lookback == 20
        assert trainer.gamma == 0.95
        assert trainer.net_arch == [64, 64]

    def test_custom_params(self):
        trainer = SB3Trainer(
            algorithm="ppo",
            lookback=10,
            learning_rate=1e-3,
            net_arch=[128, 128],
        )
        assert trainer.lookback == 10
        assert trainer.learning_rate == 1e-3
        assert trainer.net_arch == [128, 128]


# ── Training Tests ───────────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.slow
class TestSB3Training:
    """SB3 학습 테스트 (실제 SB3 모델 학습)."""

    @pytest.mark.parametrize("algo", ["dqn", "a2c", "ppo"])
    def test_train_returns_artifact(self, algo):
        trainer = _make_trainer(algo)
        dataset = _make_dataset()
        artifact = trainer.train(dataset)

        assert isinstance(artifact, RLPolicyArtifact)
        assert artifact.algorithm == algo
        assert artifact.model_path is not None
        assert artifact.q_table is None  # SB3 doesn't use q_table
        assert artifact.ticker == "TEST"

    @pytest.mark.parametrize("algo", ["dqn", "a2c", "ppo"])
    def test_train_with_metadata(self, algo):
        trainer = _make_trainer(algo)
        dataset = _make_dataset()
        artifact, split = trainer.train_with_metadata(dataset, train_ratio=0.7)

        assert artifact.model_path is not None
        assert split.train_ratio == 0.7
        assert split.train_size > 0
        assert split.test_size > 0
        assert split.train_size + split.test_size == len(dataset.closes)

    def test_train_creates_model_file(self):
        trainer = _make_trainer("dqn")
        artifact = trainer.train(_make_dataset())

        # SB3 saves as .zip (may or may not have .zip extension in path)
        model_path = Path(artifact.model_path)
        assert model_path.exists() or Path(f"{artifact.model_path}.zip").exists()

    def test_train_short_data_raises(self):
        trainer = _make_trainer("dqn", lookback=20)
        short_data = _make_dataset([100.0] * 25)  # too short: lookback + 10 = 30
        with pytest.raises(ValueError, match="학습 길이"):
            trainer.train(short_data)

    def test_train_invalid_ratio_raises(self):
        trainer = _make_trainer("dqn")
        with pytest.raises(ValueError, match="train_ratio"):
            trainer.train_with_metadata(_make_dataset(), train_ratio=0.3)

    def test_multi_seed_training(self):
        trainer = _make_trainer("dqn", num_seeds=2)
        artifact = trainer.train(_make_dataset())
        # Should still produce a valid artifact (best of 2 seeds)
        assert artifact.model_path is not None

    def test_on_progress_callback(self):
        progress_values = []
        trainer = _make_trainer("dqn", num_seeds=2)
        trainer.train_with_metadata(
            _make_dataset(),
            on_progress=lambda p: progress_values.append(p),
        )
        assert len(progress_values) == 2
        assert progress_values[-1] == 80  # last seed = 80%

    def test_artifact_evaluation_populated(self):
        trainer = _make_trainer("dqn")
        artifact = trainer.train(_make_dataset())

        ev = artifact.evaluation
        assert isinstance(ev, RLEvaluationMetrics)
        assert ev.holdout_steps > 0
        assert isinstance(ev.total_return_pct, float)
        assert isinstance(ev.win_rate, float)

    def test_state_version_includes_algorithm(self):
        for algo in ["dqn", "a2c", "ppo"]:
            trainer = _make_trainer(algo)
            artifact = trainer.train(_make_dataset())
            assert algo in artifact.state_version


# ── Evaluation Tests ─────────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.slow
class TestSB3Evaluation:
    """SB3 모델 평가 테스트."""

    def test_evaluate_model_path_first(self):
        """evaluate(model_path, closes) 호출 패턴."""
        trainer = _make_trainer("dqn")
        artifact = trainer.train(_make_dataset())
        closes = _uptrend_closes(80)

        metrics = trainer.evaluate(artifact.model_path, closes)
        assert isinstance(metrics, RLEvaluationMetrics)
        assert metrics.holdout_steps > 0

    def test_evaluate_closes_first(self):
        """evaluate(closes, model_path) 호출 패턴 (어댑터 호환)."""
        trainer = _make_trainer("a2c")
        artifact = trainer.train(_make_dataset())
        closes = _uptrend_closes(80)

        metrics = trainer.evaluate(closes, artifact.model_path)
        assert isinstance(metrics, RLEvaluationMetrics)

    def test_evaluate_missing_args_raises(self):
        trainer = _make_trainer("dqn")
        with pytest.raises((ValueError, TypeError)):
            trainer.evaluate("nonexistent_path")

    def test_evaluate_invalid_type_raises(self):
        trainer = _make_trainer("dqn")
        with pytest.raises(TypeError):
            trainer.evaluate(12345, [100.0] * 50)


# ── Inference Tests ──────────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.slow
class TestSB3Inference:
    """SB3 추론 테스트."""

    @pytest.mark.parametrize("algo", ["dqn", "a2c", "ppo"])
    def test_infer_action_returns_tuple(self, algo):
        trainer = _make_trainer(algo)
        artifact = trainer.train(_make_dataset())
        closes = _uptrend_closes(60)

        action, confidence, info_str, action_values = trainer.infer_action(
            artifact, closes, current_position=0
        )

        assert action in ("BUY", "SELL", "HOLD", "CLOSE")
        assert 0.0 < confidence <= 1.0
        assert algo in info_str
        assert isinstance(action_values, dict)
        assert len(action_values) == 4  # BUY, SELL, HOLD, CLOSE

    def test_infer_action_confidence_range(self):
        trainer = _make_trainer("dqn")
        artifact = trainer.train(_make_dataset())

        _, confidence, _, _ = trainer.infer_action(
            artifact, _uptrend_closes(60), current_position=0
        )
        assert 0.34 <= confidence <= 0.98

    def test_infer_action_no_model_path_raises(self):
        trainer = _make_trainer("dqn")
        artifact = RLPolicyArtifact(
            policy_id="test",
            ticker="TEST",
            created_at="2026-01-01",
            algorithm="dqn",
            state_version="sb3_dqn",
            lookback=20,
            episodes=2,
            learning_rate=1e-3,
            discount_factor=0.95,
            epsilon=0.05,
            trade_penalty_bps=2,
            evaluation=RLEvaluationMetrics(
                total_return_pct=0, baseline_return_pct=0,
                excess_return_pct=0, max_drawdown_pct=0,
                trades=0, win_rate=0, holdout_steps=0, approved=False,
            ),
            q_table=None,
            model_path=None,
        )
        with pytest.raises(ValueError, match="model_path"):
            trainer.infer_action(artifact, _uptrend_closes(60))

    def test_infer_action_position_override(self):
        """current_position이 obs에 반영되는지 확인."""
        trainer = _make_trainer("dqn")
        artifact = trainer.train(_make_dataset())

        # Different positions should potentially give different results
        # (at minimum, the function should not crash)
        for pos in [0, 1, -1]:
            action, conf, _, _ = trainer.infer_action(
                artifact, _uptrend_closes(60), current_position=pos
            )
            assert action in ("BUY", "SELL", "HOLD", "CLOSE")


# ── Model Management Tests ──────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.slow
class TestSB3ModelManagement:
    """모델 저장/로드/정리 테스트."""

    def test_load_saved_model(self):
        trainer = _make_trainer("dqn")
        artifact = trainer.train(_make_dataset())

        # Load should succeed
        model = trainer._load_model(artifact.model_path)
        assert model is not None

    def test_load_nonexistent_raises(self):
        trainer = _make_trainer("dqn")
        with pytest.raises(FileNotFoundError):
            trainer._load_model("/nonexistent/model_path")

    def test_cleanup_model(self):
        trainer = _make_trainer("dqn")
        artifact = trainer.train(_make_dataset())
        model_path = artifact.model_path

        # Verify file exists
        assert Path(model_path).exists() or Path(f"{model_path}.zip").exists()

        # Cleanup
        SB3Trainer._cleanup_model(model_path)

        # Verify file removed
        assert not Path(model_path).exists()
        assert not Path(f"{model_path}.zip").exists()

    def test_algo_class_dqn(self):
        trainer = _make_trainer("dqn")
        cls = trainer._get_algo_class()
        assert cls.__name__ == "DQN"

    def test_algo_class_a2c(self):
        trainer = _make_trainer("a2c")
        cls = trainer._get_algo_class()
        assert cls.__name__ == "A2C"

    def test_algo_class_ppo(self):
        trainer = _make_trainer("ppo")
        cls = trainer._get_algo_class()
        assert cls.__name__ == "PPO"


# ── Build Model Kwargs Tests ────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestBuildModelKwargs:
    """알고리즘별 kwargs 생성 테스트."""

    def test_dqn_kwargs(self):
        trainer = _make_trainer("dqn", buffer_size=5000, batch_size=64)
        kwargs = trainer._build_model_kwargs(seed=42)
        assert kwargs["buffer_size"] == 5000
        assert kwargs["batch_size"] == 64
        assert "exploration_fraction" in kwargs
        assert "target_update_interval" in kwargs

    def test_a2c_kwargs(self):
        trainer = _make_trainer("a2c", n_steps_a2c=10, ent_coef_a2c=0.02)
        kwargs = trainer._build_model_kwargs(seed=42)
        assert kwargs["n_steps"] == 10
        assert kwargs["ent_coef"] == 0.02
        assert kwargs["vf_coef"] == 0.5
        assert "buffer_size" not in kwargs

    def test_ppo_kwargs(self):
        trainer = _make_trainer("ppo", n_steps_ppo=128, n_epochs=5, clip_range=0.1)
        kwargs = trainer._build_model_kwargs(seed=42)
        assert kwargs["n_steps"] == 128
        assert kwargs["n_epochs"] == 5
        assert kwargs["clip_range"] == 0.1
        assert kwargs["gae_lambda"] == 0.95


# ── Walk-Forward Adapter Tests ──────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.slow
class TestWalkForwardSB3Adapter:
    """Walk-Forward SB3 어댑터 호환성 테스트."""

    def test_walk_forward_with_sb3_trainer(self):
        """WalkForwardEvaluator가 SB3 adapter를 통해 동작하는지 확인."""
        from src.agents.rl_walk_forward import WalkForwardEvaluator

        trainer = _make_trainer("dqn")
        closes = _uptrend_closes(200)

        class SB3WFAdapter:
            """Walk-forward용 SB3 어댑터 (실제 _WalkForwardSB3Adapter 로직 재현)."""
            def __init__(self, sb3_trainer: SB3Trainer):
                self._trainer = sb3_trainer

            def train(self, closes: list[float]) -> str:
                dataset = RLDataset(
                    ticker="WF_TEST",
                    closes=closes,
                    timestamps=[str(i) for i in range(len(closes))],
                )
                artifact = self._trainer.train(dataset)
                return artifact.model_path

            def evaluate(self, model_path: str, closes: list[float]) -> RLEvaluationMetrics:
                return self._trainer.evaluate(model_path, closes)

        adapter = SB3WFAdapter(trainer)
        evaluator = WalkForwardEvaluator(n_folds=2)
        result = evaluator.evaluate(closes, adapter)

        assert result.n_folds >= 1
        assert len(result.folds) >= 1
        assert isinstance(result.avg_return_pct, float)

    def test_extract_q_table_string_passthrough(self):
        """WalkForward._extract_q_table()가 model_path (str)를 통과시키는지."""
        from src.agents.rl_walk_forward import WalkForwardEvaluator

        result = WalkForwardEvaluator._extract_q_table("/tmp/model.zip")
        assert result == "/tmp/model.zip"


# ── Confidence Computation Tests ─────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.slow
class TestConfidenceComputation:
    """알고리즘별 confidence 계산 검증."""

    def test_dqn_confidence_uses_q_values(self):
        trainer = _make_trainer("dqn")
        artifact = trainer.train(_make_dataset())
        _, confidence, _, values = trainer.infer_action(
            artifact, _uptrend_closes(60), current_position=0
        )
        # DQN action_values should be Q-values (can be any float)
        assert all(isinstance(v, float) for v in values.values())

    def test_a2c_confidence_uses_probabilities(self):
        trainer = _make_trainer("a2c")
        artifact = trainer.train(_make_dataset())
        _, confidence, _, values = trainer.infer_action(
            artifact, _uptrend_closes(60), current_position=0
        )
        # A2C action_values should be probabilities summing to ~1.0
        total_prob = sum(values.values())
        assert total_prob == pytest.approx(1.0, abs=0.01)

    def test_ppo_confidence_uses_probabilities(self):
        trainer = _make_trainer("ppo")
        artifact = trainer.train(_make_dataset())
        _, confidence, _, values = trainer.infer_action(
            artifact, _uptrend_closes(60), current_position=0
        )
        total_prob = sum(values.values())
        assert total_prob == pytest.approx(1.0, abs=0.01)


# ── Integration: Runner Dispatch Tests ───────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestRunnerSB3Dispatch:
    """RLRunner가 SB3 알고리즘을 올바르게 디스패치하는지."""

    def test_runner_map_action(self):
        from src.agents.rl_runner import RLRunner

        assert RLRunner._map_action_to_signal("BUY") == "BUY"
        assert RLRunner._map_action_to_signal("SELL") == "SELL"
        assert RLRunner._map_action_to_signal("HOLD") == "HOLD"
        assert RLRunner._map_action_to_signal("CLOSE") == "HOLD"

    def test_runner_infer_sb3_method_exists(self):
        from src.agents.rl_runner import RLRunner

        runner = RLRunner.__new__(RLRunner)
        assert hasattr(runner, "_infer_sb3")


# ── Profile Loading Tests ────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestSB3Profiles:
    """SB3 프로파일 JSON 파일 검증."""

    @pytest.mark.parametrize(
        "profile_name",
        ["dqn_v1_baseline.json", "a2c_v1_baseline.json", "ppo_v1_baseline.json"],
    )
    def test_profile_exists_and_valid(self, profile_name):
        import json

        profile_path = (
            Path(__file__).resolve().parents[1]
            / "artifacts"
            / "rl"
            / "profiles"
            / profile_name
        )
        assert profile_path.exists(), f"Profile not found: {profile_path}"

        with open(profile_path) as f:
            profile = json.load(f)

        assert "algorithm" in profile
        assert profile["algorithm"] in SUPPORTED_ALGORITHMS
        # trainer_params 안에 learning_rate가 있음
        params = profile.get("trainer_params", profile)
        assert "learning_rate" in params

    def test_dqn_profile_has_dqn_params(self):
        import json

        path = (
            Path(__file__).resolve().parents[1]
            / "artifacts"
            / "rl"
            / "profiles"
            / "dqn_v1_baseline.json"
        )
        with open(path) as f:
            p = json.load(f)
        assert p["algorithm"] == "dqn"
        params = p.get("trainer_params", p)
        assert "buffer_size" in params
        assert "batch_size" in params

    def test_ppo_profile_has_ppo_params(self):
        import json

        path = (
            Path(__file__).resolve().parents[1]
            / "artifacts"
            / "rl"
            / "profiles"
            / "ppo_v1_baseline.json"
        )
        with open(path) as f:
            p = json.load(f)
        assert p["algorithm"] == "ppo"
        params = p.get("trainer_params", p)
        assert "n_steps_ppo" in params
        assert "clip_range" in params


# ── Edge Cases ───────────────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.slow
class TestSB3EdgeCases:
    """SB3 에지 케이스 테스트."""

    def test_downtrend_data(self):
        """하락 추세에서도 학습/추론이 크래시 없이 동작."""
        trainer = _make_trainer("dqn")
        artifact = trainer.train(_make_dataset(_downtrend_closes()))
        action, conf, _, _ = trainer.infer_action(
            artifact, _downtrend_closes(60), current_position=0
        )
        assert action in ("BUY", "SELL", "HOLD", "CLOSE")

    def test_flat_data(self):
        """횡보 데이터에서 동작."""
        flat = [100.0 + (i % 3) * 0.01 for i in range(120)]
        trainer = _make_trainer("a2c")
        artifact = trainer.train(_make_dataset(flat))
        assert artifact.model_path is not None

    def test_minimal_length_data(self):
        """최소 길이 데이터로 학습 가능."""
        # lookback=20, need at least lookback+10+1 = 31
        closes = _uptrend_closes(35)
        trainer = _make_trainer("dqn", lookback=20)
        artifact = trainer.train(_make_dataset(closes))
        assert artifact is not None

    def test_different_tickers_different_seeds(self):
        """다른 티커는 다른 시드 기반값을 사용 (재현성 분리)."""
        trainer = _make_trainer("dqn", num_seeds=1)
        a1 = trainer.train(_make_dataset(ticker="AAAA"))
        a2 = trainer.train(_make_dataset(ticker="BBBB"))
        # Both should succeed, potentially different results
        assert a1.policy_id != a2.policy_id
