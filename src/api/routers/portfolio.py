"""
src/api/routers/portfolio.py — 포트폴리오 조회 및 설정 라우터
"""

from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from src.api.deps import get_admin_user, get_current_settings, get_current_user
from src.db.queries import (
    fetch_latest_paper_trading_run,
    fetch_operational_audits,
    fetch_real_trading_audits,
    insert_real_trading_audit,
)
from src.services.paper_trading import (
    build_account_overview,
    build_account_snapshot_series,
    build_broker_order_activity,
)
from src.utils.account_scope import is_paper_scope, normalize_account_scope
from src.utils.config import Settings
from src.utils.db_client import execute, fetch, fetchrow
from src.utils.market_hours import MARKET_HOURS_ENFORCED, market_session_status
from src.utils.performance import compute_trade_performance
from src.utils.readiness import evaluate_real_trading_readiness

router = APIRouter()
MODE_PATTERN = "^(current|paper|real)$"


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


class PerformanceSeriesItem(BaseModel):
    date: str
    portfolio_return_pct: float
    benchmark_return_pct: Optional[float] = None
    realized_pnl_cum: int
    trade_count: int


class PerformanceSeriesResponse(BaseModel):
    period: str
    points: list[PerformanceSeriesItem]


class PaperTradingRunItem(BaseModel):
    scenario: str
    simulated_days: int
    trade_count: int
    return_pct: float
    benchmark_return_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    passed: bool
    summary: Optional[str] = None
    created_at: datetime


class PaperTradingOverviewResponse(BaseModel):
    broker: str
    account_label: str
    current_mode_is_paper: bool
    active_days_120d: int
    trade_count_120d: int
    traded_tickers_120d: int
    last_executed_at: Optional[str] = None
    latest_run: Optional[PaperTradingRunItem] = None


class AccountOverviewResponse(BaseModel):
    account_scope: str
    broker_name: str
    account_label: str
    base_currency: str
    seed_capital: int
    cash_balance: int
    buying_power: int
    position_market_value: int
    total_equity: int
    realized_pnl: int
    unrealized_pnl: int
    total_pnl: int
    total_pnl_pct: float
    position_count: int
    last_snapshot_at: Optional[datetime] = None


class BrokerOrderItem(BaseModel):
    client_order_id: str
    account_scope: str
    broker_name: str
    ticker: str
    name: str
    side: str
    order_type: str
    requested_quantity: int
    requested_price: int
    filled_quantity: int
    avg_fill_price: Optional[int] = None
    status: str
    signal_source: Optional[str] = None
    agent_id: Optional[str] = None
    broker_order_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    requested_at: datetime
    filled_at: Optional[datetime] = None


class BrokerOrderListResponse(BaseModel):
    account_scope: str
    data: list[BrokerOrderItem]


class AccountSnapshotItem(BaseModel):
    account_scope: str
    cash_balance: int
    buying_power: int
    position_market_value: int
    total_equity: int
    realized_pnl: int
    unrealized_pnl: int
    position_count: int
    snapshot_source: str
    snapshot_at: Optional[datetime] = None


class AccountSnapshotSeriesResponse(BaseModel):
    account_scope: str
    points: list[AccountSnapshotItem]


class PortfolioConfigRequest(BaseModel):
    strategy_blend_ratio: float = Field(ge=0.0, le=1.0)
    max_position_pct: int = Field(ge=1, le=100)
    daily_loss_limit_pct: int = Field(ge=1, le=100)


class TradingModeRequest(BaseModel):
    enable_paper_trading: bool
    enable_real_trading: bool
    primary_account_scope: str = Field(pattern="^(paper|real)$")
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
    requested_paper_enabled: bool
    requested_real_enabled: bool
    requested_primary_account_scope: str
    confirmation_code_ok: bool
    readiness_passed: bool
    readiness_summary: Optional[dict[str, Any]] = None
    applied: bool
    message: Optional[str] = None


