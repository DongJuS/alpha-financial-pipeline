"""
src/utils/account_scope.py — paper/real/virtual 계좌 범위 헬퍼
"""

from __future__ import annotations

from typing import Literal

AccountScope = Literal["paper", "real", "virtual"]


def normalize_account_scope(scope: str | None) -> AccountScope:
    if scope == "real":
        return "real"
    if scope == "virtual":
        return "virtual"
    return "paper"


def is_paper_scope(scope: str | None) -> bool:
    return normalize_account_scope(scope) == "paper"


def is_virtual_scope(scope: str | None) -> bool:
    return normalize_account_scope(scope) == "virtual"


def scope_from_is_paper(is_paper: bool) -> AccountScope:
    return "paper" if is_paper else "real"
