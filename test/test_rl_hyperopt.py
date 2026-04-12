"""
test/test_rl_hyperopt.py — Optuna RL 하이퍼파라미터 탐색 단위 테스트

search space, suggest_params, RLHyperOptimizer를 검증합니다.
SB3 의존성은 mock으로 격리.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.agents.rl_hyperopt import (
    DEFAULT_HYPEROPT_DIR,
    SEARCH_SPACES,
    RLHyperOptimizer,
    get_search_space,
    suggest_params,
)
from src.agents.rl_trading import RLDataset


# ── Helpers ──────────────────────────────────────────────────────────

def _make_dataset(n: int = 100, ticker: str = "005930.KS") -> RLDataset:
    return RLDataset(
        ticker=ticker,
        closes=[100.0 + i * 0.5 for i in range(n)],
        timestamps=[str(i) for i in range(n)],
    )


class _FakeTrial:
    """Optuna Trial을 흉내내는 최소 구현."""

    def __init__(self, params: dict | None = None):
        self._params = params or {}
        self._suggested: dict = {}
        self.number = 0

    def suggest_float(self, name: str, low: float, high: float, *, log: bool = False) -> float:
        val = self._params.get(name, (low + high) / 2)
        self._suggested[name] = val
        return val

    def suggest_int(self, name: str, low: int, high: int, step: int = 1) -> int:
        val = self._params.get(name, (low + high) // 2)
        self._suggested[name] = val
        return val

    def suggest_categorical(self, name: str, choices: list) -> Any:
        val = self._params.get(name, choices[0])
        self._suggested[name] = val
        return val


from typing import Any


# ── get_search_space Tests ──────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestGetSearchSpace:
    def test_dqn_space_has_10_params(self):
        space = get_search_space("dqn")
        assert len(space) == 10

    def test_a2c_space_has_6_params(self):
        space = get_search_space("a2c")
        assert len(space) == 6

    def test_ppo_space_has_9_params(self):
        space = get_search_space("ppo")
        assert len(space) == 9

    def test_case_insensitive(self):
        assert get_search_space("DQN") == get_search_space("dqn")

    def test_unsupported_algorithm_raises(self):
        with pytest.raises(ValueError, match="Unsupported algorithm"):
            get_search_space("sac")

    def test_all_spaces_have_learning_rate(self):
        for algo in ("dqn", "a2c", "ppo"):
            space = get_search_space(algo)
            assert "learning_rate" in space

    def test_all_spaces_have_net_arch(self):
        for algo in ("dqn", "a2c", "ppo"):
            space = get_search_space(algo)
            assert "net_arch" in space


# ── suggest_params Tests ────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestSuggestParams:
    def test_dqn_returns_all_params(self):
        trial = _FakeTrial({"net_arch_idx": 0})
        params = suggest_params(trial, "dqn")
        expected_keys = {
            "learning_rate", "buffer_size", "batch_size", "gamma",
            "exploration_fraction", "exploration_final_eps",
            "target_update_interval", "net_arch", "train_freq", "gradient_steps",
        }
        assert set(params.keys()) == expected_keys

    def test_a2c_returns_all_params(self):
        trial = _FakeTrial({"net_arch_idx": 0})
        params = suggest_params(trial, "a2c")
        expected_keys = {
            "learning_rate", "gamma", "n_steps_a2c", "ent_coef_a2c",
            "vf_coef", "net_arch",
        }
        assert set(params.keys()) == expected_keys

    def test_ppo_returns_all_params(self):
        trial = _FakeTrial({"net_arch_idx": 0})
        params = suggest_params(trial, "ppo")
        expected_keys = {
            "learning_rate", "gamma", "n_steps_ppo", "n_epochs",
            "batch_size", "clip_range", "ent_coef_ppo", "gae_lambda", "net_arch",
        }
        assert set(params.keys()) == expected_keys

    def test_net_arch_resolved_from_index(self):
        trial = _FakeTrial({"net_arch_idx": 1})
        params = suggest_params(trial, "dqn")
        assert params["net_arch"] == [128, 64]

    def test_learning_rate_is_float(self):
        trial = _FakeTrial()
        params = suggest_params(trial, "dqn")
        assert isinstance(params["learning_rate"], float)

    def test_batch_size_is_valid_choice(self):
        trial = _FakeTrial()
        params = suggest_params(trial, "dqn")
        assert params["batch_size"] in [32, 64, 128]


# ── RLHyperOptimizer Construction Tests ─────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestRLHyperOptimizerConstruction:
    def test_valid_algorithm(self):
        ds = _make_dataset()
        opt = RLHyperOptimizer(algorithm="dqn", dataset=ds)
        assert opt.algorithm == "dqn"

    def test_unsupported_algorithm_raises(self):
        ds = _make_dataset()
        with pytest.raises(ValueError, match="Unsupported"):
            RLHyperOptimizer(algorithm="sac", dataset=ds)

    def test_default_hyperopt_dir(self):
        ds = _make_dataset()
        opt = RLHyperOptimizer(algorithm="dqn", dataset=ds)
        assert opt.hyperopt_dir == DEFAULT_HYPEROPT_DIR

    def test_custom_hyperopt_dir(self, tmp_path):
        ds = _make_dataset()
        opt = RLHyperOptimizer(algorithm="dqn", dataset=ds, hyperopt_dir=tmp_path)
        assert opt.hyperopt_dir == tmp_path

    def test_base_params_stored(self):
        ds = _make_dataset()
        opt = RLHyperOptimizer(
            algorithm="dqn", dataset=ds,
            base_params={"lookback": 30},
        )
        assert opt.base_params["lookback"] == 30


# ── RLHyperOptimizer.optimize Tests (mocked SB3) ───────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestRLHyperOptimizerOptimize:
    def test_optimize_returns_best_params(self, tmp_path):
        """3 trial 소규모 탐색 → best_params dict 반환."""
        ds = _make_dataset()
        opt = RLHyperOptimizer(
            algorithm="dqn",
            dataset=ds,
            hyperopt_dir=tmp_path,
            base_params={"lookback": 20, "trade_penalty_bps": 2},
        )

        # Mock SB3Trainer to avoid actual training
        mock_artifact = MagicMock()
        mock_artifact.evaluation.excess_return_pct = 5.0
        mock_split = MagicMock()

        with patch("src.agents.rl_trading_sb3.SB3Trainer") as MockTrainer:
            mock_instance = MagicMock()
            mock_instance.train_with_metadata.return_value = (mock_artifact, mock_split)
            MockTrainer.return_value = mock_instance

            best_params = opt.optimize(n_trials=3)

        assert isinstance(best_params, dict)
        assert "learning_rate" in best_params
        assert "net_arch" in best_params
        # net_arch should be a list, not an index
        assert isinstance(best_params["net_arch"], list)

    def test_optimize_saves_best_params_json(self, tmp_path):
        """best_params JSON 파일이 저장된다."""
        ds = _make_dataset()
        opt = RLHyperOptimizer(
            algorithm="dqn",
            dataset=ds,
            hyperopt_dir=tmp_path,
        )

        mock_artifact = MagicMock()
        mock_artifact.evaluation.excess_return_pct = 3.0

        with patch("src.agents.rl_trading_sb3.SB3Trainer") as MockTrainer:
            mock_instance = MagicMock()
            mock_instance.train_with_metadata.return_value = (mock_artifact, MagicMock())
            MockTrainer.return_value = mock_instance

            opt.optimize(n_trials=2)

        params_file = tmp_path / "005930.KS_dqn_best_params.json"
        assert params_file.exists()
        data = json.loads(params_file.read_text())
        assert data["algorithm"] == "dqn"
        assert data["ticker"] == "005930.KS"
        assert "best_params" in data

    def test_optimize_saves_summary_json(self, tmp_path):
        """study summary JSON 파일이 저장된다."""
        ds = _make_dataset()
        opt = RLHyperOptimizer(
            algorithm="a2c",
            dataset=ds,
            hyperopt_dir=tmp_path,
        )

        mock_artifact = MagicMock()
        mock_artifact.evaluation.excess_return_pct = 2.0

        with patch("src.agents.rl_trading_sb3.SB3Trainer") as MockTrainer:
            mock_instance = MagicMock()
            mock_instance.train_with_metadata.return_value = (mock_artifact, MagicMock())
            MockTrainer.return_value = mock_instance

            opt.optimize(n_trials=2)

        summary_file = tmp_path / "005930.KS_a2c_summary.json"
        assert summary_file.exists()
        data = json.loads(summary_file.read_text())
        assert data["total_trials"] == 2

    def test_optimize_callback_called(self, tmp_path):
        """on_trial_complete 콜백이 trial마다 호출된다."""
        ds = _make_dataset()
        opt = RLHyperOptimizer(
            algorithm="ppo",
            dataset=ds,
            hyperopt_dir=tmp_path,
        )

        mock_artifact = MagicMock()
        mock_artifact.evaluation.excess_return_pct = 1.0

        with patch("src.agents.rl_trading_sb3.SB3Trainer") as MockTrainer:
            mock_instance = MagicMock()
            mock_instance.train_with_metadata.return_value = (mock_artifact, MagicMock())
            MockTrainer.return_value = mock_instance

            callback_calls = []
            opt.optimize(
                n_trials=3,
                on_trial_complete=lambda num, total, val: callback_calls.append((num, total, val)),
            )

        assert len(callback_calls) == 3
        assert all(total == 3 for _, total, _ in callback_calls)

    def test_optimize_handles_failed_trials(self, tmp_path):
        """학습 실패 trial은 -inf로 처리되고 탐색은 계속된다."""
        ds = _make_dataset()
        opt = RLHyperOptimizer(
            algorithm="dqn",
            dataset=ds,
            hyperopt_dir=tmp_path,
        )

        call_count = 0

        def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")
            mock_artifact = MagicMock()
            mock_artifact.evaluation.excess_return_pct = 4.0
            return mock_artifact, MagicMock()

        with patch("src.agents.rl_trading_sb3.SB3Trainer") as MockTrainer:
            mock_instance = MagicMock()
            mock_instance.train_with_metadata.side_effect = _side_effect
            MockTrainer.return_value = mock_instance

            best_params = opt.optimize(n_trials=3)

        # Should still return valid params despite 1 failure
        assert isinstance(best_params, dict)

    def test_optimize_with_timeout(self, tmp_path):
        """timeout 파라미터가 전달된다."""
        ds = _make_dataset()
        opt = RLHyperOptimizer(
            algorithm="dqn",
            dataset=ds,
            hyperopt_dir=tmp_path,
        )

        mock_artifact = MagicMock()
        mock_artifact.evaluation.excess_return_pct = 1.0

        with patch("src.agents.rl_trading_sb3.SB3Trainer") as MockTrainer:
            mock_instance = MagicMock()
            mock_instance.train_with_metadata.return_value = (mock_artifact, MagicMock())
            MockTrainer.return_value = mock_instance

            # timeout=1 should stop quickly
            best_params = opt.optimize(n_trials=100, timeout=1)

        assert isinstance(best_params, dict)


# ── RLHyperOptimizer._objective Tests ───────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestObjective:
    def test_objective_uses_quick_training(self, tmp_path):
        """objective는 1 seed, 절반 에피소드로 간이 학습한다."""
        ds = _make_dataset()
        opt = RLHyperOptimizer(
            algorithm="dqn",
            dataset=ds,
            hyperopt_dir=tmp_path,
            base_params={"num_episodes": 10, "lookback": 20},
        )

        mock_artifact = MagicMock()
        mock_artifact.evaluation.excess_return_pct = 7.5

        with patch("src.agents.rl_trading_sb3.SB3Trainer") as MockTrainer:
            mock_instance = MagicMock()
            mock_instance.train_with_metadata.return_value = (mock_artifact, MagicMock())
            MockTrainer.return_value = mock_instance

            trial = _FakeTrial({"net_arch_idx": 0})
            result = opt._objective(trial)

        # Check SB3Trainer was called with num_seeds=1
        init_kwargs = MockTrainer.call_args[1]
        assert init_kwargs["num_seeds"] == 1
        assert init_kwargs["num_episodes"] == 5  # 10 // 2
        assert result == 7.5

    def test_objective_returns_neg_inf_on_error(self, tmp_path):
        ds = _make_dataset()
        opt = RLHyperOptimizer(
            algorithm="dqn",
            dataset=ds,
            hyperopt_dir=tmp_path,
        )

        with patch("src.agents.rl_trading_sb3.SB3Trainer") as MockTrainer:
            MockTrainer.side_effect = RuntimeError("init failed")

            trial = _FakeTrial({"net_arch_idx": 0})
            result = opt._objective(trial)

        assert result == float("-inf")


# ── ContinuousImprover Hyperopt Integration Tests ──────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestContinuousImproverHyperopt:
    """ContinuousImprover._run_hyperopt_then_build_trainer 연동 테스트."""

    def test_run_hyperopt_returns_trainer(self):
        """hyperopt 실행 후 SB3Trainer를 반환한다."""
        from src.agents.rl_continuous_improver import RLContinuousImprover

        improver = RLContinuousImprover.__new__(RLContinuousImprover)
        ds = _make_dataset()
        profile = {
            "algorithm": "dqn",
            "trainer_params": {
                "algorithm": "dqn",
                "lookback": 20,
                "trade_penalty_bps": 2,
            },
        }

        best_params = {"learning_rate": 0.001, "net_arch": [64, 64]}

        with patch("src.agents.rl_hyperopt.RLHyperOptimizer") as MockOpt:
            mock_opt_instance = MagicMock()
            mock_opt_instance.optimize.return_value = best_params
            MockOpt.return_value = mock_opt_instance

            with patch("src.agents.rl_trading_sb3.SB3Trainer") as MockTrainer:
                mock_trainer = MagicMock()
                MockTrainer.return_value = mock_trainer

                result = improver._run_hyperopt_then_build_trainer(
                    profile=profile,
                    dataset=ds,
                    train_ratio=0.7,
                    n_trials=5,
                    timeout=None,
                )

        MockOpt.assert_called_once()
        mock_opt_instance.optimize.assert_called_once_with(n_trials=5, timeout=None)
        assert result is mock_trainer
