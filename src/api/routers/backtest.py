"""
src/api/routers/backtest.py — 백테스트 시뮬레이션 API 라우터

과거 OHLCV 데이터를 기반으로 전략별 가상 트레이딩 백테스트를
실행하고 결과를 조회합니다.
"""

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.api.deps import get_current_user
from src.services.backtest_engine import BacktestConfig, BacktestEngine, run_backtest_from_db
from src.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ── Request / Response 모델 ──────────────────────────────────────────────────


class BacktestRunRequest(BaseModel):
    """백테스트 실행 요청."""

    strategy_id: str = Field(
        default="A",
        description="전략 ID (A, B, RL, S, L)",
    )
    start_date: str = Field(
        ...,
        description="시작 날짜 (YYYY-MM-DD)",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    end_date: str = Field(
        ...,
        description="종료 날짜 (YYYY-MM-DD)",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    tickers: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="백테스트 대상 종목 코드 리스트 (최대 20개)",
    )
    initial_capital: int = Field(
        default=10_000_000,
        ge=1_000_000,
        le=1_000_000_000,
        description="초기 자본금 (원)",
    )
    slippage_bps: int = Field(
        default=5,
        ge=0,
        le=100,
        description="슬리피지 (bps)",
    )
    commission_bps: int = Field(
        default=15,
        ge=0,
        le=100,
        description="수수료 (bps)",
    )
    max_position_pct: float = Field(
        default=20.0,
        gt=0,
        le=100,
        description="단일 종목 최대 비중 (%)",
    )
    signal_source: str = Field(
        default="rule",
        description="시그널 소스 (rule, momentum, mean_reversion, random)",
    )


class BacktestOrderItem(BaseModel):
    """백테스트 주문 기록."""

    date: str
    ticker: str
    side: str
    quantity: int
    price: int
    amount: int
    slippage_cost: int
    commission: int


class BacktestSnapshotItem(BaseModel):
    """일별 스냅샷."""

    date: str
    cash: int
    position_value: int
    total_equity: int
    daily_pnl: int
    daily_pnl_pct: float
    cumulative_return_pct: float
    drawdown_pct: float
    trade_count: int


class BacktestPositionItem(BaseModel):
    """최종 보유 포지션."""

    ticker: str
    quantity: int
    avg_price: int
    current_price: int
    market_value: int
    unrealized_pnl: int


class BacktestRunResponse(BaseModel):
    """백테스트 실행 결과."""

    run_id: str
    config: dict[str, Any]
    start_date: str
    end_date: str
    initial_capital: int
    final_equity: int
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: Optional[float]
    win_rate: float
    total_trades: int
    total_buy_trades: int
    total_sell_trades: int
    avg_holding_days: float
    profit_factor: Optional[float]
    daily_snapshots: list[BacktestSnapshotItem]
    orders: list[BacktestOrderItem]
    final_positions: list[BacktestPositionItem]


class BacktestSummaryResponse(BaseModel):
    """백테스트 결과 요약 (차트용)."""

    run_id: str
    strategy_id: str
    start_date: str
    end_date: str
    initial_capital: int
    final_equity: int
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: Optional[float]
    win_rate: float
    total_trades: int
    profit_factor: Optional[float]
    avg_holding_days: float


# ── 엔드포인트 ────────────────────────────────────────────────────────────────


VALID_STRATEGIES = {"A", "B", "RL", "S", "L"}
VALID_SIGNALS = {"rule", "momentum", "mean_reversion", "random"}


@router.post("/run", response_model=BacktestRunResponse)
async def run_backtest(
    request: BacktestRunRequest,
    _: Annotated[dict, Depends(get_current_user)],
) -> BacktestRunResponse:
    """백테스트를 실행합니다.

    DB에 저장된 과거 OHLCV 데이터를 사용하여 지정된 전략과 종목에 대해
    가상 트레이딩 시뮬레이션을 수행하고 성과 지표를 반환합니다.
    """
    # 입력 검증
    if request.strategy_id not in VALID_STRATEGIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"유효하지 않은 전략 ID: {request.strategy_id}. "
            f"허용: {', '.join(sorted(VALID_STRATEGIES))}",
        )

    if request.signal_source not in VALID_SIGNALS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"유효하지 않은 시그널 소스: {request.signal_source}. "
            f"허용: {', '.join(sorted(VALID_SIGNALS))}",
        )

    if request.start_date >= request.end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date는 end_date보다 이전이어야 합니다.",
        )

    config = BacktestConfig(
        strategy_id=request.strategy_id,
        start_date=request.start_date,
        end_date=request.end_date,
        initial_capital=request.initial_capital,
        slippage_bps=request.slippage_bps,
        commission_bps=request.commission_bps,
        max_position_pct=request.max_position_pct,
        tickers=request.tickers,
        signal_source=request.signal_source,
    )

    try:
        result = await run_backtest_from_db(config)
    except Exception as e:
        logger.error("백테스트 실행 오류: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"백테스트 실행 중 오류 발생: {str(e)}",
        )

    return BacktestRunResponse(
        run_id=result.run_id,
        config=result.config,
        start_date=result.start_date,
        end_date=result.end_date,
        initial_capital=result.initial_capital,
        final_equity=result.final_equity,
        total_return_pct=result.total_return_pct,
        annualized_return_pct=result.annualized_return_pct,
        max_drawdown_pct=result.max_drawdown_pct,
        sharpe_ratio=result.sharpe_ratio,
        win_rate=result.win_rate,
        total_trades=result.total_trades,
        total_buy_trades=result.total_buy_trades,
        total_sell_trades=result.total_sell_trades,
        avg_holding_days=result.avg_holding_days,
        profit_factor=result.profit_factor,
        daily_snapshots=[
            BacktestSnapshotItem(
                date=s.date,
                cash=s.cash,
                position_value=s.position_value,
                total_equity=s.total_equity,
                daily_pnl=s.daily_pnl,
                daily_pnl_pct=s.daily_pnl_pct,
                cumulative_return_pct=s.cumulative_return_pct,
                drawdown_pct=s.drawdown_pct,
                trade_count=s.trade_count,
            )
            for s in result.daily_snapshots
        ],
        orders=[
            BacktestOrderItem(
                date=o.date,
                ticker=o.ticker,
                side=o.side,
                quantity=o.quantity,
                price=o.price,
                amount=o.amount,
                slippage_cost=o.slippage_cost,
                commission=o.commission,
            )
            for o in result.orders
        ],
        final_positions=[
            BacktestPositionItem(**p) for p in result.final_positions
        ],
    )


