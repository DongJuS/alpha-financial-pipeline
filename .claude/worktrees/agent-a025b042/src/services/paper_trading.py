"""
src/services/paper_trading.py — 계좌/주문 조회 조립 서비스
"""

from __future__ import annotations

from src.db.queries import get_trading_account, latest_account_snapshot, list_account_snapshots, list_broker_orders
from src.services.account_state import recompute_account_state
from src.utils.account_scope import AccountScope, normalize_account_scope


async def build_account_overview(account_scope: AccountScope = "paper") -> dict:
    scope = normalize_account_scope(account_scope)
    account = await get_trading_account(scope)
    snapshot = await latest_account_snapshot(scope)
    state = snapshot or await recompute_account_state(scope, persist_snapshot=False, snapshot_source="api")

    seed_capital = int(account["seed_capital"]) if account else int(state["total_equity"])
    total_pnl = int(state["realized_pnl"]) + int(state["unrealized_pnl"])
    total_pnl_pct = round((total_pnl / seed_capital * 100), 2) if seed_capital > 0 else 0.0

    return {
        "account_scope": scope,
        "broker_name": str(account["broker_name"]) if account else "한국투자증권 KIS",
        "account_label": str(account["account_label"]) if account else ("KIS 모의투자 계좌" if scope == "paper" else "KIS 실거래 계좌"),
        "base_currency": str(account["base_currency"]) if account else "KRW",
        "seed_capital": seed_capital,
        "cash_balance": int(state["cash_balance"]),
        "buying_power": int(state["buying_power"]),
        "position_market_value": int(state["position_market_value"]),
        "total_equity": int(state["total_equity"]),
        "realized_pnl": int(state["realized_pnl"]),
        "unrealized_pnl": int(state["unrealized_pnl"]),
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "position_count": int(state["position_count"]),
        "last_snapshot_at": snapshot["snapshot_at"] if snapshot else None,
    }


async def build_broker_order_activity(account_scope: AccountScope = "paper", limit: int = 50) -> list[dict]:
    scope = normalize_account_scope(account_scope)
    return await list_broker_orders(scope, limit=limit)


async def build_account_snapshot_series(account_scope: AccountScope = "paper", limit: int = 30) -> list[dict]:
    scope = normalize_account_scope(account_scope)
    rows = await list_account_snapshots(scope, limit=limit)
    if rows:
        return rows

    state = await recompute_account_state(scope, persist_snapshot=False, snapshot_source="api")
    return [
        {
            "account_scope": scope,
            "cash_balance": int(state["cash_balance"]),
            "buying_power": int(state["buying_power"]),
            "position_market_value": int(state["position_market_value"]),
            "total_equity": int(state["total_equity"]),
            "realized_pnl": int(state["realized_pnl"]),
            "unrealized_pnl": int(state["unrealized_pnl"]),
            "position_count": int(state["position_count"]),
            "snapshot_source": "computed",
            "snapshot_at": None,
        }
    ]
