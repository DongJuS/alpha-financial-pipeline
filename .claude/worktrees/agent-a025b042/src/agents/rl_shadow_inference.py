"""
src/agents/rl_shadow_inference.py — Shadow Inference & Paper Promotion Gate

Shadow 모드 RL 추론 모듈:
1. RL 시그널을 is_shadow=True로 기록 (블렌딩에 참여하지 않음)
2. Shadow 기간 동안의 누적 성과를 추적
3. Walk-forward 검증 결과를 승격 게이트에 통합
4. 조건 충족 시 paper → real 승격 추천

승격 파이프라인:
  학습 → 오프라인 평가 → shadow 추론(기록만) → paper 승격 게이트 → paper 운용 → real 승격 게이트
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from src.agents.rl_policy_registry import PolicyEntry, PromotionGate
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.db.models import PredictionSignal
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ── Shadow 기록 데이터 모델 ────────────────────────────────────────────────


class ShadowRecord(BaseModel):
    """Shadow 추론 단건 기록."""

    policy_id: str
    ticker: str
    signal: Literal["BUY", "SELL", "HOLD"]
    confidence: float = 0.0
    close_price: float = 0.0
    trading_date: date
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ShadowPerformance(BaseModel):
    """Shadow 기간 누적 성과 요약."""

    policy_id: str
    ticker: str
    total_trades: int = 0
    buy_signals: int = 0
    sell_signals: int = 0
    hold_signals: int = 0
    shadow_days: int = 0
    simulated_return_pct: float = 0.0
    simulated_max_drawdown_pct: float = 0.0
    avg_confidence: float = 0.0
    first_date: Optional[date] = None
    last_date: Optional[date] = None


# ── 승격 게이트 설정 ──────────────────────────────────────────────────────


class PaperPromotionCriteria(BaseModel):
    """Shadow → Paper 승격 기준."""

    min_shadow_days: int = 10
    min_shadow_trades: int = 5
    min_return_pct: float = 2.0
    max_drawdown_limit_pct: float = -20.0
    min_avg_confidence: float = 0.4
    require_walk_forward_approval: bool = True
    min_walk_forward_consistency: float = 0.6


class RealPromotionCriteria(BaseModel):
    """Paper → Real 승격 기준."""

    min_paper_days: int = 30
    min_paper_trades: int = 20
    min_return_pct: float = 5.0
    max_drawdown_limit_pct: float = -15.0
    min_sharpe_ratio: float = 0.5
    require_walk_forward_approval: bool = True


class PromotionCheckResult(BaseModel):
    """승격 게이트 평가 결과."""

    policy_id: str
    ticker: str
    promotion_type: Literal["shadow_to_paper", "paper_to_real"]
    passed: bool = False
    criteria: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Shadow Inference Engine ───────────────────────────────────────────────


class ShadowInferenceEngine:
    """Shadow 모드 RL 추론 엔진.

    - 활성 정책 또는 후보 정책으로 추론 실행
    - is_shadow=True 시그널 생성
    - Shadow 기간 성과 추적 (인메모리, 프로덕션에서는 DB로 대체)
    """

    def __init__(
        self,
        policy_store: RLPolicyStoreV2 | None = None,
        paper_criteria: PaperPromotionCriteria | None = None,
        real_criteria: RealPromotionCriteria | None = None,
    ) -> None:
        self.policy_store = policy_store or RLPolicyStoreV2()
        self.paper_criteria = paper_criteria or PaperPromotionCriteria()
        self.real_criteria = real_criteria or RealPromotionCriteria()

        # 인메모리 shadow 기록 (policy_id -> list[ShadowRecord])
        self._shadow_records: dict[str, list[ShadowRecord]] = {}

    # ── Shadow 시그널 생성 ─────────────────────────────────────────────────

    def create_shadow_signal(
        self,
        *,
        policy_id: str,
        ticker: str,
        signal: Literal["BUY", "SELL", "HOLD"],
        confidence: float,
        close_price: float,
        reasoning_summary: str = "",
    ) -> PredictionSignal:
        """Shadow 모드 시그널을 생성하고 내부 기록에 추가합니다.

        반환된 PredictionSignal의 is_shadow=True이므로
        블렌딩 엔진에서 자동으로 제외됩니다.
        """
        today = date.today()

        # Shadow 기록 저장
        record = ShadowRecord(
            policy_id=policy_id,
            ticker=ticker,
            signal=signal,
            confidence=confidence,
            close_price=close_price,
            trading_date=today,
        )
        if policy_id not in self._shadow_records:
            self._shadow_records[policy_id] = []
        self._shadow_records[policy_id].append(record)

        logger.info(
            "Shadow 시그널 기록: policy=%s, ticker=%s, signal=%s, conf=%.2f",
            policy_id, ticker, signal, confidence,
        )

        # PredictionSignal 생성 (is_shadow=True)
        return PredictionSignal(
            agent_id="rl_shadow_agent",
            llm_model="tabular-q-learning",
            strategy="RL",
            ticker=ticker,
            signal=signal,
            confidence=confidence,
            target_price=int(close_price),
            stop_loss=None,
            reasoning_summary=f"[SHADOW] {reasoning_summary}",
            trading_date=today,
            is_shadow=True,
        )

    # ── Shadow 성과 조회 ──────────────────────────────────────────────────

    def get_shadow_performance(
        self,
        policy_id: str,
        ticker: str | None = None,
    ) -> ShadowPerformance:
        """특정 정책의 shadow 기간 누적 성과를 계산합니다."""
        records = self._shadow_records.get(policy_id, [])
        if ticker:
            records = [r for r in records if r.ticker == ticker]

        if not records:
            return ShadowPerformance(
                policy_id=policy_id,
                ticker=ticker or "",
            )

        buy_signals = sum(1 for r in records if r.signal == "BUY")
        sell_signals = sum(1 for r in records if r.signal == "SELL")
        hold_signals = sum(1 for r in records if r.signal == "HOLD")
        total_trades = buy_signals + sell_signals

        dates = sorted(set(r.trading_date for r in records))
        shadow_days = len(dates)
        avg_confidence = sum(r.confidence for r in records) / len(records) if records else 0.0

        # 시뮬레이션 수익률 계산 (단순화: 가격 기반)
        simulated_return, max_drawdown = self._simulate_shadow_returns(records)

        return ShadowPerformance(
            policy_id=policy_id,
            ticker=ticker or records[0].ticker,
            total_trades=total_trades,
            buy_signals=buy_signals,
            sell_signals=sell_signals,
            hold_signals=hold_signals,
            shadow_days=shadow_days,
            simulated_return_pct=round(simulated_return, 4),
            simulated_max_drawdown_pct=round(max_drawdown, 4),
            avg_confidence=round(avg_confidence, 4),
            first_date=dates[0] if dates else None,
            last_date=dates[-1] if dates else None,
        )

    def _simulate_shadow_returns(
        self, records: list[ShadowRecord]
    ) -> tuple[float, float]:
        """Shadow 기록으로부터 시뮬레이션 수익률과 MDD를 계산합니다.

        단순 전략: BUY 시 진입, SELL 시 청산, HOLD 시 유지.
        """
        if len(records) < 2:
            return 0.0, 0.0

        sorted_records = sorted(records, key=lambda r: r.trading_date)
        position = 0  # 0: 현금, 1: 보유
        entry_price = 0.0
        cumulative_return = 0.0
        peak_return = 0.0
        max_drawdown = 0.0

        for rec in sorted_records:
            if rec.signal == "BUY" and position == 0 and rec.close_price > 0:
                position = 1
                entry_price = rec.close_price
            elif rec.signal == "SELL" and position == 1 and entry_price > 0:
                trade_return = (rec.close_price - entry_price) / entry_price * 100
                cumulative_return += trade_return
                position = 0
                entry_price = 0.0

            # MDD 계산
            peak_return = max(peak_return, cumulative_return)
            current_drawdown = cumulative_return - peak_return
            max_drawdown = min(max_drawdown, current_drawdown)

        return cumulative_return, max_drawdown

    # ── 승격 게이트 평가 ──────────────────────────────────────────────────

    def evaluate_shadow_to_paper(
        self,
        policy_id: str,
        ticker: str,
        *,
        walk_forward_approved: bool | None = None,
        walk_forward_consistency: float | None = None,
    ) -> PromotionCheckResult:
        """Shadow → Paper 승격 게이트를 평가합니다."""
        criteria = self.paper_criteria
        perf = self.get_shadow_performance(policy_id, ticker)

        failures: list[str] = []
        actual: dict[str, Any] = {}
        criteria_dict: dict[str, Any] = {}

        # 1. Shadow 기간
        actual["shadow_days"] = perf.shadow_days
        criteria_dict["min_shadow_days"] = criteria.min_shadow_days
        if perf.shadow_days < criteria.min_shadow_days:
            failures.append(
                f"shadow_days {perf.shadow_days} < {criteria.min_shadow_days}"
            )

        # 2. 거래 수
        actual["total_trades"] = perf.total_trades
        criteria_dict["min_shadow_trades"] = criteria.min_shadow_trades
        if perf.total_trades < criteria.min_shadow_trades:
            failures.append(
                f"total_trades {perf.total_trades} < {criteria.min_shadow_trades}"
            )

        # 3. 수익률
        actual["simulated_return_pct"] = perf.simulated_return_pct
        criteria_dict["min_return_pct"] = criteria.min_return_pct
        if perf.simulated_return_pct < criteria.min_return_pct:
            failures.append(
                f"return {perf.simulated_return_pct:.2f}% < {criteria.min_return_pct}%"
            )

        # 4. MDD
        actual["simulated_max_drawdown_pct"] = perf.simulated_max_drawdown_pct
        criteria_dict["max_drawdown_limit_pct"] = criteria.max_drawdown_limit_pct
        if perf.simulated_max_drawdown_pct < criteria.max_drawdown_limit_pct:
            failures.append(
                f"drawdown {perf.simulated_max_drawdown_pct:.2f}% < {criteria.max_drawdown_limit_pct}%"
            )

        # 5. 평균 신뢰도
        actual["avg_confidence"] = perf.avg_confidence
        criteria_dict["min_avg_confidence"] = criteria.min_avg_confidence
        if perf.avg_confidence < criteria.min_avg_confidence:
            failures.append(
                f"avg_confidence {perf.avg_confidence:.2f} < {criteria.min_avg_confidence}"
            )

        # 6. Walk-forward 검증
        if criteria.require_walk_forward_approval:
            actual["walk_forward_approved"] = walk_forward_approved
            actual["walk_forward_consistency"] = walk_forward_consistency
            criteria_dict["require_walk_forward_approval"] = True
            criteria_dict["min_walk_forward_consistency"] = criteria.min_walk_forward_consistency

            if walk_forward_approved is None:
                failures.append("walk_forward 검증 미실행")
            elif not walk_forward_approved:
                failures.append("walk_forward 검증 미통과")
            elif (
                walk_forward_consistency is not None
                and walk_forward_consistency < criteria.min_walk_forward_consistency
            ):
                failures.append(
                    f"walk_forward consistency {walk_forward_consistency:.2f} "
                    f"< {criteria.min_walk_forward_consistency}"
                )

        passed = len(failures) == 0
        return PromotionCheckResult(
            policy_id=policy_id,
            ticker=ticker,
            promotion_type="shadow_to_paper",
            passed=passed,
            criteria=criteria_dict,
            actual=actual,
            failures=failures,
        )

    def evaluate_paper_to_real(
        self,
        policy_id: str,
        ticker: str,
        *,
        paper_days: int = 0,
        paper_trades: int = 0,
        paper_return_pct: float = 0.0,
        paper_max_drawdown_pct: float = 0.0,
        paper_sharpe_ratio: float = 0.0,
        walk_forward_approved: bool | None = None,
    ) -> PromotionCheckResult:
        """Paper → Real 승격 게이트를 평가합니다."""
        criteria = self.real_criteria
        failures: list[str] = []
        actual: dict[str, Any] = {}
        criteria_dict: dict[str, Any] = {}

        # 1. Paper 운용 기간
        actual["paper_days"] = paper_days
        criteria_dict["min_paper_days"] = criteria.min_paper_days
        if paper_days < criteria.min_paper_days:
            failures.append(f"paper_days {paper_days} < {criteria.min_paper_days}")

        # 2. 거래 수
        actual["paper_trades"] = paper_trades
        criteria_dict["min_paper_trades"] = criteria.min_paper_trades
        if paper_trades < criteria.min_paper_trades:
            failures.append(f"paper_trades {paper_trades} < {criteria.min_paper_trades}")

        # 3. 수익률
        actual["paper_return_pct"] = paper_return_pct
        criteria_dict["min_return_pct"] = criteria.min_return_pct
        if paper_return_pct < criteria.min_return_pct:
            failures.append(
                f"return {paper_return_pct:.2f}% < {criteria.min_return_pct}%"
            )

        # 4. MDD
        actual["paper_max_drawdown_pct"] = paper_max_drawdown_pct
        criteria_dict["max_drawdown_limit_pct"] = criteria.max_drawdown_limit_pct
        if paper_max_drawdown_pct < criteria.max_drawdown_limit_pct:
            failures.append(
                f"drawdown {paper_max_drawdown_pct:.2f}% < {criteria.max_drawdown_limit_pct}%"
            )

        # 5. Sharpe ratio
        actual["paper_sharpe_ratio"] = paper_sharpe_ratio
        criteria_dict["min_sharpe_ratio"] = criteria.min_sharpe_ratio
        if paper_sharpe_ratio < criteria.min_sharpe_ratio:
            failures.append(
                f"sharpe {paper_sharpe_ratio:.2f} < {criteria.min_sharpe_ratio}"
            )

        # 6. Walk-forward
        if criteria.require_walk_forward_approval:
            actual["walk_forward_approved"] = walk_forward_approved
            criteria_dict["require_walk_forward_approval"] = True
            if walk_forward_approved is None:
                failures.append("walk_forward 검증 미실행")
            elif not walk_forward_approved:
                failures.append("walk_forward 검증 미통과")

        passed = len(failures) == 0
        return PromotionCheckResult(
            policy_id=policy_id,
            ticker=ticker,
            promotion_type="paper_to_real",
            passed=passed,
            criteria=criteria_dict,
            actual=actual,
            failures=failures,
        )

    # ── 정책 모드 관리 ────────────────────────────────────────────────────

    def get_policy_mode(self, policy_id: str, ticker: str) -> str:
        """정책의 현재 운용 모드를 반환합니다.

        Returns:
            "shadow" | "paper" | "real" | "inactive"
        """
        store = self.policy_store
        registry = store.load_registry()

        # 레지스트리에서 정책 조회
        tp = registry.tickers.get(ticker)
        if not tp:
            return "inactive"

        entry = tp.get_policy(policy_id)
        if not entry:
            return "inactive"

        # 활성 정책이면 paper 또는 real
        if tp.active_policy_id == policy_id:
            if registry.promotion_gate.auto_promote_paper_only:
                return "paper"
            return "real"

        # Shadow 기록이 있으면 shadow
        if policy_id in self._shadow_records and self._shadow_records[policy_id]:
            return "shadow"

        return "inactive"

    def list_shadow_policies(self) -> list[dict[str, Any]]:
        """현재 shadow 모드 중인 정책 목록을 반환합니다."""
        result: list[dict[str, Any]] = []
        for policy_id, records in self._shadow_records.items():
            if not records:
                continue
            tickers = sorted(set(r.ticker for r in records))
            for ticker in tickers:
                perf = self.get_shadow_performance(policy_id, ticker)
                result.append({
                    "policy_id": policy_id,
                    "ticker": ticker,
                    "shadow_days": perf.shadow_days,
                    "total_trades": perf.total_trades,
                    "simulated_return_pct": perf.simulated_return_pct,
                    "avg_confidence": perf.avg_confidence,
                    "first_date": str(perf.first_date) if perf.first_date else None,
                    "last_date": str(perf.last_date) if perf.last_date else None,
                })
        return result

    # ── Shadow 기록 관리 ──────────────────────────────────────────────────

    def clear_shadow_records(self, policy_id: str | None = None) -> int:
        """Shadow 기록을 삭제합니다.

        Args:
            policy_id: 특정 정책만 삭제. None이면 전체 삭제.

        Returns:
            삭제된 레코드 수
        """
        if policy_id:
            removed = len(self._shadow_records.pop(policy_id, []))
            logger.info("Shadow 기록 삭제: policy=%s, count=%d", policy_id, removed)
            return removed

        total = sum(len(v) for v in self._shadow_records.values())
        self._shadow_records.clear()
        logger.info("Shadow 기록 전체 삭제: count=%d", total)
        return total

    def get_shadow_records(
        self,
        policy_id: str,
        ticker: str | None = None,
    ) -> list[dict[str, Any]]:
        """Shadow 기록을 조회합니다."""
        records = self._shadow_records.get(policy_id, [])
        if ticker:
            records = [r for r in records if r.ticker == ticker]
        return [r.model_dump(mode="json") for r in records]
