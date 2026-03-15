"""
src/agents/blending.py — N-way 블렌딩 공통 로직

기존 2-way(A/B) 블렌딩을 하위 호환으로 유지하면서,
N개 전략의 시그널을 점수 기반(BUY=+1, HOLD=0, SELL=-1) 가중합으로 병합한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ────────────────────────── 기존 2-way (하위 호환) ──────────────────────────


@dataclass
class BlendResult:
    combined_signal: str
    combined_confidence: float
    conflict: bool


def blend_strategy_signals(
    strategy_a_signal: str | None,
    strategy_a_confidence: float | None,
    strategy_b_signal: str | None,
    strategy_b_confidence: float | None,
    blend_ratio: float,
) -> BlendResult:
    """
    기존 2-way A/B 블렌딩 래퍼.
    내부적으로 blend_signals()를 호출한다.
    """
    inputs: list[BlendInput] = []
    if strategy_a_signal:
        inputs.append(BlendInput(
            strategy="A",
            signal=strategy_a_signal,
            confidence=float(strategy_a_confidence or 0.0),
            weight=1.0 - max(0.0, min(1.0, float(blend_ratio))),
        ))
    if strategy_b_signal:
        inputs.append(BlendInput(
            strategy="B",
            signal=strategy_b_signal,
            confidence=float(strategy_b_confidence or 0.0),
            weight=max(0.0, min(1.0, float(blend_ratio))),
        ))

    if not inputs:
        return BlendResult(combined_signal="HOLD", combined_confidence=0.0, conflict=False)

    result = blend_signals(inputs)
    return BlendResult(
        combined_signal=result.signal,
        combined_confidence=result.confidence,
        conflict=result.conflict,
    )


# ────────────────────────── N-way 블렌딩 ──────────────────────────

# 시그널 → 점수 매핑
SIGNAL_SCORE = {"BUY": 1.0, "HOLD": 0.0, "SELL": -1.0}
VALID_SIGNALS = frozenset(SIGNAL_SCORE.keys())


@dataclass
class BlendInput:
    """N-way 블렌딩에 참여하는 개별 전략의 입력."""

    strategy: str           # "A", "B", "RL", "S", "L"
    signal: str             # "BUY", "SELL", "HOLD"
    confidence: float       # 0.0 ~ 1.0 (정규화 완료 상태)
    weight: float           # 설정에서 로드된 가중치


@dataclass
class NWayBlendResult:
    """N-way 블렌딩 결과."""

    signal: str                           # 최종 시그널: BUY / SELL / HOLD
    confidence: float                     # 가중 평균 confidence (0.0 ~ 1.0)
    weighted_score: float                 # 가중합 점수 (디버깅용)
    conflict: bool                        # 상충하는 시그널이 있는지
    participating_strategies: list[str]   # 참여 전략 목록
    meta: dict = field(default_factory=dict)  # 추가 메타데이터


def normalize_weights(inputs: list[BlendInput]) -> list[BlendInput]:
    """입력들의 가중치 합이 1.0이 되도록 정규화한다."""
    total_weight = sum(inp.weight for inp in inputs)
    if total_weight <= 0:
        # 가중치가 0이면 동일 가중치 부여
        equal_weight = 1.0 / max(1, len(inputs))
        return [
            BlendInput(
                strategy=inp.strategy,
                signal=inp.signal,
                confidence=inp.confidence,
                weight=equal_weight,
            )
            for inp in inputs
        ]
    return [
        BlendInput(
            strategy=inp.strategy,
            signal=inp.signal,
            confidence=inp.confidence,
            weight=inp.weight / total_weight,
        )
        for inp in inputs
    ]


def blend_signals(inputs: list[BlendInput]) -> NWayBlendResult:
    """N개 전략의 시그널을 점수 기반(BUY=+1, HOLD=0, SELL=-1) 가중합으로 병합한다.

    - 가중치는 자동 정규화 (합 = 1.0)
    - 시그널 결정: 가중합 점수 > +threshold → BUY, < -threshold → SELL, else HOLD
    - confidence: 가중 평균으로 합산
    - conflict: BUY와 SELL이 동시에 존재하면 True
    """
    if not inputs:
        return NWayBlendResult(
            signal="HOLD",
            confidence=0.0,
            weighted_score=0.0,
            conflict=False,
            participating_strategies=[],
        )

    # ── 단일 패스: 정규화 + 가중치 합산 + 충돌 감지를 한 번에 처리 ──
    total_weight = 0.0
    cleaned_signals: list[tuple[str, str, float, float]] = []  # (strategy, sig, conf, weight)

    for inp in inputs:
        sig = (inp.signal or "HOLD").upper()
        if sig not in VALID_SIGNALS:
            sig = "HOLD"
        conf = max(0.0, min(1.0, float(inp.confidence)))
        w = max(0.0, float(inp.weight))
        total_weight += w
        cleaned_signals.append((inp.strategy, sig, conf, w))

    # 가중치 정규화 + 점수/confidence 계산을 한 번에
    weighted_score = 0.0
    weighted_confidence = 0.0
    has_buy = False
    has_sell = False
    participating: list[str] = []
    weight_map: dict[str, float] = {}
    signal_map: dict[str, str] = {}
    confidence_map: dict[str, float] = {}

    norm_factor = total_weight if total_weight > 0 else 1.0
    equal_w = 1.0 / max(1, len(cleaned_signals)) if total_weight <= 0 else 0.0

    for strategy, sig, conf, raw_w in cleaned_signals:
        w = (raw_w / norm_factor) if total_weight > 0 else equal_w
        weighted_score += SIGNAL_SCORE[sig] * w * conf
        weighted_confidence += conf * w
        if sig == "BUY":
            has_buy = True
        elif sig == "SELL":
            has_sell = True
        participating.append(strategy)
        weight_map[strategy] = round(w, 4)
        signal_map[strategy] = sig
        confidence_map[strategy] = round(conf, 4)

    conflict = has_buy and has_sell

    # 시그널 결정: threshold 기반
    threshold = 0.15
    if weighted_score > threshold:
        final_signal = "BUY"
    elif weighted_score < -threshold:
        final_signal = "SELL"
    else:
        final_signal = "HOLD"

    return NWayBlendResult(
        signal=final_signal,
        confidence=round(max(0.0, min(1.0, weighted_confidence)), 4),
        weighted_score=round(weighted_score, 6),
        conflict=conflict,
        participating_strategies=participating,
        meta={
            "weights": weight_map,
            "signals": signal_map,
            "confidences": confidence_map,
        },
    )
