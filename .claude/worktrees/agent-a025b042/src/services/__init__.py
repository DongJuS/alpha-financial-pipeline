from __future__ import annotations

from importlib import import_module

__all__ = [
    "account_state",
    "paper_trading",
    "paper_reconciliation",
    "build_account_overview",
    "build_account_snapshot_series",
    "build_broker_order_activity",
    "reconcile_kis_paper_account",
    "recompute_account_state",
]


def __getattr__(name: str):
    if name in {"account_state", "paper_trading", "paper_reconciliation"}:
        return import_module(f"src.services.{name}")

    if name == "recompute_account_state":
        from src.services.account_state import recompute_account_state

        return recompute_account_state

    if name in {"build_account_overview", "build_account_snapshot_series", "build_broker_order_activity"}:
        from src.services.paper_trading import (
            build_account_overview,
            build_account_snapshot_series,
            build_broker_order_activity,
        )

        return {
            "build_account_overview": build_account_overview,
            "build_account_snapshot_series": build_account_snapshot_series,
            "build_broker_order_activity": build_broker_order_activity,
        }[name]

    if name == "reconcile_kis_paper_account":
        from src.services.paper_reconciliation import reconcile_kis_paper_account

        return reconcile_kis_paper_account

    raise AttributeError(f"module 'src.services' has no attribute {name!r}")
