"""
src/agents/rl_trading_sb3.py — SB3 통합 RL trainer

stable-baselines3 기반 DQN/A2C/PPO를 단일 클래스로 지원한다.
프로파일 JSON의 `algorithm` 필드로 알고리즘을 선택하고,
기존 TabularQTrainerV2와 동일한 인터페이스를 제공한다.

SB3/torch는 lazy import로 서버 시작 시간에 영향을 주지 않는다.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

from src.agents.rl_trading import (
    MIN_APPROVAL_RETURN_PCT,
    RLDataset,
    RLEvaluationMetrics,
    RLPolicyArtifact,
    RLSplitMetadata,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Supported algorithms — actual classes are lazy-imported
SUPPORTED_ALGORITHMS = ("dqn", "a2c", "ppo")


class SB3Trainer:
    """SB3 unified trainer for DQN/A2C/PPO.

    Usage:
        trainer = SB3Trainer(algorithm="dqn", learning_rate=5e-4, buffer_size=10000, ...)
        artifact, split = trainer.train_with_metadata(dataset, train_ratio=0.7)
        action, conf, info_str, details = trainer.infer_action(artifact, closes)
    """

    def __init__(
        self,
        *,
        algorithm: str = "dqn",
        lookback: int = 20,
        num_episodes: int = 10,
        trade_penalty_bps: int = 2,
        opportunity_cost_factor: float = 0.5,
        long_loss_penalty: float = 0.9,
        net_arch: list[int] | None = None,
        # Common SB3 params
        learning_rate: float = 5e-4,
        gamma: float = 0.95,
        # DQN-specific
        buffer_size: int = 10000,
        batch_size: int = 64,
        exploration_fraction: float = 0.2,
        exploration_final_eps: float = 0.05,
        target_update_interval: int = 500,
        train_freq: int = 4,
        gradient_steps: int = 1,
        # A2C-specific
        n_steps_a2c: int = 5,
        ent_coef_a2c: float = 0.01,
        vf_coef: float = 0.5,
        # PPO-specific
        n_steps_ppo: int = 2048,
        n_epochs: int = 10,
        clip_range: float = 0.2,
        ent_coef_ppo: float = 0.01,
        gae_lambda: float = 0.95,
        # Multi-seed
        num_seeds: int = 3,
        random_seed: int = 42,
    ) -> None:
        if algorithm not in SUPPORTED_ALGORITHMS:
            raise ValueError(
                f"Unsupported algorithm: {algorithm}. Use one of {SUPPORTED_ALGORITHMS}"
            )

        self.algorithm = algorithm
        self.lookback = lookback
        self.num_episodes = num_episodes
        self.trade_penalty_bps = trade_penalty_bps
        self.opportunity_cost_factor = opportunity_cost_factor
        self.long_loss_penalty = long_loss_penalty
        self.net_arch = net_arch or [64, 64]

        # Common
        self.learning_rate = learning_rate
        self.gamma = gamma

        # DQN
        self.buffer_size = buffer_size
        self.batch_size = batch_size
        self.exploration_fraction = exploration_fraction
        self.exploration_final_eps = exploration_final_eps
        self.target_update_interval = target_update_interval
        self.train_freq = train_freq
        self.gradient_steps = gradient_steps

        # A2C
        self.n_steps_a2c = n_steps_a2c
        self.ent_coef_a2c = ent_coef_a2c
        self.vf_coef = vf_coef

        # PPO
        self.n_steps_ppo = n_steps_ppo
        self.n_epochs = n_epochs
        self.clip_range = clip_range
        self.ent_coef_ppo = ent_coef_ppo
        self.gae_lambda = gae_lambda

        # Multi-seed
        self.num_seeds = num_seeds
        self.random_seed = random_seed

    # ──────────────────────── public API ────────────────────────

    def train(self, dataset: RLDataset, train_ratio: float = 0.7) -> RLPolicyArtifact:
        artifact, _ = self.train_with_metadata(dataset, train_ratio=train_ratio)
        return artifact

    def train_with_metadata(
        self,
        dataset: RLDataset,
        *,
        train_ratio: float = 0.7,
        on_progress: Callable[[int], None] | None = None,
    ) -> tuple[RLPolicyArtifact, RLSplitMetadata]:
        """Train an SB3 model and return artifact + split metadata."""
        if len(dataset.closes) <= self.lookback + 10:
            raise ValueError(
                f"RL 학습 길이가 너무 짧습니다: ticker={dataset.ticker}, "
                f"len={len(dataset.closes)}"
            )
        if not 0.5 <= train_ratio < 1.0:
            raise ValueError(
                f"train_ratio는 0.5 이상 1.0 미만이어야 합니다: {train_ratio}"
            )

        split_idx = max(self.lookback + 5, int(len(dataset.closes) * train_ratio))
        split_idx = min(split_idx, len(dataset.closes) - 3)

        train_closes = dataset.closes[:split_idx]
        train_volumes = [0.0] * len(train_closes)  # volumes not available in RLDataset
        holdout_closes = dataset.closes[split_idx - self.lookback :]

        split_metadata = self._build_split_metadata(dataset, split_idx, train_ratio)

        # Multi-seed training: train with multiple seeds, pick best on holdout
        best_model_path: str | None = None
        best_holdout_return = float("-inf")
        base_seed = self.random_seed + sum(ord(c) for c in dataset.ticker)

        for seed_offset in range(self.num_seeds):
            seed = base_seed + seed_offset * 1000
            model_path = self._train_single(train_closes, train_volumes, seed)
            evaluation = self._evaluate_model(model_path, holdout_closes)

            if evaluation.total_return_pct > best_holdout_return:
                best_holdout_return = evaluation.total_return_pct
                # Clean up previous best if exists
                if best_model_path and best_model_path != model_path:
                    self._cleanup_model(best_model_path)
                best_model_path = model_path
            else:
                self._cleanup_model(model_path)

            if on_progress is not None:
                pct = int(((seed_offset + 1) / self.num_seeds) * 80)
                on_progress(pct)

        assert best_model_path is not None
        evaluation = self._evaluate_model(best_model_path, holdout_closes)

        policy_id = (
            f"rl_{dataset.ticker}_"
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
        artifact = RLPolicyArtifact(
            policy_id=policy_id,
            ticker=dataset.ticker,
            created_at=datetime.now(timezone.utc).isoformat(),
            algorithm=self.algorithm,
            state_version=f"sb3_{self.algorithm}",
            lookback=self.lookback,
            episodes=self.num_episodes,
            learning_rate=self.learning_rate,
            discount_factor=self.gamma,
            epsilon=self.exploration_final_eps if self.algorithm == "dqn" else 0.0,
            trade_penalty_bps=self.trade_penalty_bps,
            evaluation=evaluation,
            q_table=None,  # SB3 doesn't use q_table
            model_path=best_model_path,
        )
        return artifact, split_metadata

    def evaluate(
        self,
        model_path_or_prices: Any,
        closes_or_none: list[float] | None = None,
    ) -> RLEvaluationMetrics:
        """Evaluate model on given price data.

        Supports two call patterns for compatibility:
        - evaluate(model_path: str, closes: list[float])  — SB3 style
        - evaluate(closes: list[float], model_path: str)   — adapter style
        """
        if isinstance(model_path_or_prices, str):
            model_path = model_path_or_prices
            closes = closes_or_none
        elif isinstance(model_path_or_prices, list):
            closes = model_path_or_prices
            model_path = closes_or_none
        else:
            raise TypeError(f"Unexpected type: {type(model_path_or_prices)}")

        if closes is None or model_path is None:
            raise ValueError("Both model_path and closes are required")

        return self._evaluate_model(model_path, closes)

    def infer_action(
        self,
        artifact: RLPolicyArtifact,
        closes: list[float],
        *,
        current_position: int = 0,
    ) -> tuple[str, float, str, dict[str, float]]:
        """Infer action from trained SB3 model.

        Returns same signature as TabularQTrainerV2.infer_action():
            (action_str, confidence, info_str, action_values_dict)
        """
        from src.agents.rl_environment import (
            GymTradingEnv,
            TradingEnvConfig,
            action_to_str,
        )

        if artifact.model_path is None:
            raise ValueError(f"Artifact {artifact.policy_id} has no model_path")

        model = self._load_model(artifact.model_path)

        # Build env just to get observation
        config = TradingEnvConfig(
            closes=closes,
            lookback=self.lookback,
            trade_penalty_bps=self.trade_penalty_bps,
            opportunity_cost_factor=self.opportunity_cost_factor,
            long_loss_penalty=self.long_loss_penalty,
        )
        env = GymTradingEnv(config)
        obs, _ = env.reset()

        # Override position in observation (last element)
        obs[-1] = float(current_position)

        # Get action and confidence
        action_int, _ = model.predict(obs, deterministic=True)
        action_int = int(action_int)

        # Compute confidence based on algorithm
        confidence, action_values = self._compute_confidence(model, obs)

        action_str = action_to_str(action_int)
        info_str = f"sb3_{self.algorithm}|pos={current_position}"

        return action_str, round(confidence, 4), info_str, action_values

    # ──────────────────────── training internals ────────────────────────

    def _train_single(
        self, closes: list[float], volumes: list[float], seed: int
    ) -> str:
        """Train a single model and return path to saved .zip."""
        from src.agents.rl_environment import GymTradingEnv, TradingEnvConfig

        config = TradingEnvConfig(
            closes=closes,
            volumes=volumes,
            lookback=self.lookback,
            trade_penalty_bps=self.trade_penalty_bps,
            opportunity_cost_factor=self.opportunity_cost_factor,
            long_loss_penalty=self.long_loss_penalty,
        )
        env = GymTradingEnv(config)

        algo_cls = self._get_algo_class()
        model_kwargs = self._build_model_kwargs(seed)

        total_timesteps = self.num_episodes * (len(closes) - self.lookback)

        model = algo_cls(
            "MlpPolicy",
            env,
            device="cpu",
            seed=seed,
            policy_kwargs={"net_arch": list(self.net_arch)},
            **model_kwargs,
        )
        model.learn(total_timesteps=total_timesteps)

        # Save to temp file
        tmp_dir = Path(tempfile.mkdtemp(prefix="rl_sb3_"))
        model_path = str(tmp_dir / f"model_{self.algorithm}_{seed}")
        model.save(model_path)

        return model_path  # SB3 appends .zip automatically

    def _evaluate_model(
        self, model_path: str, closes: list[float]
    ) -> RLEvaluationMetrics:
        """Evaluate a saved model on price data."""
        from src.agents.rl_environment import GymTradingEnv, TradingEnvConfig

        model = self._load_model(model_path)

        config = TradingEnvConfig(
            closes=closes,
            lookback=self.lookback,
            trade_penalty_bps=self.trade_penalty_bps,
            opportunity_cost_factor=self.opportunity_cost_factor,
            long_loss_penalty=self.long_loss_penalty,
        )
        env = GymTradingEnv(config)
        obs, info = env.reset()

        done = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(int(action))
            done = terminated or truncated

        summary = env.get_episode_summary()

        holdout_steps = max(0, len(closes) - self.lookback - 1)
        total_return_pct = summary["total_return_pct"]
        baseline_return_pct = summary["baseline_return_pct"]
        approved = (
            holdout_steps >= 5
            and total_return_pct >= MIN_APPROVAL_RETURN_PCT
            and summary["max_drawdown_pct"] >= -50.0
        )

        return RLEvaluationMetrics(
            total_return_pct=round(total_return_pct, 4),
            baseline_return_pct=round(baseline_return_pct, 4),
            excess_return_pct=round(total_return_pct - baseline_return_pct, 4),
            max_drawdown_pct=round(summary["max_drawdown_pct"], 4),
            trades=summary["total_trades"],
            win_rate=round(summary["win_rate"], 4),
            holdout_steps=holdout_steps,
            approved=approved,
        )

    # ──────────────────────── model management ────────────────────────

    def _get_algo_class(self) -> Any:
        """Lazy-import and return the SB3 algorithm class."""
        if self.algorithm == "dqn":
            from stable_baselines3 import DQN

            return DQN
        elif self.algorithm == "a2c":
            from stable_baselines3 import A2C

            return A2C
        elif self.algorithm == "ppo":
            from stable_baselines3 import PPO

            return PPO
        raise ValueError(f"Unknown algorithm: {self.algorithm}")

    def _load_model(self, model_path: str) -> Any:
        """Load a saved SB3 model."""
        algo_cls = self._get_algo_class()
        # SB3 .save() may or may not append .zip
        path = Path(model_path)
        if not path.exists() and not Path(f"{model_path}.zip").exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")
        return algo_cls.load(model_path, device="cpu")

    def _build_model_kwargs(self, seed: int) -> dict[str, Any]:
        """Build algorithm-specific kwargs for model construction."""
        if self.algorithm == "dqn":
            return {
                "learning_rate": self.learning_rate,
                "gamma": self.gamma,
                "buffer_size": self.buffer_size,
                "batch_size": self.batch_size,
                "exploration_fraction": self.exploration_fraction,
                "exploration_final_eps": self.exploration_final_eps,
                "target_update_interval": self.target_update_interval,
                "train_freq": self.train_freq,
                "gradient_steps": self.gradient_steps,
                "verbose": 0,
            }
        elif self.algorithm == "a2c":
            return {
                "learning_rate": self.learning_rate,
                "gamma": self.gamma,
                "n_steps": self.n_steps_a2c,
                "ent_coef": self.ent_coef_a2c,
                "vf_coef": self.vf_coef,
                "verbose": 0,
            }
        elif self.algorithm == "ppo":
            return {
                "learning_rate": self.learning_rate,
                "gamma": self.gamma,
                "n_steps": self.n_steps_ppo,
                "n_epochs": self.n_epochs,
                "batch_size": self.batch_size,
                "clip_range": self.clip_range,
                "ent_coef": self.ent_coef_ppo,
                "gae_lambda": self.gae_lambda,
                "verbose": 0,
            }
        return {}

    def _compute_confidence(
        self, model: Any, obs: np.ndarray
    ) -> tuple[float, dict[str, float]]:
        """Compute confidence score based on algorithm type.

        DQN: Q-value gap between best and second-best
        A2C/PPO: Max action probability from policy

        Returns (confidence, action_values_dict)
        """
        import torch

        from src.agents.rl_environment import NUM_ACTIONS, action_to_str

        obs_tensor = torch.as_tensor(obs).float().unsqueeze(0)

        if self.algorithm == "dqn":
            # DQN: extract Q-values from Q-network
            with torch.no_grad():
                q_values = model.q_net(obs_tensor).cpu().numpy().flatten()

            action_values = {
                action_to_str(i): float(q_values[i]) for i in range(NUM_ACTIONS)
            }
            sorted_q = sorted(q_values, reverse=True)
            gap = sorted_q[0] - sorted_q[1] if len(sorted_q) > 1 else 0.0
            confidence = max(0.34, min(0.98, 0.5 + gap * 5.0))

        else:
            # A2C/PPO: use action distribution probabilities
            with torch.no_grad():
                dist = model.policy.get_distribution(obs_tensor)
                probs = dist.distribution.probs.cpu().numpy().flatten()

            action_values = {
                action_to_str(i): float(probs[i]) for i in range(NUM_ACTIONS)
            }
            max_prob = float(probs.max())
            # Map probability to confidence: 0.25 (uniform) -> 0.34, 1.0 -> 0.98
            confidence = max(0.34, min(0.98, 0.34 + (max_prob - 0.25) * 0.853))

        return confidence, action_values

    @staticmethod
    def _cleanup_model(model_path: str) -> None:
        """Remove a saved model file."""
        for suffix in ("", ".zip"):
            p = Path(f"{model_path}{suffix}")
            if p.exists():
                p.unlink()

    @staticmethod
    def _build_split_metadata(
        dataset: RLDataset, split_idx: int, train_ratio: float
    ) -> RLSplitMetadata:
        train_timestamps = dataset.timestamps[:split_idx]
        test_timestamps = dataset.timestamps[split_idx:]
        return RLSplitMetadata(
            train_ratio=round(train_ratio, 4),
            train_size=len(train_timestamps),
            test_size=len(test_timestamps),
            train_start=train_timestamps[0] if train_timestamps else "",
            train_end=train_timestamps[-1] if train_timestamps else "",
            test_start=test_timestamps[0] if test_timestamps else "",
            test_end=test_timestamps[-1] if test_timestamps else "",
        )
