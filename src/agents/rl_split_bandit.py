"""
src/agents/rl_split_bandit.py — ε-greedy multi-armed bandit for RL train/test split.

(ticker, profile_id) 쌍별로 후보 train_ratio arm 중 하나를 선택하고,
walk-forward 보상으로 업데이트한다. 파일 기반(JSON, atomic write) 영속화로
별도 DB 없이 동작하며, 매 사이클마다 select → update 두 번 호출되는 것을 가정한다.

사용 의도: "정답이 없는" 시계열 학습 환경에서 7:3 같은 고정 split 대신,
RL 자체가 보상으로 best ratio를 찾아가도록 한다.
"""

from __future__ import annotations

import json
import os
import random
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from src.utils.logging import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BANDIT_DIR = ROOT / "artifacts" / "rl" / "bandit"
DEFAULT_RATIOS: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8)
DEFAULT_EPSILON = 0.2


def _ratio_key(ratio: float) -> str:
    """JSON 안전 키 (예: 0.7 → '0.70').

    부동소수 round-trip 문제를 피하기 위해 항상 소수점 2자리 문자열로 키화한다.
    """
    return f"{round(float(ratio), 2):.2f}"


# ── Data classes ──────────────────────────────────────────────────────────


@dataclass
class ArmStats:
    ratio: float
    pulls: int = 0
    total_reward: float = 0.0
    last_reward: float | None = None
    last_pulled_at: str | None = None

    @property
    def mean_reward(self) -> float:
        return self.total_reward / self.pulls if self.pulls else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ratio": round(self.ratio, 4),
            "pulls": self.pulls,
            "total_reward": round(self.total_reward, 6),
            "mean_reward": round(self.mean_reward, 6),
            "last_reward": (None if self.last_reward is None else round(self.last_reward, 6)),
            "last_pulled_at": self.last_pulled_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArmStats":
        return cls(
            ratio=float(data["ratio"]),
            pulls=int(data.get("pulls", 0)),
            total_reward=float(data.get("total_reward", 0.0)),
            last_reward=(
                None if data.get("last_reward") is None else float(data["last_reward"])
            ),
            last_pulled_at=data.get("last_pulled_at"),
        )


