"""
src/utils/strategy_promotion.py — 전략 승격 파이프라인

virtual → paper → real 점진적 승격 로직.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from src.utils.account_scope import AccountScope
from src.utils.config import get_settings
from src.utils.db_client import execute, fetch, fetchrow, fetchval
from src.utils.logging import get_logger
from src.utils.performance import compute_trade_performance

logger = get_logger(__name__)

# 기본 승격 기준
DEFAULT_CRITERIA: dict[str, dict[str, Any]] = {
    "virtual_to_paper": {
        "min_days": 30,
        "min_trades": 20,
        "min_return_pct": 0.0,
        "max_drawdown_pct": -15.0,
        "min_sharpe": 0.5,
    },
    "paper_to_real": {
        "min_days": 60,
        "min_trades": 50,
        "min_return_pct": 5.0,
        "max_drawdown_pct": -10.0,
        "min_sharpe": 1.0,
    },
}

VALID_PROMOTIONS = {
    ("virtual", "paper"),
    ("paper", "real"),
}


@dataclass
class PromotionCheckResult:
    strategy_id: str
    from_mode: str
    to_mode: str
    ready: bool
    criteria: dict[str, Any] = field(default_factory=dict)
    actual: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class PromotionResult:
    success: bool
    strategy_id: str
    from_mode: str
    to_mode: str
    message: str
    check: PromotionCheckResult | None = None


class StrategyPromoter:
    """전략 모드 승격 관리자."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._criteria = self._load_criteria()

    def _load_criteria(self) -> dict[str, dict[str, Any]]:
        import copy
        criteria = copy.deepcopy(DEFAULT_CRITERIA)
        try:
            override = json.loads(self.settings.promotion_criteria_override)
            if isinstance(override, dict):
                for key, vals in override.items():
                    if key in criteria and isinstance(vals, dict):
                        criteria[key].update(vals)
        except (json.JSONDecodeError, TypeError):
            pass
        return criteria

    def get_promotion_criteria(self, from_mode: str, to_mode: str) -> dict[str, Any]:
        """승격 기준을 반환합니다."""
        key = f"{from_mode}_to_{to_mode}"
        return dict(self._criteria.get(key, {}))

    async def evaluate_promotion_readiness(
        self,
        strategy_id: str,
        from_mode: str,
        to_mode: str,
    ) -> PromotionCheckResult:
        """전략의 승격 준비 상태를 평가합니다."""
        if (from_mode, to_mode) not in VALID_PROMOTIONS:
            return PromotionCheckResult(
                strategy_id=strategy_id,
                from_mode=from_mode,
                to_mode=to_mode,
                ready=False,
                message=f"유효하지 않은 승격 경로: {from_mode} → {to_mode}",
            )

        criteria = self.get_promotion_criteria(from_mode, to_mode)
        if not criteria:
            return PromotionCheckResult(
                strategy_id=strategy_id,
                from_mode=from_mode,
                to_mode=to_mode,
                ready=False,
                criteria=criteria,
                message="승격 기준이 정의되지 않았습니다.",
            )

        # 거래 이력 조회
        scope: AccountScope = from_mode  # type: ignore[assignment]
        trade_rows = await self._fetch_strategy_trades(strategy_id, scope)

        # 운용 일수 계산
        trading_days = await self._count_trading_days(strategy_id, scope)

        # 성과 계산
        if trade_rows:
            perf = compute_trade_performance(trade_rows)
        else:
            perf = {
                "return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": None,
                "total_trades": 0,
                "sell_count": 0,
            }

        actual = {
            "trading_days": trading_days,
            "total_trades": perf["total_trades"],
            "return_pct": perf["return_pct"],
            "max_drawdown_pct": perf["max_drawdown_pct"],
            "sharpe_ratio": perf.get("sharpe_ratio"),
        }

        failures: list[str] = []

        if trading_days < criteria.get("min_days", 0):
            failures.append(
                f"운용 일수 부족: {trading_days}일 < {criteria['min_days']}일"
            )

        if perf["total_trades"] < criteria.get("min_trades", 0):
            failures.append(
                f"거래 횟수 부족: {perf['total_trades']}건 < {criteria['min_trades']}건"
            )

        if perf["return_pct"] < criteria.get("min_return_pct", 0.0):
            failures.append(
                f"수익률 미달: {perf['return_pct']:.2f}% < {criteria['min_return_pct']:.2f}%"
            )

        if perf["max_drawdown_pct"] < criteria.get("max_drawdown_pct", -100.0):
            failures.append(
                f"최대 낙폭 초과: {perf['max_drawdown_pct']:.2f}% < {criteria['max_drawdown_pct']:.2f}%"
            )

        sharpe = perf.get("sharpe_ratio")
        min_sharpe = criteria.get("min_sharpe", 0.0)
        if sharpe is None or sharpe < min_sharpe:
            failures.append(
                f"샤프 비율 미달: {sharpe} < {min_sharpe}"
            )

        ready = len(failures) == 0
        message = "승격 준비 완료" if ready else f"승격 기준 미충족 ({len(failures)}건)"

        return PromotionCheckResult(
            strategy_id=strategy_id,
            from_mode=from_mode,
            to_mode=to_mode,
            ready=ready,
            criteria=criteria,
            actual=actual,
            failures=failures,
            message=message,
        )

    async def promote_strategy(
        self,
        strategy_id: str,
        from_mode: str,
        to_mode: str,
        force: bool = False,
        approved_by: str = "system",
    ) -> PromotionResult:
        """전략을 다음 모드로 승격합니다."""
        check = await self.evaluate_promotion_readiness(strategy_id, from_mode, to_mode)

        if not check.ready and not force:
            return PromotionResult(
                success=False,
                strategy_id=strategy_id,
                from_mode=from_mode,
                to_mode=to_mode,
                message=f"승격 기준 미충족: {', '.join(check.failures)}",
                check=check,
            )

        # 전략 모드 업데이트 (STRATEGY_MODES JSON 수정은 환경변수이므로 DB에 기록만)
        await self._record_promotion(
            strategy_id=strategy_id,
            from_mode=from_mode,
            to_mode=to_mode,
            criteria_snapshot=check.criteria,
            actual_snapshot=check.actual,
            approved_by=approved_by,
            forced=force,
        )

        logger.info(
            "전략 승격 완료: %s (%s → %s)%s",
            strategy_id,
            from_mode,
            to_mode,
            " [강제]" if force else "",
        )

        return PromotionResult(
            success=True,
            strategy_id=strategy_id,
            from_mode=from_mode,
            to_mode=to_mode,
            message=f"전략 {strategy_id} 승격 완료: {from_mode} → {to_mode}",
            check=check,
        )

    async def get_all_strategy_status(self) -> list[dict[str, Any]]:
        """모든 전략의 현재 모드와 승격 준비 상태를 반환합니다."""
        strategies = ["A", "B", "RL", "S", "L"]
        result = []

        try:
            modes_json = json.loads(self.settings.strategy_modes)
        except (json.JSONDecodeError, TypeError):
            modes_json = {}

        for sid in strategies:
            active_modes = modes_json.get(sid, [])
            if isinstance(active_modes, str):
                active_modes = [active_modes]

            status_entry: dict[str, Any] = {
                "strategy_id": sid,
                "active_modes": active_modes,
                "promotion_readiness": {},
            }

            # 가능한 승격 경로 평가
            for from_m, to_m in VALID_PROMOTIONS:
                if from_m in active_modes and to_m not in active_modes:
                    check = await self.evaluate_promotion_readiness(sid, from_m, to_m)
                    status_entry["promotion_readiness"][f"{from_m}_to_{to_m}"] = {
                        "ready": check.ready,
                        "failures": check.failures,
                        "actual": check.actual,
                    }

            result.append(status_entry)

        return result

    async def _fetch_strategy_trades(
        self, strategy_id: str, scope: AccountScope
    ) -> list[dict]:
        """전략별 거래 이력을 조회합니다."""
        rows = await fetch(
            """
            SELECT ticker, side, price, quantity, amount, executed_at
            FROM trade_history
            WHERE account_scope = $1
              AND (strategy_id = $2 OR ($2 IS NULL AND strategy_id IS NULL))
            ORDER BY executed_at
            """,
            scope,
            strategy_id,
        )
        return [dict(r) for r in rows]

    async def _count_trading_days(
        self, strategy_id: str, scope: AccountScope
    ) -> int:
        """전략의 운용 일수를 계산합니다."""
        count = await fetchval(
            """
            SELECT COUNT(DISTINCT executed_at::date)
            FROM trade_history
            WHERE account_scope = $1
              AND (strategy_id = $2 OR ($2 IS NULL AND strategy_id IS NULL))
            """,
            scope,
            strategy_id,
        )
        return int(count or 0)

    async def _record_promotion(
        self,
        strategy_id: str,
        from_mode: str,
        to_mode: str,
        criteria_snapshot: dict,
        actual_snapshot: dict,
        approved_by: str,
        forced: bool = False,
    ) -> None:
        """승격 기록을 DB에 저장합니다."""
        await execute(
            """
            INSERT INTO strategy_promotions (
                strategy_id, from_mode, to_mode,
                criteria_snapshot, actual_snapshot,
                approved_by, forced, promoted_at
            ) VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, NOW())
            """,
            strategy_id,
            from_mode,
            to_mode,
            json.dumps(criteria_snapshot, ensure_ascii=False),
            json.dumps(actual_snapshot, ensure_ascii=False),
            approved_by,
            forced,
        )
