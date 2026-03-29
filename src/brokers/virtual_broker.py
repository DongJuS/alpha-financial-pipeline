"""
src/brokers/virtual_broker.py — Virtual 계좌 전용 브로커

실제 주문은 실행하지 않고, 슬리피지·체결 지연·부분 체결을 시뮬레이션합니다.
전략별 독립 포트폴리오(virtual scope)에서 사용합니다.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from src.utils.config import get_settings
from src.utils.db_client import execute, fetch, fetchrow
from src.utils.logging import get_logger

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")


@dataclass
class VirtualBrokerExecution:
    """Virtual 브로커 주문 실행 결과."""

    client_order_id: str
    ticker: str
    side: str
    requested_quantity: int
    requested_price: int
    filled_quantity: int
    avg_fill_price: int
    status: str  # FILLED, REJECTED
    slippage_bps: float = 0.0
    fill_delay_sec: float = 0.0
    strategy_id: str | None = None
    rejection_reason: str | None = None


class VirtualBroker:
    """Virtual 계좌 전용 브로커 — 시뮬레이션 체결 엔진."""

    def __init__(
        self,
        strategy_id: str | None = None,
        initial_capital: int | None = None,
    ) -> None:
        settings = get_settings()
        self.strategy_id = strategy_id
        self.initial_capital = initial_capital or settings.virtual_initial_capital
        self.slippage_bps = settings.virtual_slippage_bps
        self.fill_delay_max_sec = settings.virtual_fill_delay_max_sec
        self.partial_fill_enabled = settings.virtual_partial_fill_enabled

    def _apply_slippage(self, price: int, side: str) -> int:
        """슬리피지를 적용한 체결 가격을 반환합니다.

        매수(BUY)는 가격 상승, 매도(SELL)는 가격 하락 방향으로 슬리피지가 적용됩니다.
        """
        if self.slippage_bps <= 0:
            return price

        # 0 ~ slippage_bps 범위에서 랜덤 적용
        actual_bps = random.uniform(0, self.slippage_bps)
        ratio = actual_bps / 10_000

        if side == "BUY":
            return int(round(price * (1 + ratio)))
        else:  # SELL
            return int(round(price * (1 - ratio)))

    def _calc_partial_fill(self, quantity: int) -> int:
        """부분 체결 수량을 계산합니다.

        10주 이하 소량 주문은 전량 체결, 그 이상은 50~100% 범위로 부분 체결합니다.
        """
        if not self.partial_fill_enabled:
            return quantity

        if quantity <= 10:
            return quantity

        fill_ratio = random.uniform(0.5, 1.0)
        filled = max(1, int(round(quantity * fill_ratio)))
        return min(filled, quantity)

    async def _simulate_delay(self) -> float:
        """체결 지연을 시뮬레이션합니다."""
        if self.fill_delay_max_sec <= 0:
            return 0.0
        delay = random.uniform(0, self.fill_delay_max_sec)
        await asyncio.sleep(delay)
        return delay

    async def execute_order(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: int,
        name: str = "",
        signal_source: str = "VIRTUAL",
    ) -> VirtualBrokerExecution:
        """Virtual 주문을 실행합니다 (시뮬레이션)."""
        client_order_id = f"VB-{uuid.uuid4().hex[:12]}"

        # 체결 지연 시뮬레이션
        delay = await self._simulate_delay()

        # 슬리피지 적용
        fill_price = self._apply_slippage(price, side)

        # 부분 체결 계산
        filled_qty = self._calc_partial_fill(quantity)

        amount = fill_price * filled_qty
        slippage_actual = abs(fill_price - price) / price * 10_000 if price > 0 else 0

        logger.info(
            "Virtual 체결 [%s] %s %s x %d @ %d (슬리피지 %.1fbps, 지연 %.2fs, 전략=%s)",
            ticker,
            side,
            name or ticker,
            filled_qty,
            fill_price,
            slippage_actual,
            delay,
            self.strategy_id or "default",
        )

        # DB 기록: broker_orders
        await execute(
            """
            INSERT INTO broker_orders (
                client_order_id, account_scope, broker_name, ticker, name,
                side, order_type, requested_quantity, requested_price,
                filled_quantity, avg_fill_price, status, signal_source,
                strategy_id, filled_at
            ) VALUES (
                $1, 'virtual', 'VirtualBroker', $2, $3,
                $4, 'MARKET', $5, $6,
                $7, $8, 'FILLED', $9,
                $10, NOW()
            )
            """,
            client_order_id,
            ticker,
            name or ticker,
            side,
            quantity,
            price,
            filled_qty,
            fill_price,
            signal_source,
            self.strategy_id,
        )

        # DB 기록: trade_history
        await execute(
            """
            INSERT INTO trade_history (
                ticker, name, side, quantity, price, amount,
                signal_source, account_scope, strategy_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'virtual', $8)
            """,
            ticker,
            name or ticker,
            side,
            filled_qty,
            fill_price,
            amount,
            signal_source,
            self.strategy_id,
        )

        # 포지션 업데이트
        await self._update_position(ticker, name, side, filled_qty, fill_price)

        return VirtualBrokerExecution(
            client_order_id=client_order_id,
            ticker=ticker,
            side=side,
            requested_quantity=quantity,
            requested_price=price,
            filled_quantity=filled_qty,
            avg_fill_price=fill_price,
            status="FILLED",
            slippage_bps=round(slippage_actual, 2),
            fill_delay_sec=round(delay, 3),
            strategy_id=self.strategy_id,
        )

    async def _update_position(
        self,
        ticker: str,
        name: str,
        side: str,
        quantity: int,
        price: int,
    ) -> None:
        """Virtual 포지션을 업데이트합니다."""
        strategy_filter = self.strategy_id or ""

        existing = await fetchrow(
            """
            SELECT id, quantity, avg_price
            FROM portfolio_positions
            WHERE ticker = $1
              AND account_scope = 'virtual'
              AND COALESCE(strategy_id, '') = $2
            """,
            ticker,
            strategy_filter,
        )

        if side == "BUY":
            if existing:
                old_qty = int(existing["quantity"])
                old_avg = int(existing["avg_price"])
                new_qty = old_qty + quantity
                new_avg = int((old_avg * old_qty + price * quantity) / new_qty) if new_qty > 0 else price
                await execute(
                    """
                    UPDATE portfolio_positions
                    SET quantity = $1, avg_price = $2, current_price = $3, updated_at = NOW()
                    WHERE id = $4
                    """,
                    new_qty,
                    new_avg,
                    price,
                    existing["id"],
                )
            else:
                await execute(
                    """
                    INSERT INTO portfolio_positions (
                        ticker, name, quantity, avg_price, current_price,
                        is_paper, account_scope, strategy_id
                    ) VALUES ($1, $2, $3, $4, $5, FALSE, 'virtual', $6)
                    """,
                    ticker,
                    name or ticker,
                    quantity,
                    price,
                    price,
                    self.strategy_id,
                )
        else:  # SELL
            if existing:
                new_qty = max(0, int(existing["quantity"]) - quantity)
                await execute(
                    """
                    UPDATE portfolio_positions
                    SET quantity = $1, current_price = $2, updated_at = NOW()
                    WHERE id = $3
                    """,
                    new_qty,
                    price,
                    existing["id"],
                )

    async def get_positions(self) -> list[dict[str, Any]]:
        """현재 Virtual 포지션 목록을 반환합니다."""
        strategy_filter = self.strategy_id or ""
        rows = await fetch(
            """
            SELECT ticker, name, quantity, avg_price, current_price
            FROM portfolio_positions
            WHERE account_scope = 'virtual'
              AND COALESCE(strategy_id, '') = $1
              AND quantity > 0
            ORDER BY updated_at DESC
            """,
            strategy_filter,
        )
        return [dict(r) for r in rows]