@router.post("/run/summary", response_model=BacktestSummaryResponse)
async def run_backtest_summary(
    request: BacktestRunRequest,
    _: Annotated[dict, Depends(get_current_user)],
) -> BacktestSummaryResponse:
    """백테스트를 실행하고 요약 결과만 반환합니다.

    전체 결과 대신 핵심 지표만 반환하여 빠른 비교에 적합합니다.
    """
    if request.strategy_id not in VALID_STRATEGIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"유효하지 않은 전략 ID: {request.strategy_id}",
        )

    if request.signal_source not in VALID_SIGNALS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"유효하지 않은 시그널 소스: {request.signal_source}",
        )

    if request.start_date >= request.end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date는 end_date보다 이전이어야 합니다.",
        )

    config = BacktestConfig(
        strategy_id=request.strategy_id,
        start_date=request.start_date,
        end_date=request.end_date,
        initial_capital=request.initial_capital,
        slippage_bps=request.slippage_bps,
        commission_bps=request.commission_bps,
        max_position_pct=request.max_position_pct,
        tickers=request.tickers,
        signal_source=request.signal_source,
    )

    try:
        result = await run_backtest_from_db(config)
    except Exception as e:
        logger.error("백테스트 요약 실행 오류: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"백테스트 실행 중 오류 발생: {str(e)}",
        )

    return BacktestSummaryResponse(
        run_id=result.run_id,
        strategy_id=request.strategy_id,
        start_date=result.start_date,
        end_date=result.end_date,
        initial_capital=result.initial_capital,
        final_equity=result.final_equity,
        total_return_pct=result.total_return_pct,
        annualized_return_pct=result.annualized_return_pct,
        max_drawdown_pct=result.max_drawdown_pct,
        sharpe_ratio=result.sharpe_ratio,
        win_rate=result.win_rate,
        total_trades=result.total_trades,
        profit_factor=result.profit_factor,
        avg_holding_days=result.avg_holding_days,
    )
