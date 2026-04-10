"""
src/api/routers/backtest.py — Backtest REST API

백테스트 실행 결과를 조회하는 읽기 전용 API.
  GET /runs              — 실행 목록 (페이지네이션 + strategy 필터)
  GET /runs/{run_id}     — 실행 상세 (설정 + 지표)
  GET /runs/{run_id}/daily — 일별 포트폴리오 스냅샷
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.deps import get_current_user
from src.utils.db_client import fetch, fetchrow, fetchval

router = APIRouter()


# ── Response Models ──────────────────────────────────────────────────────


class BacktestRunSummary(BaseModel):
    id: int
    ticker: str
    strategy: str
    test_start: str
    test_end: str
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    created_at: str


class BacktestRunDetail(BacktestRunSummary):
    train_start: str
    train_end: str
    initial_capital: int
    commission_rate_pct: float
    tax_rate_pct: float
    slippage_bps: int
    annual_return_pct: float
    avg_holding_days: float
    baseline_return_pct: float
    excess_return_pct: float


class BacktestDailyItem(BaseModel):
    date: str
    close_price: float
    cash: float
    position_qty: int
    position_value: float
    portfolio_value: float
    daily_return_pct: float


# ── Helpers ──────────────────────────────────────────────────────────────


def _row_to_summary(row: dict) -> dict:
    return BacktestRunSummary(
        id=row["id"],
        ticker=row["ticker"],
        strategy=row["strategy"],
        test_start=str(row["test_start"]),
        test_end=str(row["test_end"]),
        total_return_pct=float(row["total_return_pct"] or 0),
        sharpe_ratio=float(row["sharpe_ratio"] or 0),
        max_drawdown_pct=float(row["max_drawdown_pct"] or 0),
        win_rate=float(row["win_rate"] or 0),
        total_trades=row["total_trades"] or 0,
        created_at=str(row["created_at"]),
    ).model_dump()


def _row_to_detail(row: dict) -> dict:
    return BacktestRunDetail(
        id=row["id"],
        ticker=row["ticker"],
        strategy=row["strategy"],
        train_start=str(row["train_start"]),
        train_end=str(row["train_end"]),
        test_start=str(row["test_start"]),
        test_end=str(row["test_end"]),
        initial_capital=row["initial_capital"],
        commission_rate_pct=float(row["commission_rate_pct"]),
        tax_rate_pct=float(row["tax_rate_pct"]),
        slippage_bps=row["slippage_bps"],
        total_return_pct=float(row["total_return_pct"] or 0),
        annual_return_pct=float(row["annual_return_pct"] or 0),
        sharpe_ratio=float(row["sharpe_ratio"] or 0),
        max_drawdown_pct=float(row["max_drawdown_pct"] or 0),
        win_rate=float(row["win_rate"] or 0),
        total_trades=row["total_trades"] or 0,
        avg_holding_days=float(row["avg_holding_days"] or 0),
        baseline_return_pct=float(row["baseline_return_pct"] or 0),
        excess_return_pct=float(row["excess_return_pct"] or 0),
        created_at=str(row["created_at"]),
    ).model_dump()


def _row_to_daily(row: dict) -> dict:
    return BacktestDailyItem(
        date=str(row["date"]),
        close_price=float(row["close_price"]),
        cash=float(row["cash"]),
        position_qty=row["position_qty"],
        position_value=float(row["position_value"]),
        portfolio_value=float(row["portfolio_value"]),
        daily_return_pct=float(row["daily_return_pct"] or 0),
    ).model_dump()


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("/runs", summary="백테스트 실행 목록")
async def list_backtest_runs(
    _: Annotated[dict, Depends(get_current_user)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    strategy: Optional[str] = Query(default=None, pattern="^(RL|A|B|BLEND)$"),
) -> dict:
    """백테스트 실행 목록을 페이지네이션으로 조회합니다."""
    offset = (page - 1) * per_page

    if strategy:
        total = await fetchval(
            "SELECT COUNT(*) FROM backtest_runs WHERE strategy = $1",
            strategy,
        )
        rows = await fetch(
            "SELECT * FROM backtest_runs WHERE strategy = $1 "
            "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            strategy,
            per_page,
            offset,
        )
    else:
        total = await fetchval("SELECT COUNT(*) FROM backtest_runs")
        rows = await fetch(
            "SELECT * FROM backtest_runs "
            "ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            per_page,
            offset,
        )

    return {
        "data": [_row_to_summary(dict(r)) for r in rows],
        "meta": {"page": page, "per_page": per_page, "total": total or 0},
    }


@router.get("/runs/{run_id}", summary="백테스트 실행 상세")
async def get_backtest_run(
    run_id: int,
    _: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """백테스트 실행의 상세 정보(설정 + 지표)를 조회합니다."""
    row = await fetchrow("SELECT * FROM backtest_runs WHERE id = $1", run_id)
    if not row:
        raise HTTPException(status_code=404, detail="백테스트 실행을 찾을 수 없습니다.")
    return _row_to_detail(dict(row))


@router.get("/runs/{run_id}/daily", summary="백테스트 일별 스냅샷")
async def get_backtest_daily(
    run_id: int,
    _: Annotated[dict, Depends(get_current_user)],
) -> list[dict]:
    """백테스트 일별 포트폴리오 스냅샷을 조회합니다."""
    exists = await fetchrow("SELECT id FROM backtest_runs WHERE id = $1", run_id)
    if not exists:
        raise HTTPException(status_code=404, detail="백테스트 실행을 찾을 수 없습니다.")

    rows = await fetch(
        "SELECT date, close_price, cash, position_qty, position_value, "
        "portfolio_value, daily_return_pct "
        "FROM backtest_daily WHERE run_id = $1 ORDER BY date",
        run_id,
    )
    return [_row_to_daily(dict(r)) for r in rows]
