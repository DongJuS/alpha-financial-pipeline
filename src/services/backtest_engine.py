"""
src/services/backtest_engine.py — 백테스트 시뮬레이션 엔진

과거 OHLCV 데이터를 기반으로 전략의 시그널을 재현하여
가상 트레이딩 성과를 시뮬레이션합니다.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional

from src.utils.logging import get_logger
from src.utils.performance import compute_trade_performance

logger = get_logger(__name__)


@dataclass
class BacktestConfig:
    """백테스트 실행 설정."""

    strategy_id: str = "A"
    start_date: str = ""  # YYYY-MM-DD
    end_date: str = ""  # YYYY-MM-DD
    initial_capital: int = 10_000_000
    slippage_bps: int = 5
    commission_bps: int = 15  # 매매 수수료 (한국 기준 ~0.015%)
    max_position_pct: float = 20.0  # 단일 종목 최대 비중
    tickers: list[str] = field(default_factory=list)
    signal_source: str = "rule"  # rule | random | momentum | mean_reversion


@dataclass
class BacktestOrder:
    """백테스트 주문 기록."""

    date: str
    ticker: str
    side: str  # BUY | SELL
    quantity: int
    price: int
    amount: int
    slippage_cost: int
    commission: int


@dataclass
class BacktestPosition:
    """백테스트 보유 포지션."""

    ticker: str
    quantity: int = 0
    avg_price: float = 0.0
    current_price: float = 0.0

    @property
    def market_value(self) -> int:
        return int(self.quantity * self.current_price)

    @property
    def unrealized_pnl(self) -> int:
        return int(self.quantity * (self.current_price - self.avg_price))


@dataclass
class BacktestDailySnapshot:
    """일별 포트폴리오 스냅샷."""

    date: str
    cash: int
    position_value: int
    total_equity: int
    daily_pnl: int
    daily_pnl_pct: float
    cumulative_return_pct: float
    drawdown_pct: float
    trade_count: int


@dataclass
class BacktestResult:
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
    daily_snapshots: list[BacktestDailySnapshot]
    orders: list[BacktestOrder]
    final_positions: list[dict[str, Any]]


class BacktestEngine:
    """과거 데이터 기반 백테스트 시뮬레이션 엔진."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.cash = config.initial_capital
        self.positions: dict[str, BacktestPosition] = {}
        self.orders: list[BacktestOrder] = []
        self.daily_snapshots: list[BacktestDailySnapshot] = []
        self.peak_equity = config.initial_capital
        self.run_id = f"BT-{uuid.uuid4().hex[:8]}"

    def _apply_slippage(self, price: int, side: str) -> int:
        """슬리피지를 적용한 체결가를 반환합니다."""
        bps = self.config.slippage_bps
        if bps <= 0:
            return price
        ratio = bps / 10_000
        if side == "BUY":
            return int(round(price * (1 + ratio)))
        return int(round(price * (1 - ratio)))

    def _calc_commission(self, amount: int) -> int:
        """수수료를 계산합니다."""
        return int(round(amount * self.config.commission_bps / 10_000))

    def _total_equity(self) -> int:
        """현재 총 자산을 계산합니다."""
        pos_value = sum(p.market_value for p in self.positions.values())
        return self.cash + pos_value

    def _position_value(self) -> int:
        """현재 포지션 합산 시가를 계산합니다."""
        return sum(p.market_value for p in self.positions.values())

    def execute_buy(
        self,
        trade_date: str,
        ticker: str,
        price: int,
        target_pct: float = 10.0,
    ) -> Optional[BacktestOrder]:
        """매수 주문을 실행합니다."""
        fill_price = self._apply_slippage(price, "BUY")
        equity = self._total_equity()

        # 단일 종목 비중 제한
        max_amount = int(equity * min(target_pct, self.config.max_position_pct) / 100)

        # 기존 포지션 감안
        existing = self.positions.get(ticker)
        if existing and existing.quantity > 0:
            existing_value = existing.market_value
            remaining = max(0, max_amount - existing_value)
            if remaining <= 0:
                return None
            max_amount = remaining

        # 현금 제한
        max_amount = min(max_amount, self.cash)
        if max_amount < fill_price:
            return None

        quantity = max_amount // fill_price
        if quantity <= 0:
            return None

        amount = quantity * fill_price
        commission = self._calc_commission(amount)
        total_cost = amount + commission
        if total_cost > self.cash:
            quantity = (self.cash - commission) // fill_price
            if quantity <= 0:
                return None
            amount = quantity * fill_price
            commission = self._calc_commission(amount)
            total_cost = amount + commission

        self.cash -= total_cost

        # 포지션 업데이트
        pos = self.positions.setdefault(
            ticker, BacktestPosition(ticker=ticker)
        )
        old_qty = pos.quantity
        new_qty = old_qty + quantity
        if new_qty > 0:
            pos.avg_price = (
                (old_qty * pos.avg_price + quantity * fill_price) / new_qty
            )
        pos.quantity = new_qty
        pos.current_price = fill_price

        order = BacktestOrder(
            date=trade_date,
            ticker=ticker,
            side="BUY",
            quantity=quantity,
            price=fill_price,
            amount=amount,
            slippage_cost=abs(fill_price - price) * quantity,
            commission=commission,
        )
        self.orders.append(order)
        return order

    def execute_sell(
        self,
        trade_date: str,
        ticker: str,
        price: int,
        quantity: Optional[int] = None,
    ) -> Optional[BacktestOrder]:
        """매도 주문을 실행합니다 (quantity=None이면 전량 매도)."""
        pos = self.positions.get(ticker)
        if not pos or pos.quantity <= 0:
            return None

        fill_price = self._apply_slippage(price, "SELL")
        sell_qty = min(quantity or pos.quantity, pos.quantity)
        if sell_qty <= 0:
            return None

        amount = sell_qty * fill_price
        commission = self._calc_commission(amount)

        self.cash += amount - commission
        pos.quantity -= sell_qty
        pos.current_price = fill_price
        if pos.quantity <= 0:
            pos.avg_price = 0.0

        order = BacktestOrder(
            date=trade_date,
            ticker=ticker,
            side="SELL",
            quantity=sell_qty,
            price=fill_price,
            amount=amount,
            slippage_cost=abs(fill_price - price) * sell_qty,
            commission=commission,
        )
        self.orders.append(order)
        return order

    def update_prices(self, prices: dict[str, int]) -> None:
        """현재가를 업데이트합니다."""
        for ticker, price in prices.items():
            if ticker in self.positions:
                self.positions[ticker].current_price = price

    def record_daily_snapshot(
        self, trade_date: str, trade_count: int = 0
    ) -> BacktestDailySnapshot:
        """일별 스냅샷을 기록합니다."""
        equity = self._total_equity()
        pos_value = self._position_value()

        prev_equity = (
            self.daily_snapshots[-1].total_equity
            if self.daily_snapshots
            else self.config.initial_capital
        )
        daily_pnl = equity - prev_equity
        daily_pnl_pct = (daily_pnl / prev_equity * 100) if prev_equity > 0 else 0.0
        cum_return = (
            (equity - self.config.initial_capital)
            / self.config.initial_capital
            * 100
        )

        if equity > self.peak_equity:
            self.peak_equity = equity
        drawdown = (
            (equity - self.peak_equity) / self.peak_equity * 100
            if self.peak_equity > 0
            else 0.0
        )

        snapshot = BacktestDailySnapshot(
            date=trade_date,
            cash=self.cash,
            position_value=pos_value,
            total_equity=equity,
            daily_pnl=daily_pnl,
            daily_pnl_pct=round(daily_pnl_pct, 4),
            cumulative_return_pct=round(cum_return, 4),
            drawdown_pct=round(drawdown, 4),
            trade_count=trade_count,
        )
        self.daily_snapshots.append(snapshot)
        return snapshot

    def generate_signal(
        self,
        ticker: str,
        ohlcv_history: list[dict[str, Any]],
    ) -> str:
        """시그널을 생성합니다 (규칙 기반)."""
        if len(ohlcv_history) < 20:
            return "HOLD"

        source = self.config.signal_source

        if source == "momentum":
            return self._momentum_signal(ohlcv_history)
        elif source == "mean_reversion":
            return self._mean_reversion_signal(ohlcv_history)
        elif source == "random":
            import random
            return random.choice(["BUY", "SELL", "HOLD", "HOLD", "HOLD"])
        else:  # rule — 기본 골든/데드 크로스
            return self._golden_dead_cross_signal(ohlcv_history)

    def _golden_dead_cross_signal(self, history: list[dict]) -> str:
        """5일/20일 이동평균 골든/데드 크로스 시그널."""
        closes = [float(h["close"]) for h in history[-20:]]
        if len(closes) < 20:
            return "HOLD"

        sma5 = sum(closes[-5:]) / 5
        sma20 = sum(closes) / 20
        prev_sma5 = sum(closes[-6:-1]) / 5

        # 골든 크로스 (5일선이 20일선 상향 돌파)
        if prev_sma5 <= sma20 and sma5 > sma20:
            return "BUY"
        # 데드 크로스 (5일선이 20일선 하향 돌파)
        if prev_sma5 >= sma20 and sma5 < sma20:
            return "SELL"
        return "HOLD"

    def _momentum_signal(self, history: list[dict]) -> str:
        """모멘텀 시그널 — 5일 수익률 기반."""
        closes = [float(h["close"]) for h in history[-6:]]
        if len(closes) < 6:
            return "HOLD"
        ret_5d = (closes[-1] - closes[0]) / closes[0] * 100
        if ret_5d > 3.0:
            return "BUY"
        if ret_5d < -3.0:
            return "SELL"
        return "HOLD"

    def _mean_reversion_signal(self, history: list[dict]) -> str:
        """평균 회귀 시그널 — 볼린저 밴드 기반."""
        closes = [float(h["close"]) for h in history[-20:]]
        if len(closes) < 20:
            return "HOLD"
        sma20 = sum(closes) / 20
        std = (sum((c - sma20) ** 2 for c in closes) / 20) ** 0.5
        if std == 0:
            return "HOLD"
        upper = sma20 + 2 * std
        lower = sma20 - 2 * std
        current = closes[-1]

        if current < lower:
            return "BUY"
        if current > upper:
            return "SELL"
        return "HOLD"

    async def run(
        self,
        ohlcv_data: dict[str, list[dict[str, Any]]],
    ) -> BacktestResult:
        """백테스트를 실행합니다.

        Args:
            ohlcv_data: {ticker: [{date, open, high, low, close, volume}, ...]}
        """
        logger.info(
            "백테스트 시작: %s (%s ~ %s) 전략=%s 종목=%d",
            self.run_id,
            self.config.start_date,
            self.config.end_date,
            self.config.strategy_id,
            len(ohlcv_data),
        )

        # 모든 거래일 정렬
        all_dates: set[str] = set()
        for ticker_data in ohlcv_data.values():
            for row in ticker_data:
                d = str(row["date"])[:10]
                if self.config.start_date <= d <= self.config.end_date:
                    all_dates.add(d)
        sorted_dates = sorted(all_dates)

        if not sorted_dates:
            return self._build_result()

        # 일자별 시뮬레이션
        for trade_date in sorted_dates:
            day_trade_count = 0

            # 현재가 업데이트
            current_prices: dict[str, int] = {}
            for ticker, rows in ohlcv_data.items():
                for row in rows:
                    if str(row["date"])[:10] == trade_date:
                        current_prices[ticker] = int(row["close"])
                        break
            self.update_prices(current_prices)

            # 시그널 생성 및 주문 실행
            for ticker in self.config.tickers:
                if ticker not in ohlcv_data:
                    continue

                # 해당 날짜까지의 히스토리
                history = [
                    r for r in ohlcv_data[ticker]
                    if str(r["date"])[:10] <= trade_date
                ]

                price = current_prices.get(ticker)
                if not price:
                    continue

                signal = self.generate_signal(ticker, history)

                if signal == "BUY":
                    order = self.execute_buy(trade_date, ticker, price)
                    if order:
                        day_trade_count += 1
                elif signal == "SELL":
                    order = self.execute_sell(trade_date, ticker, price)
                    if order:
                        day_trade_count += 1

            # 일별 스냅샷
            self.record_daily_snapshot(trade_date, day_trade_count)

        return self._build_result()

    def _build_result(self) -> BacktestResult:
        """최종 결과를 생성합니다."""
        final_equity = self._total_equity()
        initial = self.config.initial_capital
        total_return = (
            (final_equity - initial) / initial * 100 if initial > 0 else 0.0
        )

        # 연환산 수익률
        if self.daily_snapshots and len(self.daily_snapshots) > 1:
            days = len(self.daily_snapshots)
            annualized = ((1 + total_return / 100) ** (252 / max(days, 1)) - 1) * 100
        else:
            annualized = 0.0

        # MDD
        max_dd = 0.0
        for snap in self.daily_snapshots:
            if snap.drawdown_pct < max_dd:
                max_dd = snap.drawdown_pct

        # 거래 통계
        buy_orders = [o for o in self.orders if o.side == "BUY"]
        sell_orders = [o for o in self.orders if o.side == "SELL"]

        # 승률 및 Profit Factor
        trade_rows = [
            {
                "ticker": o.ticker,
                "side": o.side,
                "price": o.price,
                "quantity": o.quantity,
                "amount": o.amount,
                "executed_at": o.date,
            }
            for o in self.orders
        ]
        perf = compute_trade_performance(trade_rows) if trade_rows else {
            "win_rate": 0.0, "sharpe_ratio": None, "sell_count": 0,
        }

        # Profit Factor
        winning_pnl = 0.0
        losing_pnl = 0.0
        positions_temp: dict[str, dict] = {}
        for o in self.orders:
            pos = positions_temp.setdefault(o.ticker, {"qty": 0, "avg": 0.0})
            if o.side == "BUY":
                old = pos["qty"]
                new = old + o.quantity
                if new > 0:
                    pos["avg"] = (old * pos["avg"] + o.quantity * o.price) / new
                pos["qty"] = new
            elif o.side == "SELL" and pos["qty"] > 0:
                matched = min(pos["qty"], o.quantity)
                pnl = matched * (o.price - pos["avg"])
                if pnl > 0:
                    winning_pnl += pnl
                else:
                    losing_pnl += abs(pnl)
                pos["qty"] -= matched

        profit_factor = (
            round(winning_pnl / losing_pnl, 2)
            if losing_pnl > 0
            else None
        )

        # 평균 보유일수 (간단 추정)
        avg_holding = 0.0
        if buy_orders and sell_orders:
            total_hold_days = 0
            sell_count = 0
            buy_dates: dict[str, list[str]] = {}
            for o in buy_orders:
                buy_dates.setdefault(o.ticker, []).append(o.date)
            for o in sell_orders:
                ticker_buys = buy_dates.get(o.ticker, [])
                if ticker_buys:
                    buy_date = ticker_buys.pop(0)
                    bd = date.fromisoformat(buy_date)
                    sd = date.fromisoformat(o.date)
                    total_hold_days += (sd - bd).days
                    sell_count += 1
            avg_holding = total_hold_days / sell_count if sell_count > 0 else 0.0

        # 최종 포지션
        final_positions = [
            {
                "ticker": p.ticker,
                "quantity": p.quantity,
                "avg_price": round(p.avg_price),
                "current_price": round(p.current_price),
                "market_value": p.market_value,
                "unrealized_pnl": p.unrealized_pnl,
            }
            for p in self.positions.values()
            if p.quantity > 0
        ]

        return BacktestResult(
            run_id=self.run_id,
            config={
                "strategy_id": self.config.strategy_id,
                "signal_source": self.config.signal_source,
                "slippage_bps": self.config.slippage_bps,
                "commission_bps": self.config.commission_bps,
                "max_position_pct": self.config.max_position_pct,
                "tickers": self.config.tickers,
            },
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            initial_capital=initial,
            final_equity=final_equity,
            total_return_pct=round(total_return, 2),
            annualized_return_pct=round(annualized, 2),
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=perf.get("sharpe_ratio"),
            win_rate=perf.get("win_rate", 0.0),
            total_trades=len(self.orders),
            total_buy_trades=len(buy_orders),
            total_sell_trades=len(sell_orders),
            avg_holding_days=round(avg_holding, 1),
            profit_factor=profit_factor,
            daily_snapshots=self.daily_snapshots,
            orders=self.orders,
            final_positions=final_positions,
        )


async def run_backtest_from_db(config: BacktestConfig) -> BacktestResult:
    """DB에 저장된 과거 데이터로 백테스트를 실행합니다."""
    from src.utils.db_client import fetch

    ohlcv_data: dict[str, list[dict[str, Any]]] = {}

    for ticker in config.tickers:
        rows = await fetch(
            """
            SELECT
                (timestamp_kst AT TIME ZONE 'Asia/Seoul')::date::text AS date,
                open, high, low, close, volume
            FROM market_data
            WHERE ticker = $1
              AND interval = 'daily'
              AND (timestamp_kst AT TIME ZONE 'Asia/Seoul')::date
                  BETWEEN $2::date AND $3::date
            ORDER BY timestamp_kst
            """,
            ticker,
            config.start_date,
            config.end_date,
        )
        ohlcv_data[ticker] = [dict(r) for r in rows]

    engine = BacktestEngine(config)
    return await engine.run(ohlcv_data)
