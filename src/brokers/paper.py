"""
src/brokers/paper.py — 내부 모의주문 브로커
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from src.db.models import PaperOrderRequest
from src.db.queries import (
    fetch_all_trade_rows,
    get_position,
    get_trading_account,
    insert_broker_order,
    insert_trade,
    portfolio_position_stats,
    record_account_snapshot,
    save_position,
    trade_cash_totals,
    update_broker_order_status,
    upsert_trading_account,
)
from src.utils.account_scope import AccountScope, normalize_account_scope
from src.utils.performance import compute_trade_performance


@dataclass
class PaperBrokerExecution:
    client_order_id: str
    account_scope: AccountScope
    status: str
    ticker: str
    side: str
    quantity: int
    price: int
    cash_balance: int
    total_equity: int
    rejection_reason: str | None = None


class PaperBroker:
    def __init__(self, broker_name: str = "internal-paper") -> None:
        self.broker_name = broker_name

    async def execute_order(self, order: PaperOrderRequest) -> PaperBrokerExecution:
        scope = normalize_account_scope(order.account_scope)
        client_order_id = f"paper-{uuid4().hex[:16]}"

        await self._ensure_account(scope)
        await insert_broker_order(
            client_order_id=client_order_id,
            account_scope=scope,
            broker_name=self.broker_name,
            ticker=order.ticker,
            name=order.name,
            side=order.signal,
            requested_quantity=order.quantity,
            requested_price=order.price,
            signal_source=order.signal_source,
            agent_id=order.agent_id,
        )

        account_state = await self.sync_account_state(scope, snapshot_source="pre_trade")
        position = await get_position(order.ticker, account_scope=scope)
        order_amount = order.quantity * order.price

        if order.signal == "BUY" and account_state["buying_power"] < order_amount:
            return await self._reject_order(
                client_order_id=client_order_id,
                scope=scope,
                order=order,
                account_state=account_state,
                reason=f"주문 가능 금액 부족 ({account_state['buying_power']:,}원 < {order_amount:,}원)",
            )

        if order.signal == "SELL":
            held_qty = int(position["quantity"]) if position else 0
            if held_qty < order.quantity:
                return await self._reject_order(
                    client_order_id=client_order_id,
                    scope=scope,
                    order=order,
                    account_state=account_state,
                    reason=f"보유 수량 부족 ({held_qty}주 < {order.quantity}주)",
                )

        if order.signal == "BUY":
            prev_qty = int(position["quantity"]) if position else 0
            prev_avg = int(position["avg_price"]) if position else 0
            new_qty = prev_qty + order.quantity
            new_avg = int(((prev_qty * prev_avg) + order_amount) / new_qty)
            await save_position(
                ticker=order.ticker,
                name=order.name,
                quantity=new_qty,
                avg_price=new_avg,
                current_price=order.price,
                is_paper=scope == "paper",
                account_scope=scope,
            )
        else:
            held_qty = int(position["quantity"]) if position else 0
            remaining_qty = max(held_qty - order.quantity, 0)
            prev_avg = int(position["avg_price"]) if position else 0
            await save_position(
                ticker=order.ticker,
                name=order.name,
                quantity=remaining_qty,
                avg_price=prev_avg if remaining_qty > 0 else 0,
                current_price=order.price,
                is_paper=scope == "paper",
                account_scope=scope,
            )

        await insert_trade(order)
        await update_broker_order_status(
            client_order_id=client_order_id,
            status="FILLED",
            filled_quantity=order.quantity,
            avg_fill_price=order.price,
            broker_order_id=client_order_id,
        )
        account_state = await self.sync_account_state(scope, snapshot_source="paper_broker")

        return PaperBrokerExecution(
            client_order_id=client_order_id,
            account_scope=scope,
            status="FILLED",
            ticker=order.ticker,
            side=order.signal,
            quantity=order.quantity,
            price=order.price,
            cash_balance=account_state["cash_balance"],
            total_equity=account_state["total_equity"],
        )

    async def sync_account_state(
        self,
        account_scope: AccountScope = "paper",
        snapshot_source: str = "broker",
    ) -> dict:
        scope = normalize_account_scope(account_scope)
        await self._ensure_account(scope)

        account = await get_trading_account(scope)
        trade_totals = await trade_cash_totals(scope)
        position_stats = await portfolio_position_stats(scope)
        performance_rows = await fetch_all_trade_rows(scope)
        performance = compute_trade_performance(performance_rows)

        seed_capital = int(account["seed_capital"]) if account else 10_000_000
        cash_balance = max(seed_capital - trade_totals["buy_total"] + trade_totals["sell_total"], 0)
        buying_power = cash_balance
        total_equity = cash_balance + position_stats["market_value"]

        await upsert_trading_account(
            account_scope=scope,
            broker_name=str(account["broker_name"]) if account else "한국투자증권 KIS",
            account_label=str(account["account_label"]) if account else "KIS 모의투자 계좌",
            base_currency=str(account["base_currency"]) if account else "KRW",
            seed_capital=seed_capital,
            cash_balance=cash_balance,
            buying_power=buying_power,
            total_equity=total_equity,
            is_active=bool(account["is_active"]) if account else (scope == "paper"),
        )
        await record_account_snapshot(
            account_scope=scope,
            cash_balance=cash_balance,
            buying_power=buying_power,
            position_market_value=position_stats["market_value"],
            total_equity=total_equity,
            realized_pnl=int(performance["realized_pnl"]),
            unrealized_pnl=position_stats["unrealized_pnl"],
            position_count=position_stats["position_count"],
            snapshot_source=snapshot_source,
        )

        return {
            "account_scope": scope,
            "seed_capital": seed_capital,
            "cash_balance": cash_balance,
            "buying_power": buying_power,
            "position_market_value": position_stats["market_value"],
            "total_equity": total_equity,
            "realized_pnl": int(performance["realized_pnl"]),
            "unrealized_pnl": position_stats["unrealized_pnl"],
            "position_count": position_stats["position_count"],
        }

    async def _ensure_account(self, scope: AccountScope) -> None:
        account = await get_trading_account(scope)
        if account:
            return
        await upsert_trading_account(
            account_scope=scope,
            broker_name="한국투자증권 KIS",
            account_label="KIS 모의투자 계좌" if scope == "paper" else "KIS 실거래 계좌",
            seed_capital=10_000_000 if scope == "paper" else 0,
            cash_balance=10_000_000 if scope == "paper" else 0,
            buying_power=10_000_000 if scope == "paper" else 0,
            total_equity=10_000_000 if scope == "paper" else 0,
            is_active=(scope == "paper"),
        )

    async def _reject_order(
        self,
        client_order_id: str,
        scope: AccountScope,
        order: PaperOrderRequest,
        account_state: dict,
        reason: str,
    ) -> PaperBrokerExecution:
        await update_broker_order_status(
            client_order_id=client_order_id,
            status="REJECTED",
            rejection_reason=reason,
        )
        return PaperBrokerExecution(
            client_order_id=client_order_id,
            account_scope=scope,
            status="REJECTED",
            ticker=order.ticker,
            side=order.signal,
            quantity=order.quantity,
            price=order.price,
            cash_balance=account_state["cash_balance"],
            total_equity=account_state["total_equity"],
            rejection_reason=reason,
        )
