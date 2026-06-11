"""
src/agents/rl_policy_interface.py — 알고리즘 독립적인 RL 정책 인터페이스

RLRunner(라이브 추론)와 평가 하니스가 알고리즘(tabular Q / SB3 DQN·PPO / DreamerV3)을
몰라도 되도록, 공통 `act()` 인터페이스를 정의한다. 각 알고리즘은 이 인터페이스를
구현한 어댑터를 제공하고, `policy_from_artifact()` 팩토리가 artifact.algorithm 으로
적절한 어댑터를 생성한다.

이 추상화가 DreamerV3 도입의 핵심 seam이다 — 추론·평가 코드를 알고리즘 분기로
더럽히지 않고 정책 종류만 늘릴 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

from src.agents.rl_trading import RLPolicyArtifact

# 행동 도메인 (오케스트레이터 블렌딩은 BUY/SELL/HOLD 를 기대)
ACTIONS = ("BUY", "SELL", "HOLD")


@dataclass
class PolicyDecision:
    """정책 추론 결과 — 알고리즘 무관 공통 형식."""

    action: str
    confidence: float
    meta: dict = field(default_factory=dict)


@runtime_checkable
class RLPolicy(Protocol):
    """알고리즘 독립적 RL 정책 인터페이스.

    관측(종가 시퀀스 + 선택적 per-step 일중 특징, 현재 포지션) → 행동.
    features 는 combined 데이터셋(일봉+분봉)에서 온 일중 특징 시퀀스이며,
    이를 활용할 수 없는 정책(예: tabular)은 무시해도 된다.
    """

    algorithm: str

    def act(
        self,
        closes: Sequence[float],
        *,
        position: int = 0,
        features: Sequence[Sequence[float]] | None = None,
    ) -> PolicyDecision:
        ...


class TabularRLPolicy:
    """기존 TabularQTrainerV2 + q_table 을 공통 인터페이스로 감싸는 어댑터.

    tabular 정책은 종가 버킷 상태만 사용하므로 features(일중 특징)는 무시한다.
    """

    algorithm = "tabular_q_learning"

    def __init__(self, artifact: RLPolicyArtifact, trainer=None) -> None:
        if artifact.q_table is None:
            raise ValueError(
                f"tabular 정책에 q_table 이 없습니다: policy_id={artifact.policy_id}"
            )
        # 지연 import (순환 import 방지)
        if trainer is None:
            from src.agents.rl_trading_v2 import TabularQTrainerV2

            trainer = TabularQTrainerV2(lookback=artifact.lookback)
        self._artifact = artifact
        self._trainer = trainer

    def act(
        self,
        closes: Sequence[float],
        *,
        position: int = 0,
        features: Sequence[Sequence[float]] | None = None,
    ) -> PolicyDecision:
        action, confidence, state, _q = self._trainer.infer_action(
            self._artifact, list(closes), current_position=position
        )
        return PolicyDecision(
            action=action,
            confidence=float(confidence),
            meta={"algorithm": self.algorithm, "state": state},
        )


def policy_from_artifact(artifact: RLPolicyArtifact, trainer=None) -> RLPolicy:
    """artifact.algorithm 으로 적절한 정책 어댑터를 생성한다.

    현재 지원: tabular_q_learning. SB3/DreamerV3 어댑터는 후속 Feature 에서 등록된다.
    """
    algo = (artifact.algorithm or "").lower()
    if "tabular" in algo or artifact.q_table is not None:
        return TabularRLPolicy(artifact, trainer=trainer)
    raise ValueError(
        f"지원하지 않는 RL 정책 알고리즘: {artifact.algorithm!r} "
        f"(policy_id={artifact.policy_id})"
    )
