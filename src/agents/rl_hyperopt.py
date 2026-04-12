"""
src/agents/rl_hyperopt.py — Optuna 기반 RL 하이퍼파라미터 자동 탐색

SB3 알고리즘(DQN/A2C/PPO)의 하이퍼파라미터를 Optuna TPE sampler로 탐색한다.
각 trial은 1-seed 간이 학습 후 holdout excess_return_pct로 평가.
best_params는 JSON 파일로 저장하고, SB3Trainer에 직접 전달 가능하다.

Optuna/torch는 lazy import로 서버 시작 시간에 영향을 주지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.agents.rl_trading import RLDataset
from src.utils.logging import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HYPEROPT_DIR = ROOT / "artifacts" / "rl" / "hyperopt"

# Algorithm-specific search spaces
_DQN_SPACE: dict[str, dict[str, Any]] = {
    "learning_rate": {"type": "log_float", "low": 1e-4, "high": 1e-2},
    "buffer_size": {"type": "int", "low": 5000, "high": 50000, "step": 5000},
    "batch_size": {"type": "categorical", "choices": [32, 64, 128]},
    "gamma": {"type": "float", "low": 0.90, "high": 0.99},
    "exploration_fraction": {"type": "float", "low": 0.1, "high": 0.4},
    "exploration_final_eps": {"type": "float", "low": 0.01, "high": 0.10},
    "target_update_interval": {"type": "int", "low": 100, "high": 1000, "step": 100},
    "net_arch": {"type": "categorical", "choices": [[64, 64], [128, 64], [64, 32]]},
    "train_freq": {"type": "categorical", "choices": [1, 2, 4]},
    "gradient_steps": {"type": "categorical", "choices": [1, 2, 4]},
}

_A2C_SPACE: dict[str, dict[str, Any]] = {
    "learning_rate": {"type": "log_float", "low": 1e-4, "high": 1e-2},
    "gamma": {"type": "float", "low": 0.90, "high": 0.99},
    "n_steps_a2c": {"type": "categorical", "choices": [5, 10, 20]},
    "ent_coef_a2c": {"type": "log_float", "low": 1e-4, "high": 0.1},
    "vf_coef": {"type": "float", "low": 0.25, "high": 1.0},
    "net_arch": {"type": "categorical", "choices": [[64, 64], [128, 64], [64, 32]]},
}

_PPO_SPACE: dict[str, dict[str, Any]] = {
    "learning_rate": {"type": "log_float", "low": 1e-4, "high": 1e-2},
    "gamma": {"type": "float", "low": 0.90, "high": 0.99},
    "n_steps_ppo": {"type": "categorical", "choices": [256, 512, 1024, 2048]},
    "n_epochs": {"type": "int", "low": 3, "high": 15},
    "batch_size": {"type": "categorical", "choices": [32, 64, 128]},
    "clip_range": {"type": "float", "low": 0.1, "high": 0.3},
    "ent_coef_ppo": {"type": "log_float", "low": 1e-4, "high": 0.1},
    "gae_lambda": {"type": "float", "low": 0.9, "high": 0.99},
    "net_arch": {"type": "categorical", "choices": [[64, 64], [128, 64], [64, 32]]},
}

SEARCH_SPACES: dict[str, dict[str, dict[str, Any]]] = {
    "dqn": _DQN_SPACE,
    "a2c": _A2C_SPACE,
    "ppo": _PPO_SPACE,
}


def get_search_space(algorithm: str) -> dict[str, dict[str, Any]]:
    """알고리즘별 search space를 반환한다."""
    algo = algorithm.lower()
    if algo not in SEARCH_SPACES:
        raise ValueError(f"Unsupported algorithm: {algorithm}. Use one of {list(SEARCH_SPACES)}")
    return SEARCH_SPACES[algo]


def suggest_params(trial: Any, algorithm: str) -> dict[str, Any]:
    """Optuna trial에서 알고리즘별 파라미터를 suggest한다."""
    space = get_search_space(algorithm)
    params: dict[str, Any] = {}

    for name, spec in space.items():
        ptype = spec["type"]
        if ptype == "log_float":
            params[name] = trial.suggest_float(name, spec["low"], spec["high"], log=True)
        elif ptype == "float":
            params[name] = trial.suggest_float(name, spec["low"], spec["high"])
        elif ptype == "int":
            params[name] = trial.suggest_int(name, spec["low"], spec["high"], step=spec.get("step", 1))
        elif ptype == "categorical":
            # Optuna doesn't support list choices directly — use index for net_arch
            choices = spec["choices"]
            if name == "net_arch":
                idx = trial.suggest_categorical("net_arch_idx", list(range(len(choices))))
                params[name] = choices[idx]
            else:
                params[name] = trial.suggest_categorical(name, choices)

    return params


class RLHyperOptimizer:
    """Optuna TPE 기반 RL 하이퍼파라미터 자동 탐색기.

    Usage:
        optimizer = RLHyperOptimizer(
            algorithm="dqn",
            dataset=dataset,
            base_params={"lookback": 20, "trade_penalty_bps": 2},
        )
        best_params = optimizer.optimize(n_trials=50)
        # best_params를 SB3Trainer에 직접 전달 가능
    """

    def __init__(
        self,
        *,
        algorithm: str,
        dataset: RLDataset,
        base_params: dict[str, Any] | None = None,
        hyperopt_dir: Path | None = None,
        train_ratio: float = 0.7,
    ) -> None:
        self.algorithm = algorithm.lower()
        self.dataset = dataset
        self.base_params = base_params or {}
        self.hyperopt_dir = Path(hyperopt_dir or DEFAULT_HYPEROPT_DIR)
        self.train_ratio = train_ratio

        if self.algorithm not in SEARCH_SPACES:
            raise ValueError(
                f"Unsupported algorithm: {algorithm}. Use one of {list(SEARCH_SPACES)}"
            )

    def optimize(
        self,
        n_trials: int = 50,
        *,
        timeout: int | None = None,
        on_trial_complete: Callable[[int, int, float], None] | None = None,
    ) -> dict[str, Any]:
        """Optuna 탐색을 실행하고 best_params를 반환한다.

        Args:
            n_trials: 탐색 trial 수
            timeout: 탐색 제한 시간 (초). None이면 무제한.
            on_trial_complete: (trial_number, n_trials, value) 콜백

        Returns:
            best_params dict (SB3Trainer에 직접 전달 가능)
        """
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        self.hyperopt_dir.mkdir(parents=True, exist_ok=True)
        study_name = f"{self.dataset.ticker}_{self.algorithm}"
        storage_path = self.hyperopt_dir / f"{study_name}.db"
        storage = f"sqlite:///{storage_path}"

        study = optuna.create_study(
            study_name=study_name,
            storage=storage,
            direction="maximize",
            load_if_exists=True,
            sampler=optuna.samplers.TPESampler(seed=42),
            pruner=optuna.pruners.MedianPruner(
                n_startup_trials=5,
                n_warmup_steps=0,
            ),
        )

        def objective(trial: optuna.Trial) -> float:
            return self._objective(trial)

        # Wrap callback
        callbacks = []
        if on_trial_complete is not None:
            def _on_complete(study: Any, trial: Any) -> None:
                on_trial_complete(trial.number + 1, n_trials, trial.value or 0.0)
            callbacks.append(_on_complete)

        study.optimize(
            objective,
            n_trials=n_trials,
            timeout=timeout,
            callbacks=callbacks,
            show_progress_bar=False,
        )

        # Extract best params
        best_params = self._extract_best_params(study)

        # Save results
        self._save_results(study_name, best_params, study)

        logger.info(
            "Optuna 탐색 완료 [%s][%s]: %d trials, best=%.2f%%, params=%s",
            self.dataset.ticker,
            self.algorithm,
            len(study.trials),
            study.best_value,
            {k: round(v, 4) if isinstance(v, float) else v for k, v in best_params.items()},
        )

        return best_params

    def _objective(self, trial: Any) -> float:
        """단일 trial: suggest → 간이 학습(1 seed) → holdout excess_return 반환."""
        from src.agents.rl_trading_sb3 import SB3Trainer

        suggested = suggest_params(trial, self.algorithm)

        # Merge base_params with suggested (suggested overrides)
        trainer_kwargs = {**self.base_params, "algorithm": self.algorithm}
        trainer_kwargs.update(suggested)

        # Quick training: 1 seed, fewer episodes
        trainer_kwargs["num_seeds"] = 1
        original_episodes = trainer_kwargs.get("num_episodes", 10)
        trainer_kwargs["num_episodes"] = max(3, original_episodes // 2)

        try:
            trainer = SB3Trainer(**trainer_kwargs)
            artifact, _ = trainer.train_with_metadata(
                self.dataset,
                train_ratio=self.train_ratio,
            )
            return artifact.evaluation.excess_return_pct
        except Exception as exc:
            logger.debug("Trial %d failed: %s", trial.number, exc)
            return float("-inf")

    def _extract_best_params(self, study: Any) -> dict[str, Any]:
        """Study에서 best_params를 추출하고 net_arch를 복원한다."""
        best = dict(study.best_params)

        # net_arch_idx → net_arch 복원
        if "net_arch_idx" in best:
            space = get_search_space(self.algorithm)
            choices = space["net_arch"]["choices"]
            best["net_arch"] = choices[best.pop("net_arch_idx")]

        return best

    def _save_results(
        self,
        study_name: str,
        best_params: dict[str, Any],
        study: Any,
    ) -> None:
        """best_params와 study 요약을 JSON으로 저장한다."""
        # best_params
        params_path = self.hyperopt_dir / f"{study_name}_best_params.json"
        params_path.write_text(
            json.dumps(
                {
                    "algorithm": self.algorithm,
                    "ticker": self.dataset.ticker,
                    "n_trials": len(study.trials),
                    "best_value": round(study.best_value, 4),
                    "best_params": {
                        k: round(v, 6) if isinstance(v, float) else v
                        for k, v in best_params.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # study summary
        summary_path = self.hyperopt_dir / f"{study_name}_summary.json"
        trials_summary = []
        for t in study.trials:
            if t.value is not None:
                trials_summary.append({
                    "number": t.number,
                    "value": round(t.value, 4),
                    "state": str(t.state),
                })

        trials_summary.sort(key=lambda x: x["value"], reverse=True)
        summary_path.write_text(
            json.dumps(
                {
                    "study_name": study_name,
                    "total_trials": len(study.trials),
                    "best_trial": study.best_trial.number,
                    "best_value": round(study.best_value, 4),
                    "top_10_trials": trials_summary[:10],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
