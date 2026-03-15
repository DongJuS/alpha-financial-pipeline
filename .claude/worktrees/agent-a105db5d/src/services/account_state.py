"""
src/services/account_state.py — 계좌 상태 재계산 서비스
"""

from __future__ import annotations

from src.db.queries import (
    fetch_all_trade_rows,
    get_trading_account,
    portfolio_position_stats,
    record_account_snapshot,
    trade_cash_totals,
    upsert_trading_account,
)
from src.utils.account_scope import AccountScope, normalize_account_scope
from src.utils.performance import compute_trade_performance


async def recompute_account_state(
    account_scope: AccountScope = "paper",
    *,
    persist_snapshot: bool = True,
    snapshot_source: str = "broker",
) -> dict:
    scope = normalize_account_scope(account_scope)
    account = await get_trading_account(scope)
    trade_totals = await trade_cash_totals(scope)
    position_stats = await portfolio_position_stats(scope)
    performance_rows = await fetch_all_trade_rows(scope)
    performance = compute_trade_performance(performance_rows)

    seed_capital = int(account["seed_capital"]) if account else (10_000_000 if scope == "paper" else 0)
    cash_balance = max(seed_capital - trade_totals["buy_total"] + trade_totals["sell_total"], 0)
    buying_power = cash_balance
    total_equity = cash_balance + position_stats["market_value"]

    await upsert_trading_account(
        account_scope=scope,
        broker_name=str(account["broker_name"]) if account else "한국투자증권 KIS",
        account_label=str(account["account_label"]) if account else ("KIS 모의투자 계좌" if scope == "paper" else "KIS 실거래 계좌"),
        base_currency=str(account["base_currency"]) if account else "KRW",
        seed_capital=seed_capital,
        cash_balance=cash_balance,
        buying_power=buying_power,
        total_equity=total_equity,
        is_active=bool(account["is_active"]) if account else (scope == "paper"),
    )

    state = {
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

    if persist_snapshot:
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

    return state