class ReadinessAuditResponse(BaseModel):
    operational_audits: list[OperationalAuditItem]
    mode_switch_audits: list[TradingModeAuditItem]


async def _resolve_mode_is_paper(mode: str) -> bool:
    return is_paper_scope(await _resolve_mode_account_scope(mode))


async def _resolve_mode_account_scope(mode: str) -> str:
    if mode == "paper":
        return "paper"
    if mode == "real":
        return "real"

    config = await fetchrow(
        """
        SELECT is_paper_trading, enable_paper_trading, enable_real_trading, primary_account_scope
        FROM portfolio_config
        LIMIT 1
        """
    )
    if not config:
        return "paper"
    cfg = dict(config)

    primary_scope = normalize_account_scope(cfg.get("primary_account_scope"))
    if primary_scope == "paper" and bool(cfg.get("enable_paper_trading", True)):
        return "paper"
    if primary_scope == "real" and bool(cfg.get("enable_real_trading", False)):
        return "real"
    if bool(cfg.get("enable_paper_trading", True)):
        return "paper"
    if bool(cfg.get("enable_real_trading", False)):
        return "real"
    return normalize_account_scope("paper" if bool(cfg["is_paper_trading"]) else "real")


def _period_to_days(period: str) -> int:
    period_days_map = {"daily": 1, "weekly": 7, "monthly": 30, "all": 99999}
    return period_days_map[period]


@router.get("/positions", response_model=PortfolioResponse)
async def get_positions(
    _: Annotated[dict, Depends(get_current_user)],
    mode: str = Query(default="current", pattern=MODE_PATTERN),
) -> PortfolioResponse:
    """현재 보유 포지션과 포트폴리오 요약을 반환합니다."""
    account_scope = await _resolve_mode_account_scope(mode)
    is_paper = account_scope == "paper"
    rows = await fetch(
        """
        SELECT ticker, name, quantity, avg_price, current_price, is_paper, account_scope
        FROM portfolio_positions
        WHERE quantity > 0
          AND account_scope = $1
        ORDER BY (quantity * current_price) DESC
        """,
        account_scope,
    )

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
    mode: str = Query(default="current", pattern=MODE_PATTERN),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    ticker: Optional[str] = Query(default=None),
) -> dict:
    """거래 이력을 조회합니다."""
    account_scope = await _resolve_mode_account_scope(mode)
    params: list = [account_scope]
    where_clauses: list[str] = [f"account_scope = ${len(params)}"]

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
               agent_id, is_paper, account_scope, circuit_breaker,
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
    mode: str = Query(default="current", pattern=MODE_PATTERN),
) -> PerformanceResponse:
    """성과 지표 (수익률, MDD, Sharpe 등)를 반환합니다."""
    days = _period_to_days(period)
    account_scope = await _resolve_mode_account_scope(mode)

    rows = await fetch(
        """
        SELECT ticker, side, price, quantity, amount, executed_at
        FROM trade_history
        WHERE account_scope = $1
          AND executed_at >= NOW() - ($2 * INTERVAL '1 day')
        ORDER BY executed_at
        """,
        account_scope,
        days,
    )
    metrics = compute_trade_performance([dict(r) for r in rows])
    benchmark_rows = await fetch(
        """
        SELECT
            (timestamp_kst AT TIME ZONE 'Asia/Seoul')::date AS trade_date,
            AVG(close)::float AS avg_close
        FROM market_data
        WHERE interval = 'daily'
          AND market = 'KOSPI'
          AND timestamp_kst >= NOW() - ($1 * INTERVAL '1 day')
        GROUP BY (timestamp_kst AT TIME ZONE 'Asia/Seoul')::date
        ORDER BY trade_date
        """,
        days,
    )
    benchmark_pct = None
    if benchmark_rows:
        first_close = float(benchmark_rows[0]["avg_close"])
        last_close = float(benchmark_rows[-1]["avg_close"])
        if first_close > 0:
            benchmark_pct = round(((last_close / first_close) - 1.0) * 100, 2)

    return PerformanceResponse(
        period=period,
        return_pct=metrics["return_pct"],
        max_drawdown_pct=metrics["max_drawdown_pct"],
        sharpe_ratio=metrics["sharpe_ratio"],
        win_rate=metrics["win_rate"],
        total_trades=metrics["total_trades"],
        kospi_benchmark_pct=benchmark_pct,
    )


