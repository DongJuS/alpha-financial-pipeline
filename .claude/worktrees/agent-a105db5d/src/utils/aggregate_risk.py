"""
src/utils/aggregate_risk.py — 전략 간 합산 리스크 모니터링

동일 종목 다중 전략 매수 시 총 노출 관리.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.utils.config import get_settings
from src.utils.db_client import execute, fetch, fetchval
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ExposureInfo:
    ticker: str
    total_quantity: int
    total_market_value: int
    strategies: list[dict[str, Any]]
    exposure_pct: float
    over_limit: bool


@dataclass
class RiskSummary:
    total_aum: int
    strategy_allocations: dict[str, int]
    top_exposures: list[ExposureInfo]
    overlap_count: int
    max_overlap_ticker: str | None
    warnings: list[str] = field(default_factory=list)


class AggregateRiskMonitor:
    """전략 간 합산 리스크를 모니터링합니다."""

    def __init__(self) -> None:
        settings = get_settings()
        self.max_single_stock_pct = settings.max_single_stock_exposure_pct
        self.max_overlap_count = settings.max_strategy_overlap_count

    async def check_total_exposure(self, ticker: str) -> ExposureInfo:
        """특정 종목의 전체 전략 합산 노출을 조회합니다."""
        rows = await fetch(
            """
            SELECT
                ticker,
                strategy_id,
                account_scope,
                quantity,
                current_price,
                (quantity * current_price) AS market_value
            FROM portfolio_positions
            WHERE ticker = $1
              AND quantity > 0
            ORDER BY strategy_id NULLS FIRST
            """,
            ticker,
        )

        strategies = []
        total_qty = 0
        total_value = 0

        for r in rows:
            row = dict(r)
            qty = int(row["quantity"])
            mv = int(row["market_value"])
            total_qty += qty
            total_value += mv
            strategies.append({
                "strategy_id": row.get("strategy_id") or "default",
                "account_scope": row["account_scope"],
                "quantity": qty,
                "market_value": mv,
            })

        total_aum = await self._total_aum()
        exposure_pct = (total_value / total_aum * 100) if total_aum > 0 else 0.0

        return ExposureInfo(
            ticker=ticker,
            total_quantity=total_qty,
            total_market_value=total_value,
            strategies=strategies,
            exposure_pct=round(exposure_pct, 2),
            over_limit=exposure_pct > self.max_single_stock_pct,
        )

    async def check_strategy_correlation(self) -> dict[str, Any]:
        """전략 간 종목 중복도를 분석합니다."""
        rows = await fetch(
            """
            SELECT
                ticker,
                COUNT(DISTINCT COALESCE(strategy_id, 'default')) AS strategy_count,
                ARRAY_AGG(DISTINCT COALESCE(strategy_id, 'default')) AS strategies
            FROM portfolio_positions
            WHERE quantity > 0
            GROUP BY ticker
            HAVING COUNT(DISTINCT COALESCE(strategy_id, 'default')) > 1
            ORDER BY strategy_count DESC
            """
        )

        overlaps = []
        for r in rows:
            row = dict(r)
            overlaps.append({
                "ticker": row["ticker"],
                "strategy_count": int(row["strategy_count"]),
                "strategies": list(row["strategies"]),
            })

        return {
            "overlap_tickers": len(overlaps),
            "details": overlaps,
            "max_overlap": overlaps[0] if overlaps else None,
        }

    async def get_risk_summary(self) -> RiskSummary:
        """전체 리스크 요약을 반환합니다."""
        total_aum = await self._total_aum()
        allocations = await self._strategy_allocations()
        correlation = await self.check_strategy_correlation()

        # 상위 노출 종목
        top_rows = await fetch(
            """
            SELECT
                ticker,
                SUM(quantity) AS total_qty,
                SUM(quantity * current_price) AS total_value,
                COUNT(DISTINCT COALESCE(strategy_id, 'default')) AS strat_count
            FROM portfolio_positions
            WHERE quantity > 0
            GROUP BY ticker
            ORDER BY total_value DESC
            LIMIT 10
            """
        )

        top_exposures = []
        warnings: list[str] = []

        for r in top_rows:
            row = dict(r)
            mv = int(row["total_value"])
            pct = (mv / total_aum * 100) if total_aum > 0 else 0.0
            over = pct > self.max_single_stock_pct

            top_exposures.append(ExposureInfo(
                ticker=row["ticker"],
                total_quantity=int(row["total_qty"]),
                total_market_value=mv,
                strategies=[],
                exposure_pct=round(pct, 2),
                over_limit=over,
            ))

            if over:
                warnings.append(
                    f"{row['ticker']}: 단일 종목 노출 {pct:.1f}% > 한도 {self.max_single_stock_pct}%"
                )

        overlap_details = correlation.get("details", [])
        for ovl in overlap_details:
            if ovl["strategy_count"] > self.max_overlap_count:
                warnings.append(
                    f"{ovl['ticker']}: {ovl['strategy_count']}개 전략 중복"
                    f" (한도 {self.max_overlap_count}개)"
                )

        max_overlap = correlation.get("max_overlap")
        max_overlap_ticker = max_overlap["ticker"] if max_overlap else None

        return RiskSummary(
            total_aum=total_aum,
            strategy_allocations=allocations,
            top_exposures=top_exposures,
            overlap_count=correlation.get("overlap_tickers", 0),
            max_overlap_ticker=max_overlap_ticker,
            warnings=warnings,
        )

    async def record_risk_snapshot(self) -> None:
        """현재 리스크 상태를 스냅샷으로 DB에 기록합니다."""
        summary = await self.get_risk_summary()
        data = {
            "total_aum": summary.total_aum,
            "strategy_allocations": summary.strategy_allocations,
            "overlap_count": summary.overlap_count,
            "max_overlap_ticker": summary.max_overlap_ticker,
            "warnings": summary.warnings,
            "top_exposures": [
                {
                    "ticker": e.ticker,
                    "total_market_value": e.total_market_value,
                    "exposure_pct": e.exposure_pct,
                    "over_limit": e.over_limit,
                }
                for e in summary.top_exposures
            ],
        }
        await execute(
            """
            INSERT INTO aggregate_risk_snapshots (risk_data, snapshot_at)
            VALUES ($1::jsonb, NOW())
            """,
            json.dumps(data, ensure_ascii=False),
        )

    async def _total_aum(self) -> int:
        """전체 운용 자산 총액을 계산합니다."""
        val = await fetchval(
            """
            SELECT COALESCE(SUM(quantity * current_price), 0)
            FROM portfolio_positions
            WHERE quantity > 0
            """
        )
        return int(val or 0)

    async def _strategy_allocations(self) -> dict[str, int]:
        """전략별 운용 자산 현황을 반환합니다."""
        rows = await fetch(
            """
            SELECT
                COALESCE(strategy_id, 'default') AS sid,
                SUM(quantity * current_price) AS total_value
            FROM portfolio_positions
            WHERE quantity > 0
            GROUP BY strategy_id
            ORDER BY total_value DESC
            """
        )
        return {str(r["sid"]): int(r["total_value"]) for r in rows}
