"""
src/utils/performance.py — 거래 이력 성과 계산 유틸
"""

from __future__ import annotations

from datetime import date, datetime


def _to_date(value: date | datetime | str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        # ISO datetime/date 문자열을 허용합니다.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    raise TypeError(f"Unsupported date value: {value!r}")

def compute_trade_performance(rows: list[dict]) -> dict:
    """체결 이력에서 실현손익 기반 성과 지표를 계산합니다."""
    positions: dict[str, dict] = {}
    realized_pnl = 0.0
    invested_capital = 0.0
    sell_returns: list[float] = []
    equity_curve: list[float] = [1.0]
    win_sells = 0
    sell_count = 0

    for row in rows:
        ticker = str(row["ticker"])
        side = str(row["side"]).upper()
        qty = int(row["quantity"])
        price = float(row["price"])
        pos = positions.setdefault(ticker, {"qty": 0, "avg_cost": 0.0})

        if side == "BUY":
            prev_qty = int(pos["qty"])
            new_qty = prev_qty + qty
            if new_qty <= 0:
                pos["qty"] = 0
                pos["avg_cost"] = 0.0
                continue
            pos["avg_cost"] = ((prev_qty * float(pos["avg_cost"])) + (qty * price)) / new_qty
            pos["qty"] = new_qty
            invested_capital += qty * price
            continue

        if side != "SELL":
            continue

        held_qty = int(pos["qty"])
        if held_qty <= 0:
            # 매칭할 포지션이 없으면 성과 계산에서 제외
            continue

        matched_qty = min(held_qty, qty)
        cost_basis = matched_qty * float(pos["avg_cost"])
        proceeds = matched_qty * price
        trade_pnl = proceeds - cost_basis
        realized_pnl += trade_pnl
        sell_count += 1
        if trade_pnl > 0:
            win_sells += 1
        if cost_basis > 0:
            trade_return = trade_pnl / cost_basis
            sell_returns.append(trade_return)
            equity_curve.append(equity_curve[-1] * (1.0 + trade_return))

        remaining_qty = held_qty - matched_qty
        pos["qty"] = remaining_qty
        if remaining_qty == 0:
            pos["avg_cost"] = 0.0

    return_pct = (realized_pnl / invested_capital * 100) if invested_capital > 0 else 0.0
    win_rate = (win_sells / sell_count) if sell_count > 0 else 0.0

    peak = equity_curve[0]
    max_drawdown_pct = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        drawdown_pct = ((value - peak) / peak) * 100
        if drawdown_pct < max_drawdown_pct:
            max_drawdown_pct = drawdown_pct

    sharpe_ratio = None
    if len(sell_returns) >= 2:
        mean_ret = sum(sell_returns) / len(sell_returns)
        variance = sum((r - mean_ret) ** 2 for r in sell_returns) / (len(sell_returns) - 1)
        std_dev = variance ** 0.5
        if std_dev > 0:
            sharpe_ratio = (mean_ret / std_dev) * (len(sell_returns) ** 0.5)

    return {
        "return_pct": round(return_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "sharpe_ratio": round(sharpe_ratio, 3) if sharpe_ratio is not None else None,
        "win_rate": round(win_rate, 2),
        "total_trades": len(rows),
        "realized_pnl": int(round(realized_pnl)),
        "invested_capital": int(round(invested_capital)),
        "sell_count": sell_count,
    }


def compute_trade_performance_series(rows: list[dict]) -> list[dict]:
    """거래 이력으로 일자별 누적 실현손익/수익률 시계열을 계산합니다."""
    if not rows:
        return []

    sorted_rows = sorted(
        rows,
        key=lambda r: _to_date(r["executed_at"]),
    )

    positions: dict[str, dict] = {}
    invested_capital = 0.0
    realized_pnl_cum = 0.0
    daily_stats: dict[date, dict] = {}

    for row in sorted_rows:
        ticker = str(row["ticker"])
        side = str(row["side"]).upper()
        qty = int(row["quantity"])
        price = float(row["price"])
        day = _to_date(row["executed_at"])
        bucket = daily_stats.setdefault(day, {"realized_pnl": 0.0, "trades": 0})
        bucket["trades"] += 1

        pos = positions.setdefault(ticker, {"qty": 0, "avg_cost": 0.0})
        if side == "BUY":
            prev_qty = int(pos["qty"])
            new_qty = prev_qty + qty
            if new_qty > 0:
                pos["avg_cost"] = ((prev_qty * float(pos["avg_cost"])) + (qty * price)) / new_qty
                pos["qty"] = new_qty
                invested_capital += qty * price
            continue

        if side != "SELL":
            continue

        held_qty = int(pos["qty"])
        if held_qty <= 0:
            continue

        matched_qty = min(held_qty, qty)
        cost_basis = matched_qty * float(pos["avg_cost"])
        proceeds = matched_qty * price
        pnl = proceeds - cost_basis
        bucket["realized_pnl"] += pnl

        pos["qty"] = held_qty - matched_qty
        if int(pos["qty"]) == 0:
            pos["avg_cost"] = 0.0

    series: list[dict] = []
    for d in sorted(daily_stats.keys()):
        realized_pnl_cum += float(daily_stats[d]["realized_pnl"])
        return_pct = (realized_pnl_cum / invested_capital * 100) if invested_capital > 0 else 0.0
        series.append(
            {
                "date": d.isoformat(),
                "realized_pnl_cum": int(round(realized_pnl_cum)),
                "portfolio_return_pct": round(return_pct, 2),
                "trade_count": int(daily_stats[d]["trades"]),
            }
        )
    return series


def compute_benchmark_series(rows: list[dict]) -> list[dict]:
    """
    벤치마크 시계열을 계산합니다.
    입력 rows 예시: [{"trade_date": date|str|datetime, "avg_close": 2500.1}, ...]
    """
    if not rows:
        return []

    normalized = []
    for row in rows:
        normalized.append(
            {
                "date": _to_date(row["trade_date"]),
                "avg_close": float(row["avg_close"]),
            }
        )
    normalized.sort(key=lambda r: r["date"])

    first = normalized[0]["avg_close"] if normalized else 0.0
    if first <= 0:
        return []

    series: list[dict] = []
    for item in normalized:
        ret = ((item["avg_close"] / first) - 1.0) * 100
        series.append(
            {
                "date": item["date"].isoformat(),
                "benchmark_return_pct": round(ret, 2),
            }
        )
    return series
