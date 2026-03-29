"""
src/utils/blend_weight_optimizer.py — 성과 기반 블렌딩 가중치 동적 조정

환경 변수 DYNAMIC_BLEND_WEIGHTS_ENABLED=true 로 opt-in.
기본(false)은 기존 고정 가중치 동작 유지.

알고리즘:
1. 전략별 최근 N일 거래 이력을 DB에서 fetch (signal_source 기준)
2. compute_trade_performance()로 수익률/승률/샤프 계산
3. 복합 점수로 가중치 산출 → 최솟값 floor → 재정규화
4. 데이터 부족 시 base_weights 그대로 반환 (안전 폴백)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.utils.performance import compute_trade_performance

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# 성과 지표 → 점수 변환 가중치
_W_RETURN = 1.0   # return_pct (단위: %)
_W_WIN_RATE = 10.0  # win_rate (0~1 → ×10 으로 return_pct 수준 스케일)
_W_SHARPE = 5.0   # sharpe_ratio (무차원)

# 전략 성과 데이터가 이 건수 미만이면 해당 전략은 base_weight 사용
MIN_TRADE_COUNT = 3


def _composite_score(perf: dict) -> float:
    """성과 dict → 단일 점수 (≥ 0).

    - return_pct: 실현 손익 기반 수익률(%)
    - win_rate: 승률 (0~1)
    - sharpe_ratio: 샤프 비율 (없으면 0)

    모두 음수가 될 수 있으므로 max(0, ...)로 클램핑.
    """
    return_pct = float(perf.get("return_pct") or 0.0)
    win_rate = float(perf.get("win_rate") or 0.0)
    sharpe = float(perf.get("sharpe_ratio") or 0.0)
    raw = (
        max(0.0, return_pct) * _W_RETURN
        + max(0.0, win_rate) * _W_WIN_RATE
        + max(0.0, sharpe) * _W_SHARPE
    )
    return max(0.0, raw)


def compute_dynamic_weights(
    perf_by_strategy: dict[str, dict],
    base_weights: dict[str, float],
    min_weight: float = 0.05,
) -> dict[str, float]:
    """성과 dict로부터 동적 블렌딩 가중치를 계산한다.

    Args:
        perf_by_strategy: {strategy_id: compute_trade_performance() 결과}
            - 없거나 trade_count < MIN_TRADE_COUNT인 전략은 base_weight 유지
        base_weights: 폴백용 기본 가중치 (정규화 전)
        min_weight: 최소 가중치 하한선 (어떤 전략도 이 값 아래로 내려가지 않음)

    Returns:
        합이 1.0인 가중치 dict. 키는 base_weights와 동일.
    """
    strategies = list(base_weights.keys())

    # 유효 성과 데이터가 있는 전략 분류
    scores: dict[str, float] = {}
    has_valid_data = False

    for s in strategies:
        perf = perf_by_strategy.get(s)
        if perf and int(perf.get("sell_count", 0)) >= MIN_TRADE_COUNT:
            scores[s] = _composite_score(perf)
            has_valid_data = True
        else:
            # 데이터 없으면 base_weight를 점수로 사용 (상대적 비율 유지)
            scores[s] = float(base_weights.get(s, 0.0))

    if not has_valid_data:
        logger.debug("동적 가중치: 유효 성과 데이터 없음 → base_weights 유지")
        return _normalize(dict(base_weights))

    logger.debug("동적 가중치 원점수: %s", scores)
    weights = _normalize(scores)
    weights = _apply_min_weight(weights, min_weight)
    logger.info("동적 블렌딩 가중치 산출: %s", weights)
    return weights


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    """값을 합이 1.0이 되도록 정규화한다. 합이 0이면 동일 가중치."""
    total = sum(scores.values())
    if total <= 0:
        n = max(1, len(scores))
        return {k: 1.0 / n for k in scores}
    return {k: v / total for k, v in scores.items()}


def _apply_min_weight(weights: dict[str, float], min_weight: float) -> dict[str, float]:
    """최소 가중치 floor 적용 후 재정규화."""
    n = len(weights)
    if n == 0:
        return weights
    # floor가 1/n을 초과하면 동일 가중치로 클램핑
    effective_floor = min(min_weight, 1.0 / n)
    floored = {k: max(v, effective_floor) for k, v in weights.items()}
    return _normalize(floored)


# ── DB 연동 헬퍼 ────────────────────────────────────────────────────────────


async def fetch_strategy_performance(
    strategies: list[str],
    lookback_days: int,
    account_scope: str = "paper",
) -> dict[str, dict]:
    """전략별 성과 지표를 DB에서 조회한다.

    Returns:
        {strategy_id: compute_trade_performance() 결과}
        - 조회 실패한 전략은 결과에서 제외
    """
    from src.db.queries import fetch_trade_rows_by_source

    result: dict[str, dict] = {}
    for strategy in strategies:
        try:
            rows = await fetch_trade_rows_by_source(
                signal_source=strategy,
                days=lookback_days,
                account_scope=account_scope,  # type: ignore[arg-type]
            )
            if rows:
                result[strategy] = compute_trade_performance(rows)
                logger.debug(
                    "전략 %s 성과 (%d일, %d건): %s",
                    strategy,
                    lookback_days,
                    len(rows),
                    result[strategy],
                )
            else:
                logger.debug("전략 %s: 최근 %d일 거래 없음", strategy, lookback_days)
        except Exception as exc:
            logger.warning("전략 %s 성과 조회 실패: %s", strategy, exc)
    return result


class BlendWeightOptimizer:
    """성과 기반 블렌딩 가중치 최적화기.

    사용 예:
        optimizer = BlendWeightOptimizer(
            base_weights={"A": 0.30, "B": 0.30, "RL": 0.20, "S": 0.20},
            lookback_days=30,
            min_weight=0.05,
        )
        weights = await optimizer.optimize(account_scope="paper")
    """

    def __init__(
        self,
        base_weights: dict[str, float],
        lookback_days: int = 30,
        min_weight: float = 0.05,
    ) -> None:
        self.base_weights = base_weights
        self.lookback_days = lookback_days
        self.min_weight = min_weight

    async def optimize(self, account_scope: str = "paper") -> dict[str, float]:
        """성과를 조회하고 동적 가중치를 반환한다.

        DB 연결 실패 등 예외 발생 시 base_weights를 안전하게 반환한다.
        """
        try:
            perf = await fetch_strategy_performance(
                strategies=list(self.base_weights.keys()),
                lookback_days=self.lookback_days,
                account_scope=account_scope,
            )
            return compute_dynamic_weights(
                perf_by_strategy=perf,
                base_weights=self.base_weights,
                min_weight=self.min_weight,
            )
        except Exception as exc:
            logger.error("BlendWeightOptimizer.optimize() 실패 → base_weights 사용: %s", exc)
            return _normalize(dict(self.base_weights))
