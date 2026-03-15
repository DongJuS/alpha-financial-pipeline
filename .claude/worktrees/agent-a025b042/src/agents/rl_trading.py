"""
src/agents/rl_trading.py — lightweight RL trading lane

Q-learning 기반의 최소 RL lane을 제공합니다.
기존 Strategy A/B를 대체하지 않고, 별도 signal source로 동작합니다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
import random
from typing import Literal, Optional

from src.db.models import PredictionSignal
from src.db.queries import fetch_recent_market_data, get_position
from src.utils.logging import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACTS_DIR = ROOT / "artifacts" / "rl"
ACTIONS = ("BUY", "SELL", "HOLD")
MIN_APPROVAL_RETURN_PCT = 5.0
RLInterval = Literal["daily", "tick"]


@dataclass
class RLDataset:
    ticker: str
    closes: list[float]
    timestamps: list[str]


@dataclass
class RLEvaluationMetrics:
    total_return_pct: float
    baseline_return_pct: float
    excess_return_pct: float
    max_drawdown_pct: float
    trades: int
    win_rate: float
    holdout_steps: int
    approved: bool


@dataclass
class RLSplitMetadata:
    train_ratio: float
    train_size: int
    test_size: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str


@dataclass
class RLPolicyArtifact:
    policy_id: str
    ticker: str
    created_at: str
    algorithm: str
    state_version: str
    lookback: int
    episodes: int
    learning_rate: float
    discount_factor: float
    epsilon: float
    trade_penalty_bps: int
    q_table: dict[str, dict[str, float]]
    evaluation: RLEvaluationMetrics
    artifact_path: Optional[str] = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["evaluation"] = asdict(self.evaluation)
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> "RLPolicyArtifact":
        return cls(
            policy_id=payload["policy_id"],
            ticker=payload["ticker"],
            created_at=payload["created_at"],
            algorithm=payload.get("algorithm", "tabular_q_learning"),
            state_version=payload.get("state_version", "qlearn_v1"),
            lookback=int(payload.get("lookback", 6)),
            episodes=int(payload.get("episodes", 60)),
            learning_rate=float(payload.get("learning_rate", 0.18)),
            discount_factor=float(payload.get("discount_factor", 0.92)),
            epsilon=float(payload.get("epsilon", 0.15)),
            trade_penalty_bps=int(payload.get("trade_penalty_bps", 5)),
            q_table={
                str(state): {str(action): float(value) for action, value in actions.items()}
                for state, actions in payload.get("q_table", {}).items()
            },
            evaluation=RLEvaluationMetrics(**payload.get("evaluation", {})),
            artifact_path=payload.get("artifact_path"),
        )


class RLDatasetBuilder:
    def __init__(self, min_history_points: int = 40, default_interval: RLInterval = "daily") -> None:
        self.min_history_points = min_history_points
        self.default_interval = default_interval

    async def build_dataset(
        self,
        ticker: str,
        days: int = 120,
        *,
        interval: RLInterval | None = None,
        seconds: int | None = None,
        limit: int | None = None,
    ) -> RLDataset:
        resolved_interval = interval or self.default_interval
        query_days = days if resolved_interval == "daily" else None
        query_seconds = seconds
        if resolved_interval == "tick" and query_seconds is None and days is not None and limit is None:
            query_seconds = max(1, days * 24 * 60 * 60)
        if resolved_interval == "tick" and query_seconds is None and limit is None:
            limit = 5_000

        rows = await fetch_recent_market_data(
            ticker,
            interval=resolved_interval,
            days=query_days,
            seconds=query_seconds,
            limit=limit,
        )
        ordered_rows = sorted(rows, key=lambda row: row["timestamp_kst"])
        closes = [float(row["close"]) for row in ordered_rows if row.get("close")]
        timestamps = [str(row["timestamp_kst"]) for row in ordered_rows if row.get("close")]
        if len(closes) < self.min_history_points:
            raise ValueError(
                f"RL 학습 이력 부족: ticker={ticker}, interval={resolved_interval}, history={len(closes)}, required={self.min_history_points}"
            )
        return RLDataset(ticker=ticker, closes=closes, timestamps=timestamps)


class RLPolicyStore:
    def __init__(self, artifacts_dir: Path | None = None) -> None:
        self.artifacts_dir = Path(artifacts_dir or DEFAULT_ARTIFACTS_DIR)
        self.registry_path = self.artifacts_dir / "active_policies.json"

    def save_policy(self, artifact: RLPolicyArtifact) -> RLPolicyArtifact:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = self.artifacts_dir / f"{artifact.policy_id}.json"
        payload = artifact.to_dict()
        payload["artifact_path"] = str(path)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact.artifact_path = str(path)
        return artifact

    def activate_policy(self, artifact: RLPolicyArtifact) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        registry = self.list_active_policies()
        registry["updated_at"] = datetime.now(timezone.utc).isoformat()
        registry["policies"][artifact.ticker] = {
            "policy_id": artifact.policy_id,
            "artifact_path": artifact.artifact_path,
            "evaluation": asdict(artifact.evaluation),
        }
        self.registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_policy(self, policy_id: str) -> RLPolicyArtifact:
        path = self.artifacts_dir / f"{policy_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RLPolicyArtifact.from_dict(payload)

    def load_active_policy(self, ticker: str) -> Optional[RLPolicyArtifact]:
        registry = self.list_active_policies()
        policy_info = registry["policies"].get(ticker)
        if not policy_info:
            return None
        artifact_path = policy_info.get("artifact_path")
        if not artifact_path:
            return self.load_policy(policy_info["policy_id"])
        path = Path(artifact_path)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RLPolicyArtifact.from_dict(payload)

    def list_active_policies(self) -> dict:
        if not self.registry_path.exists():
            return {"updated_at": None, "policies": {}}
        return json.loads(self.registry_path.read_text(encoding="utf-8"))


class TabularQTrainer:
    def __init__(
        self,
        *,
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

    def train(self, dataset: RLDataset, train_ratio: float = 0.7) -> RLPolicyArtifact:
        artifact, _ = self.train_with_metadata(dataset, train_ratio=train_ratio)
        return artifact

    def train_with_metadata(
        self,
        dataset: RLDataset,
        *,
        train_ratio: float = 0.7,
    ) -> tuple[RLPolicyArtifact, RLSplitMetadata]:
        if len(dataset.closes) <= self.lookback + 10:
            raise ValueError(f"RL 학습 길이가 너무 짧습니다: ticker={dataset.ticker}, len={len(dataset.closes)}")

        if not 0.5 <= train_ratio < 1.0:
            raise ValueError(f"train_ratio는 0.5 이상 1.0 미만이어야 합니다: {train_ratio}")

        split_idx = max(self.lookback + 5, int(len(dataset.closes) * train_ratio))
        split_idx = min(split_idx, len(dataset.closes) - 3)
        split_metadata = self._build_split_metadata(dataset, split_idx=split_idx, train_ratio=train_ratio)

        q_table: dict[str, dict[str, float]] = {}
        rng = random.Random(self.random_seed + sum(ord(ch) for ch in dataset.ticker))
        train_prices = dataset.closes[:split_idx]

        for episode in range(self.episodes):
            position = 0
            current_epsilon = max(0.01, self.epsilon * (1.0 - (episode / max(1, self.episodes))))
            for idx in range(self.lookback, len(train_prices) - 1):
                state = self._state_key(train_prices[: idx + 1], position)
                action = self._select_action(q_table, state, rng, current_epsilon)
                next_position = self._transition(position, action)
                reward = self._reward(train_prices[idx], train_prices[idx + 1], position, next_position)
                next_state = self._state_key(train_prices[: idx + 2], next_position)
                self._update_q(q_table, state, action, reward, next_state)
                position = next_position

        holdout_prices = dataset.closes[split_idx - self.lookback :]
        evaluation = self.evaluate(holdout_prices, q_table)
        policy_id = f"rl_{dataset.ticker}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        artifact = RLPolicyArtifact(
            policy_id=policy_id,
            ticker=dataset.ticker,
            created_at=datetime.now(timezone.utc).isoformat(),
            algorithm="tabular_q_learning",
            state_version="qlearn_v1",
            lookback=self.lookback,
            episodes=self.episodes,
            learning_rate=self.learning_rate,
            discount_factor=self.discount_factor,
            epsilon=self.epsilon,
            trade_penalty_bps=self.trade_penalty_bps,
            q_table=q_table,
            evaluation=evaluation,
        )
        return artifact, split_metadata

    def evaluate(self, prices: list[float], q_table: dict[str, dict[str, float]]) -> RLEvaluationMetrics:
        position = 0
        equity = 1.0
        baseline = 1.0
        peak_equity = 1.0
        max_drawdown_pct = 0.0
        trades = 0
        wins = 0
        holdout_steps = max(0, len(prices) - self.lookback - 1)

        for idx in range(self.lookback, len(prices) - 1):
            state = self._state_key(prices[: idx + 1], position)
            action = self.best_action(q_table, state)
            next_position = self._transition(position, action)
            reward = self._reward(prices[idx], prices[idx + 1], position, next_position)
            daily_return = (prices[idx + 1] / prices[idx]) - 1.0
            equity *= max(0.0001, 1.0 + reward)
            baseline *= max(0.0001, 1.0 + daily_return)
            if next_position != position:
                trades += 1
                if reward > 0:
                    wins += 1
            peak_equity = max(peak_equity, equity)
            drawdown_pct = ((equity - peak_equity) / peak_equity) * 100.0
            max_drawdown_pct = min(max_drawdown_pct, drawdown_pct)
            position = next_position

        total_return_pct = (equity - 1.0) * 100.0
        baseline_return_pct = (baseline - 1.0) * 100.0
        win_rate = (wins / trades) if trades else 0.0
        approved = (
            holdout_steps >= 5
            and total_return_pct >= MIN_APPROVAL_RETURN_PCT
            and max_drawdown_pct >= -15.0
        )
        return RLEvaluationMetrics(
            total_return_pct=round(total_return_pct, 4),
            baseline_return_pct=round(baseline_return_pct, 4),
            excess_return_pct=round(total_return_pct - baseline_return_pct, 4),
            max_drawdown_pct=round(max_drawdown_pct, 4),
            trades=trades,
            win_rate=round(win_rate, 4),
            holdout_steps=holdout_steps,
            approved=approved,
        )

    def infer_action(
        self,
        artifact: RLPolicyArtifact,
        closes: list[float],
        *,
        current_position: int = 0,
    ) -> tuple[str, float, str, dict[str, float]]:
        state = self._state_key(closes, current_position)
        q_values = self._ensure_state(artifact.q_table, state)
        ordered = sorted(q_values.items(), key=lambda item: (-item[1], item[0]))
        best_action = ordered[0][0]
        gap = ordered[0][1] - ordered[1][1]
        confidence = max(0.34, min(0.98, 0.5 + (gap * 12.0)))
        return best_action, round(confidence, 4), state, q_values

    def best_action(self, q_table: dict[str, dict[str, float]], state: str) -> str:
        q_values = self._ensure_state(q_table, state)
        return sorted(q_values.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def _select_action(
        self,
        q_table: dict[str, dict[str, float]],
        state: str,
        rng: random.Random,
        epsilon: float,
    ) -> str:
        q_values = self._ensure_state(q_table, state)
        if rng.random() < epsilon:
            return rng.choice(list(ACTIONS))
        return sorted(q_values.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def _update_q(
        self,
        q_table: dict[str, dict[str, float]],
        state: str,
        action: str,
        reward: float,
        next_state: str,
    ) -> None:
        state_actions = self._ensure_state(q_table, state)
        next_actions = self._ensure_state(q_table, next_state)
        best_future = max(next_actions.values())
        current = state_actions[action]
        state_actions[action] = current + self.learning_rate * (
            reward + (self.discount_factor * best_future) - current
        )

    @staticmethod
    def _ensure_state(q_table: dict[str, dict[str, float]], state: str) -> dict[str, float]:
        if state not in q_table:
            q_table[state] = {action: 0.0 for action in ACTIONS}
        return q_table[state]

    @staticmethod
    def _transition(position: int, action: str) -> int:
        if action == "BUY":
            return 1
        if action == "SELL":
            return 0
        return position

    def _reward(self, current_price: float, next_price: float, position: int, next_position: int) -> float:
        next_return = (next_price / current_price) - 1.0
        trade_penalty = (self.trade_penalty_bps / 10_000.0) if next_position != position else 0.0
        return (next_position * next_return) - trade_penalty

    def _state_key(self, closes: list[float], position: int) -> str:
        if len(closes) < 2:
            return f"p{position}|s0|l0"
        short_return = (closes[-1] / closes[-2]) - 1.0
        window = closes[-5:] if len(closes) >= 5 else closes
        moving_avg = sum(window) / len(window)
        long_return = ((closes[-1] / moving_avg) - 1.0) if moving_avg else 0.0
        short_bucket = self._bucket(short_return, threshold=0.004)
        long_bucket = self._bucket(long_return, threshold=0.008)
        return f"p{position}|s{short_bucket}|l{long_bucket}"

    @staticmethod
    def _bucket(value: float, threshold: float) -> int:
        if value > threshold:
            return 1
        if value < -threshold:
            return -1
        return 0

    def _build_split_metadata(
        self,
        dataset: RLDataset,
        *,
        split_idx: int,
        train_ratio: float,
    ) -> RLSplitMetadata:
        train_timestamps = dataset.timestamps[:split_idx]
        test_timestamps = dataset.timestamps[split_idx:]
        return RLSplitMetadata(
            train_ratio=round(train_ratio, 4),
            train_size=len(train_timestamps),
            test_size=len(test_timestamps),
            train_start=train_timestamps[0],
            train_end=train_timestamps[-1],
            test_start=test_timestamps[0],
            test_end=test_timestamps[-1],
        )


class RLTradingAgent:
    def __init__(
        self,
        *,
        dataset_builder: RLDatasetBuilder | None = None,
        trainer: TabularQTrainer | None = None,
        policy_store: RLPolicyStore | None = None,
        dataset_interval: RLInterval = "daily",
        training_window_days: int = 120,
        training_window_seconds: int | None = None,
        dataset_limit: int | None = None,
        use_latest_tick_for_inference: bool = True,
    ) -> None:
        self.dataset_builder = dataset_builder or RLDatasetBuilder()
        self.trainer = trainer or TabularQTrainer()
        self.policy_store = policy_store or RLPolicyStore()
        self.dataset_interval = dataset_interval
        self.training_window_days = training_window_days
        self.training_window_seconds = training_window_seconds
        self.dataset_limit = dataset_limit
        self.use_latest_tick_for_inference = use_latest_tick_for_inference

    async def run_cycle(
        self,
        tickers: list[str],
        *,
        account_scope: str = "paper",
    ) -> tuple[list[PredictionSignal], list[dict]]:
        predictions: list[PredictionSignal] = []
        summaries: list[dict] = []

        for ticker in tickers:
            try:
                dataset = await self.dataset_builder.build_dataset(
                    ticker,
                    days=self.training_window_days,
                    interval=self.dataset_interval,
                    seconds=self.training_window_seconds,
                    limit=self.dataset_limit,
                )
                trained_artifact = self.trainer.train(dataset)
                trained_artifact = self.policy_store.save_policy(trained_artifact)

                active_artifact = self._select_active_policy(ticker, trained_artifact)
                signal = await self._signal_from_policy(
                    ticker=ticker,
                    dataset=dataset,
                    artifact=active_artifact,
                    training_artifact=trained_artifact,
                    account_scope=account_scope,
                )
                predictions.append(signal)
                summaries.append(
                    {
                        "ticker": ticker,
                        "trained_policy_id": trained_artifact.policy_id,
                        "active_policy_id": active_artifact.policy_id if active_artifact else None,
                        "signal": signal.signal,
                        "confidence": signal.confidence,
                        "dataset_interval": self.dataset_interval,
                        "approved": trained_artifact.evaluation.approved,
                        "evaluation": asdict(trained_artifact.evaluation),
                    }
                )
            except Exception as exc:
                logger.warning("RL cycle 실패 [%s]: %s", ticker, exc)
                predictions.append(
                    self._hold_signal(
                        ticker=ticker,
                        reasoning_summary=f"rl_cycle_failed: {exc}",
                    )
                )
                summaries.append(
                    {
                        "ticker": ticker,
                        "trained_policy_id": None,
                        "active_policy_id": None,
                        "signal": "HOLD",
                        "confidence": 0.0,
                        "dataset_interval": self.dataset_interval,
                        "approved": False,
                        "error": str(exc),
                    }
                )

        return predictions, summaries

    def _select_active_policy(
        self,
        ticker: str,
        trained_artifact: RLPolicyArtifact,
    ) -> Optional[RLPolicyArtifact]:
        if trained_artifact.evaluation.approved:
            self.policy_store.activate_policy(trained_artifact)
            return trained_artifact
        return self.policy_store.load_active_policy(ticker)

    async def _signal_from_policy(
        self,
        *,
        ticker: str,
        dataset: RLDataset,
        artifact: Optional[RLPolicyArtifact],
        training_artifact: RLPolicyArtifact,
        account_scope: str,
    ) -> PredictionSignal:
        if artifact is None:
            return self._hold_signal(
                ticker=ticker,
                reasoning_summary=(
                    f"approved policy unavailable; latest_eval_return={training_artifact.evaluation.total_return_pct:.2f}%"
                ),
            )

        position = await self._current_position_flag(ticker, account_scope)
        inference_closes, latest_tick_ts = await self._build_inference_closes(ticker, dataset)
        action, confidence, state, q_values = self.trainer.infer_action(
            artifact,
            inference_closes,
            current_position=position,
        )
        emitted_signal = action
        if action == "BUY" and position == 1:
            emitted_signal = "HOLD"
        if action == "SELL" and position == 0:
            emitted_signal = "HOLD"

        latest_close = int(inference_closes[-1])
        target_price = latest_close if emitted_signal != "BUY" else int(round(latest_close * (1 + confidence * 0.01)))
        stop_loss = int(round(latest_close * 0.97)) if emitted_signal == "BUY" else None

        return PredictionSignal(
            agent_id="rl_policy_agent",
            llm_model="tabular-q-learning",
            strategy="RL",
            ticker=ticker,
            signal=emitted_signal,
            confidence=confidence,
            target_price=target_price,
            stop_loss=stop_loss,
            reasoning_summary=(
                f"policy={artifact.policy_id}, state={state}, q={q_values}, "
                f"approved={artifact.evaluation.approved}, holdout_return={artifact.evaluation.total_return_pct:.2f}%, "
                f"latest_tick_ts={latest_tick_ts}"
            ),
            trading_date=date.today(),
        )

    async def _current_position_flag(self, ticker: str, account_scope: str) -> int:
        position = await get_position(ticker, account_scope=account_scope)
        if position and int(position.get("quantity") or 0) > 0:
            return 1
        return 0

    async def _build_inference_closes(self, ticker: str, dataset: RLDataset) -> tuple[list[float], str | None]:
        if not self.use_latest_tick_for_inference:
            return dataset.closes, None

        latest_ticks = await fetch_recent_market_data(ticker, interval="tick", limit=1)
        if not latest_ticks:
            return dataset.closes, None

        latest_tick = latest_ticks[0]
        latest_close = latest_tick.get("close")
        latest_ts = str(latest_tick.get("timestamp_kst"))
        if latest_close in {None, ""}:
            return dataset.closes, latest_ts

        if dataset.timestamps and latest_ts == dataset.timestamps[-1]:
            return dataset.closes, latest_ts
        return [*dataset.closes, float(latest_close)], latest_ts

    @staticmethod
    def _hold_signal(ticker: str, reasoning_summary: str) -> PredictionSignal:
        return PredictionSignal(
            agent_id="rl_policy_agent",
            llm_model="tabular-q-learning",
            strategy="RL",
            ticker=ticker,
            signal="HOLD",
            confidence=0.0,
            reasoning_summary=reasoning_summary,
            trading_date=date.today(),
        )