@router.get("/performance-series", response_model=PerformanceSeriesResponse)
async def get_performance_series(
    _: Annotated[dict, Depends(get_current_user)],
    period: str = Query(
        default="monthly", pattern="^(daily|weekly|monthly|all)$"
    ),
    mode: str = Query(default="current", pattern=MODE_PATTERN),
) -> PerformanceSeriesResponse:
    """일자별 누적 성과 시계열(포트폴리오 vs KOSPI 대용 벤치마크)을 반환합니다."""
    from src.utils.performance import compute_benchmark_series, compute_trade_performance_series

    days = _period_to_days(period)
    account_scope = await _resolve_mode_account_scope(mode)

    trade_rows = await fetch(
        """
        SELECT ticker, side, price, quantity, amount, executed_at
        FROM trade_history
        WHERE account_scope = $1
          AND executed_at >= NOW() - ($2 * INTERVAL '1 day')
        ORDER BY executed_at
        """,
        account_scope,
        days,
    )
    benchmark_rows = await fetch(
        """
        SELECT
            (timestamp_kst AT TIME ZONE 'Asia/Seoul')::date AS trade_date,
            AVG(close)::float AS avg_close
        FROM market_data
        WHERE interval = 'daily'
          AND market = 'KOSPI'
          AND timestamp_kst >= NOW() - ($1 * INTERVAL '1 day')
        GROUP BY (timestamp_kst AT TIME ZONE 'Asia/Seoul')::date
        ORDER BY trade_date
        """,
        days,
    )

    portfolio_series = compute_trade_performance_series([dict(r) for r in trade_rows])
    benchmark_series = compute_benchmark_series([dict(r) for r in benchmark_rows])
    benchmark_by_date = {row["date"]: row["benchmark_return_pct"] for row in benchmark_series}

    points = [
        PerformanceSeriesItem(
            date=item["date"],
            portfolio_return_pct=item["portfolio_return_pct"],
            benchmark_return_pct=benchmark_by_date.get(item["date"]),
            realized_pnl_cum=item["realized_pnl_cum"],
            trade_count=item["trade_count"],
        )
        for item in portfolio_series
    ]
    return PerformanceSeriesResponse(period=period, points=points)


