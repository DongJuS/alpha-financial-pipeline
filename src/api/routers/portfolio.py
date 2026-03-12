"""
src/api/routers/portfolio.py — 포트폴리오 조회 및 설정 라우터
"""

from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from src.api.deps import get_admin_user, get_current_settings, get_current_user
from src.db.queries import (
    fetch_operational_audits,
    fetch_real_trading_audits,
    insert_real_trading_audit,
)
from src.utils.config import Settings
from src.utils.db_client import execute, fetch, fetchrow
from src.utils.performance import compute_trade_performance
from src.utils.readiness import evaluate_real_trading_readiness

router = APIRouter()


class PositionItem(BaseModel):
    ticker: str
    name: str
    quantity: int
    avg_price: int
    current_price: int
    unrealized_pnl: int
    weight_pct: float


class PortfolioResponse(BaseModel):
    total_value: int
    total_pnl: int
    total_pnl_pct: float
    is_paper: bool
    positions: list[PositionItem]


class PerformanceResponse(BaseModel):
    period: str
    return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: Optional[float] = None
    win_rate: float
    total_trades: int
    kospi_benchmark_pct: Optional[float] = None


class PortfolioConfigRequest(BaseModel):
    strategy_blend_ratio: float = Field(ge=0.0, le=1.0)
    max_position_pct: int = Field(ge=1, le=100)
    daily_loss_limit_pct: int = Field(ge=1, le=100)


class TradingModeRequest(BaseModel):
    is_paper: bool
    confirmation_code: str


class ReadinessCheckItem(BaseModel):
    key: str
    ok: bool
    message: str
    severity: str


class ReadinessResponse(BaseModel):
    ready: bool
    critical_ok: bool
    high_ok: bool
    checks: list[ReadinessCheckItem]


class OperationalAuditItem(BaseModel):
    id: int
    audit_type: str
    passed: bool
    summary: str
    details: Optional[dict[str, Any]] = None
    executed_by: Optional[str] = None
    created_at: datetime


class TradingModeAuditItem(BaseModel):
    id: int
    requested_at: datetime
    requested_by_email: Optional[str] = None
    requested_by_user_id: Optional[str] = None
    requested_mode_is_paper: bool
    confirmation_code_ok: bool
    readiness_passed: bool
    readiness_summary: Optional[dict[str, Any]] = None
    applied: bool
    message: Optional[str] = None


class ReadinessAuditResponse(BaseModel):
    operational_audits: list[OperationalAuditItem]
    mode_switch_audits: list[TradingModeAuditItem]


@router.get("/positions", response_model=PortfolioResponse)
async def get_positions(
    _: Annotated[dict, Depends(get_current_user)],
) -> PortfolioResponse:
    """현재 보유 포지션과 포트폴리오 요약을 반환합니다."""
    rows = await fetch(
        """
        SELECT ticker, name, quantity, avg_price, current_price, is_paper
        FROM portfolio_positions
        WHERE quantity > 0
        ORDER BY (quantity * current_price) DESC
        """
    )

    config = await fetchrow("SELECT is_paper_trading FROM portfolio_config LIMIT 1")
    is_paper = config["is_paper_trading"] if config else True

    total_value = sum(r["quantity"] * r["current_price"] for r in rows)
    total_cost = sum(r["quantity"] * r["avg_price"] for r in rows)
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0

    positions = [
        PositionItem(
            ticker=r["ticker"],
            name=r["name"],
            quantity=r["quantity"],
            avg_price=r["avg_price"],
            current_price=r["current_price"],
            unrealized_pnl=r["quantity"] * (r["current_price"] - r["avg_price"]),
            weight_pct=round(
                r["quantity"] * r["current_price"] / total_value * 100, 2
            ) if total_value > 0 else 0.0,
        )
        for r in rows
    ]

    return PortfolioResponse(
        total_value=total_value,
        total_pnl=total_pnl,
        total_pnl_pct=round(total_pnl_pct, 2),
        is_paper=is_paper,
        positions=positions,
    )