@dataclass
class BanditState:
    ticker: str
    profile_id: str
    arms: dict[str, ArmStats] = field(default_factory=dict)  # key = _ratio_key(ratio)
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "profile_id": self.profile_id,
            "updated_at": self.updated_at,
            "arms": {k: arm.to_dict() for k, arm in self.arms.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BanditState":
        return cls(
            ticker=str(data["ticker"]),
            profile_id=str(data["profile_id"]),
            updated_at=data.get("updated_at"),
            arms={k: ArmStats.from_dict(v) for k, v in (data.get("arms") or {}).items()},
        )


# ── Bandit ────────────────────────────────────────────────────────────────


class RLSplitBandit:
    """파일 기반 ε-greedy bandit.

    선택 규칙:
        1. cold-start — pulls=0인 arm이 있으면 그 arm 우선 (ratios 순서대로)
        2. ε 확률로 무작위 arm
        3. 그 외엔 mean_reward 최대 arm. 동률은 ratio가 작은 쪽 (보수적)

    영속화:
        - storage_dir/{ticker}__{profile_id}.json
        - tempfile + os.replace 로 atomic write
        - 동일 ticker가 동시에 학습되는 경로는 없으므로 lock 미사용
    """

    def __init__(
        self,
        *,
        storage_dir: Path | str | None = None,
        ratios: Sequence[float] = DEFAULT_RATIOS,
        epsilon: float = DEFAULT_EPSILON,
        rng: random.Random | None = None,
    ) -> None:
        if not ratios:
            raise ValueError("ratios must contain at least one value")
        if not 0.0 <= epsilon <= 1.0:
            raise ValueError(f"epsilon must be in [0, 1]: {epsilon}")
        self._storage_dir = Path(storage_dir or DEFAULT_BANDIT_DIR)
        self._ratios: tuple[float, ...] = tuple(round(float(r), 2) for r in ratios)
        self._epsilon = float(epsilon)
        self._rng = rng or random.Random()

    # ── public ────────────────────────────────────────────────────────────

    @property
    def ratios(self) -> tuple[float, ...]:
        return self._ratios

    @property
    def epsilon(self) -> float:
        return self._epsilon

    @property
    def storage_dir(self) -> Path:
        return self._storage_dir

    def select_ratio(self, ticker: str, profile_id: str) -> float:
        state = self._load_state(ticker, profile_id)
        # 1) cold-start: 미탐색 arm 우선
        for ratio in self._ratios:
            arm = state.arms.get(_ratio_key(ratio))
            if arm is None or arm.pulls == 0:
                return ratio
        # 2) ε 확률 무작위
        if self._rng.random() < self._epsilon:
            return self._rng.choice(self._ratios)
        # 3) greedy (동률 시 작은 ratio)
        return min(
            self._ratios,
            key=lambda r: (-state.arms[_ratio_key(r)].mean_reward, r),
        )

    def update(
        self,
        ticker: str,
        profile_id: str,
        ratio: float,
        reward: float,
    ) -> ArmStats:
        ratio = round(float(ratio), 2)
        if ratio not in self._ratios:
            raise ValueError(f"unknown ratio {ratio}, valid={self._ratios}")
        state = self._load_state(ticker, profile_id)
        key = _ratio_key(ratio)
        arm = state.arms.get(key) or ArmStats(ratio=ratio)
        arm.pulls += 1
        arm.total_reward += float(reward)
        arm.last_reward = float(reward)
        arm.last_pulled_at = datetime.now(timezone.utc).isoformat()
        state.arms[key] = arm
        state.updated_at = arm.last_pulled_at
        self._save_state(state)
        return arm

    def snapshot(self, ticker: str, profile_id: str) -> dict[str, Any]:
        """UI/응답에 노출하는 read-only 상태."""
        state = self._load_state(ticker, profile_id)
        arms_view: dict[str, dict[str, Any]] = {}
        for ratio in self._ratios:
            key = _ratio_key(ratio)
            arm = state.arms.get(key) or ArmStats(ratio=ratio)
            arms_view[key] = arm.to_dict()
        return {
            "ticker": state.ticker,
            "profile_id": state.profile_id,
            "epsilon": self._epsilon,
            "ratios": list(self._ratios),
            "best_ratio": self._best_ratio(state),
            "updated_at": state.updated_at,
            "arms": arms_view,
        }

    # ── internal ──────────────────────────────────────────────────────────

    def _best_ratio(self, state: BanditState) -> float | None:
        candidates: list[tuple[float, ArmStats]] = []
        for ratio in self._ratios:
            arm = state.arms.get(_ratio_key(ratio))
            if arm is not None and arm.pulls > 0:
                candidates.append((ratio, arm))
        if not candidates:
            return None
        return min(candidates, key=lambda pair: (-pair[1].mean_reward, pair[0]))[0]

    def _state_path(self, ticker: str, profile_id: str) -> Path:
        safe_ticker = ticker.replace("/", "_")
        safe_profile = profile_id.replace("/", "_")
        return self._storage_dir / f"{safe_ticker}__{safe_profile}.json"

    def _load_state(self, ticker: str, profile_id: str) -> BanditState:
        path = self._state_path(ticker, profile_id)
        if not path.exists():
            return BanditState(ticker=ticker, profile_id=profile_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return BanditState.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("bandit state 손상, 초기화: path=%s err=%s", path, exc)
            return BanditState(ticker=ticker, profile_id=profile_id)

    def _save_state(self, state: BanditState) -> None:
        path = self._state_path(state.ticker, state.profile_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # atomic write: tempfile + os.replace
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(state.to_dict(), tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)


# ── reward helper ─────────────────────────────────────────────────────────


def reward_from_walk_forward(
    *,
    consistency_score: float,
    excess_return_pct: float,
    consistency_weight: float = 0.6,
    excess_weight: float = 0.4,
) -> float:
    """Walk-forward 결과 → bandit reward 합성.

    excess_return_pct는 100으로 나눠 [-x, x] 단위로 정규화 후 가중합.
    consistency_score는 [0, 1] 가정.
    """
    return (
        consistency_weight * float(consistency_score)
        + excess_weight * (float(excess_return_pct) / 100.0)
    )