@router.get("/paper-overview", response_model=PaperTradingOverviewResponse)
async def get_paper_trading_overview(
    _: Annotated[dict, Depends(get_current_user)],
) -> PaperTradingOverviewResponse:
    """한국투자증권 모의투자 운영 개요를 반환합니다."""
    current_mode_is_paper = await _resolve_mode_is_paper("current")
    account_row = await fetchrow(
        """
        SELECT broker_name, account_label
        FROM trading_accounts
        WHERE account_scope = 'paper'
        LIMIT 1
        """
    )
    paper_stats = await fetchrow(
        """
        SELECT
            COUNT(DISTINCT (executed_at AT TIME ZONE 'Asia/Seoul')::date) AS active_days,
            COUNT(*) AS trade_count,
            COUNT(DISTINCT ticker) AS traded_tickers,
            to_char(
                MAX(executed_at) AT TIME ZONE 'Asia/Seoul',
                'YYYY-MM-DD"T"HH24:MI:SS+09:00'
            ) AS last_executed_at
        FROM trade_history
        WHERE account_scope = 'paper'
          AND executed_at >= NOW() - INTERVAL '120 day'
        """
    )
    latest_run = await fetch_latest_paper_trading_run("baseline")

    latest_run_item = (
        PaperTradingRunItem(
            scenario=str(latest_run["scenario"]),
            simulated_days=int(latest_run["simulated_days"] or 0),
            trade_count=int(latest_run["trade_count"] or 0),
            return_pct=float(latest_run["return_pct"] or 0),
            benchmark_return_pct=float(latest_run["benchmark_return_pct"]) if latest_run.get("benchmark_return_pct") is not None else None,
            max_drawdown_pct=float(latest_run["max_drawdown_pct"]) if latest_run.get("max_drawdown_pct") is not None else None,
            sharpe_ratio=float(latest_run["sharpe_ratio"]) if latest_run.get("sharpe_ratio") is not None else None,
            passed=bool(latest_run["passed"]),
            summary=latest_run.get("summary"),
            created_at=latest_run["created_at"],
        )
        if latest_run
        else None
    )

    return PaperTradingOverviewResponse(
        broker=str(account_row["broker_name"]) if account_row else "한국투자증권 KIS",
        account_label=str(account_row["account_label"]) if account_row else "KIS 모의투자 계좌",
        current_mode_is_paper=current_mode_is_paper,
        active_days_120d=int(paper_stats["active_days"] or 0) if paper_stats else 0,
        trade_count_120d=int(paper_stats["trade_count"] or 0) if paper_stats else 0,
        traded_tickers_120d=int(paper_stats["traded_tickers"] or 0) if paper_stats else 0,
        last_executed_at=paper_stats["last_executed_at"] if paper_stats else None,
        latest_run=latest_run_item,
    )


@router.get("/account-overview", response_model=AccountOverviewResponse)
async def get_account_overview(
    _: Annotated[dict, Depends(get_current_user)],
    mode: str = Query(default="current", pattern=MODE_PATTERN),
) -> AccountOverviewResponse:
    account_scope = await _resolve_mode_account_scope(mode)
    payload = await build_account_overview(account_scope)
    return AccountOverviewResponse(**payload)


@router.get("/orders", response_model=BrokerOrderListResponse)
async def get_broker_orders(
    _: Annotated[dict, Depends(get_current_user)],
    mode: str = Query(default="current", pattern=MODE_PATTERN),
    limit: int = Query(default=50, ge=1, le=200),
) -> BrokerOrderListResponse:
    account_scope = await _resolve_mode_account_scope(mode)
    rows = await build_broker_order_activity(account_scope, limit=limit)
    return BrokerOrderListResponse(
        account_scope=account_scope,
        data=[BrokerOrderItem(**row) for row in rows],
    )


@router.get("/account-snapshots", response_model=AccountSnapshotSeriesResponse)
async def get_account_snapshots(
    _: Annotated[dict, Depends(get_current_user)],
    mode: str = Query(default="current", pattern=MODE_PATTERN),
    limit: int = Query(default=30, ge=1, le=365),
) -> AccountSnapshotSeriesResponse:
    account_scope = await _resolve_mode_account_scope(mode)
    rows = await build_account_snapshot_series(account_scope, limit=limit)
    return AccountSnapshotSeriesResponse(
        account_scope=account_scope,
        points=[AccountSnapshotItem(**row) for row in rows],
    )