@router.get("/history")
async def get_trade_history(
    _: Annotated[dict, Depends(get_current_user)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    ticker: Optional[str] = Query(default=None),
) -> dict:
    """거래 이력을 조회합니다."""
    params: list = []
    where_clauses: list[str] = []

    if ticker:
        params.append(ticker)
        where_clauses.append(f"ticker = ${len(params)}")
    if from_date:
        params.append(from_date)
        where_clauses.append(f"executed_at >= ${len(params)}::date")
    if to_date:
        params.append(to_date)
        where_clauses.append(f"executed_at < (${len(params)}::date + interval '1 day')")

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    offset = (page - 1) * per_page
    params += [per_page, offset]

    rows = await fetch(
        f"""
        SELECT ticker, name, side, quantity, price, amount, signal_source,
               agent_id, is_paper, circuit_breaker,
               to_char(executed_at AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS+09:00') AS executed_at
        FROM trade_history
        {where}
        ORDER BY executed_at DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )

    return {
        "data": [dict(r) for r in rows],
        "meta": {"page": page, "per_page": per_page},
    }


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance(
    _: Annotated[dict, Depends(get_current_user)],
    period: str = Query(
        default="monthly", pattern="^(daily|weekly|monthly|all)$"
    ),
) -> PerformanceResponse:
    """성과 지표 (수익률, MDD, Sharpe 등)를 반환합니다."""
    period_days_map = {"daily": 1, "weekly": 7, "monthly": 30, "all": 99999}
    days = period_days_map[period]

    rows = await fetch(
        """
        SELECT ticker, side, price, quantity, amount, executed_at
        FROM trade_history
        WHERE is_paper = TRUE
          AND executed_at >= NOW() - ($1 * INTERVAL '1 day')
        ORDER BY executed_at
        """,
        days,
    )
    metrics = compute_trade_performance([dict(r) for r in rows])

    return PerformanceResponse(
        period=period,
        return_pct=metrics["return_pct"],
        max_drawdown_pct=metrics["max_drawdown_pct"],
        sharpe_ratio=metrics["sharpe_ratio"],
        win_rate=metrics["win_rate"],
        total_trades=metrics["total_trades"],
        kospi_benchmark_pct=None,
    )


@router.post("/config")
async def update_config(
    body: PortfolioConfigRequest,
    _: Annotated[dict, Depends(get_admin_user)],
) -> dict:
    """전략 블렌드 비율 및 리스크 한도를 업데이트합니다."""
    await execute(
        """
        UPDATE portfolio_config
        SET strategy_blend_ratio = $1,
            max_position_pct = $2,
            daily_loss_limit_pct = $3,
            updated_at = NOW()
        """,
        body.strategy_blend_ratio,
        body.max_position_pct,
        body.daily_loss_limit_pct,
    )
    return {"message": "포트폴리오 설정이 업데이트되었습니다.", "config": body.model_dump()}


@router.post("/trading-mode")
async def update_trading_mode(
    body: TradingModeRequest,
    admin_user: Annotated[dict, Depends(get_admin_user)],
    settings: Annotated[Settings, Depends(get_current_settings)],
) -> dict:
    """페이퍼/실거래 모드를 전환합니다 (관리자 전용)."""
    confirmation_code_ok = body.confirmation_code == settings.real_trading_confirmation_code
    readiness = {"ready": True, "critical_ok": True, "high_ok": True, "checks": []}

    if not body.is_paper:
        readiness = await evaluate_real_trading_readiness()
        if (not confirmation_code_ok) or (not readiness["ready"]):
            message = "실거래 전환 차단: 확인 코드 또는 readiness 점검 실패"
            await insert_real_trading_audit(
                requested_by_email=admin_user.get("email"),
                requested_by_user_id=admin_user.get("sub"),
                requested_mode_is_paper=body.is_paper,
                confirmation_code_ok=confirmation_code_ok,
                readiness_passed=bool(readiness.get("ready")),
                readiness_summary=readiness,
                applied=False,
                message=message,
            )
            return {
                "error": message,
                "confirmation_code_ok": confirmation_code_ok,
                "readiness": readiness,
            }

    await execute(
        "UPDATE portfolio_config SET is_paper_trading = $1, updated_at = NOW()",
        body.is_paper,
    )

    message = f"트레이딩 모드 변경 성공: {'paper' if body.is_paper else 'real'}"
    await insert_real_trading_audit(
        requested_by_email=admin_user.get("email"),
        requested_by_user_id=admin_user.get("sub"),
        requested_mode_is_paper=body.is_paper,
        confirmation_code_ok=confirmation_code_ok,
        readiness_passed=bool(readiness.get("ready")),
        readiness_summary=readiness,
        applied=True,
        message=message,
    )

    mode = "페이퍼 트레이딩" if body.is_paper else "실거래"
    return {"message": f"트레이딩 모드가 '{mode}'으로 변경되었습니다.", "readiness": readiness}


@router.get("/readiness", response_model=ReadinessResponse)
async def get_readiness(
    _: Annotated[dict, Depends(get_admin_user)],
) -> ReadinessResponse:
    """실거래 전환 readiness 점검 결과를 반환합니다."""
    result = await evaluate_real_trading_readiness()
    return ReadinessResponse(
        ready=bool(result["ready"]),
        critical_ok=bool(result["critical_ok"]),
        high_ok=bool(result["high_ok"]),
        checks=[ReadinessCheckItem(**c) for c in result["checks"]],
    )


@router.get("/readiness/audits", response_model=ReadinessAuditResponse)
async def get_readiness_audits(
    _: Annotated[dict, Depends(get_admin_user)],
    limit: int = Query(default=20, ge=1, le=200),
    audit_type: Optional[str] = Query(default=None, pattern="^(security|risk_rules)$"),
) -> ReadinessAuditResponse:
    """운영 감사/실거래 모드 전환 감사 이력을 반환합니다."""
    operational_rows = await fetch_operational_audits(limit=limit, audit_type=audit_type)
    mode_switch_rows = await fetch_real_trading_audits(limit=limit)

    return ReadinessAuditResponse(
        operational_audits=[OperationalAuditItem(**row) for row in operational_rows],
        mode_switch_audits=[TradingModeAuditItem(**row) for row in mode_switch_rows],
    )