@router.get("/config")
async def get_config(
    _: Annotated[dict, Depends(get_admin_user)],
) -> dict:
    """현재 포트폴리오 운영 설정을 조회합니다."""
    market_status = await market_session_status()
    row = await fetchrow(
        """
        SELECT
            strategy_blend_ratio,
            max_position_pct,
            daily_loss_limit_pct,
            is_paper_trading,
            enable_paper_trading,
            enable_real_trading,
            primary_account_scope
        FROM portfolio_config
        LIMIT 1
        """
    )
    if not row:
        return {
            "strategy_blend_ratio": 0.5,
            "max_position_pct": 20,
            "daily_loss_limit_pct": 3,
            "is_paper_trading": True,
            "enable_paper_trading": True,
            "enable_real_trading": False,
            "primary_account_scope": "paper",
            "market_hours_enforced": MARKET_HOURS_ENFORCED,
            "market_status": market_status,
        }
    payload = dict(row)
    payload["is_paper_trading"] = normalize_account_scope(payload["primary_account_scope"]) == "paper"
    payload["market_hours_enforced"] = MARKET_HOURS_ENFORCED
    payload["market_status"] = market_status
    return payload


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
    """페이퍼/실거래 실행 계좌를 업데이트합니다 (관리자 전용)."""
    if not body.enable_paper_trading and not body.enable_real_trading:
        return {"error": "paper 또는 real 중 최소 하나는 활성화해야 합니다."}

    primary_scope = normalize_account_scope(body.primary_account_scope)
    if primary_scope == "paper" and not body.enable_paper_trading:
        return {"error": "primary_account_scope=paper 이면 paper 실행이 활성화되어야 합니다."}
    if primary_scope == "real" and not body.enable_real_trading:
        return {"error": "primary_account_scope=real 이면 real 실행이 활성화되어야 합니다."}

    confirmation_code_ok = body.confirmation_code == settings.real_trading_confirmation_code
    readiness = {"ready": True, "critical_ok": True, "high_ok": True, "checks": []}

    if body.enable_real_trading:
        readiness = await evaluate_real_trading_readiness()
        if (not confirmation_code_ok) or (not readiness["ready"]):
            message = "실거래 활성화 차단: 확인 코드 또는 readiness 점검 실패"
            await insert_real_trading_audit(
                requested_by_email=admin_user.get("email"),
                requested_by_user_id=admin_user.get("sub"),
                requested_mode_is_paper=(primary_scope == "paper"),
                requested_paper_enabled=body.enable_paper_trading,
                requested_real_enabled=body.enable_real_trading,
                requested_primary_account_scope=primary_scope,
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
        """
        UPDATE portfolio_config
        SET is_paper_trading = $1,
            enable_paper_trading = $2,
            enable_real_trading = $3,
            primary_account_scope = $4,
            updated_at = NOW()
        """,
        primary_scope == "paper",
        body.enable_paper_trading,
        body.enable_real_trading,
        primary_scope,
    )

    message = (
        "트레이딩 실행 계좌 변경 성공: "
        f"paper={'on' if body.enable_paper_trading else 'off'}, "
        f"real={'on' if body.enable_real_trading else 'off'}, "
        f"primary={primary_scope}"
    )
    await insert_real_trading_audit(
        requested_by_email=admin_user.get("email"),
        requested_by_user_id=admin_user.get("sub"),
        requested_mode_is_paper=(primary_scope == "paper"),
        requested_paper_enabled=body.enable_paper_trading,
        requested_real_enabled=body.enable_real_trading,
        requested_primary_account_scope=primary_scope,
        confirmation_code_ok=confirmation_code_ok,
        readiness_passed=bool(readiness.get("ready")),
        readiness_summary=readiness,
        applied=True,
        message=message,
    )

    current = "페이퍼 우선" if primary_scope == "paper" else "실거래 우선"
    return {
        "message": (
            f"실행 계좌 설정이 저장되었습니다. "
            f"(paper={'on' if body.enable_paper_trading else 'off'}, "
            f"real={'on' if body.enable_real_trading else 'off'}, primary={current})"
        ),
        "readiness": readiness,
    }


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
    audit_type: Optional[str] = Query(default=None, pattern="^(security|risk_rules|paper_reconciliation)$"),
) -> ReadinessAuditResponse:
    """운영 감사/실거래 모드 전환 감사 이력을 반환합니다."""
    operational_rows = await fetch_operational_audits(limit=limit, audit_type=audit_type)
    mode_switch_rows = await fetch_real_trading_audits(limit=limit)

    return ReadinessAuditResponse(
        operational_audits=[OperationalAuditItem(**row) for row in operational_rows],
        mode_switch_audits=[TradingModeAuditItem(**row) for row in mode_switch_rows],
    )
