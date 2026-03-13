"""
src/services/paper_reconciliation.py — KIS paper 계좌 reconciliation 및 운영 보고
"""

from __future__ import annotations

from datetime import date, datetime

from src.brokers.kis import KISAPIError, KISPaperApiClient
from src.db.queries import (
    get_trading_account,
    insert_operational_audit,
    list_positions,
    record_account_snapshot,
    save_position,
    upsert_kis_broker_order,
    upsert_trade_fill,
    upsert_trading_account,
)
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _to_int(value: object) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _parse_kis_datetime(ord_dt: object, ord_tmd: object) -> datetime | None:
    date_text = str(ord_dt or "").strip()
    time_text = str(ord_tmd or "").strip()
    if not date_text or not time_text:
        return None

    padded_time = time_text.zfill(6)[:6]
    try:
        return datetime.strptime(f"{date_text}{padded_time}", "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _status_from_fill_row(row: dict) -> str:
    filled_quantity = _to_int(row.get("tot_ccld_qty"))
    remaining_quantity = _to_int(row.get("rmn_qty"))
    rejected_quantity = _to_int(row.get("rjct_qty"))
    cancelled = str(row.get("cncl_yn") or "N").upper() == "Y"

    if filled_quantity > 0 and remaining_quantity == 0:
        return "FILLED"
    if cancelled:
        return "CANCELLED"
    if rejected_quantity > 0 and filled_quantity == 0:
        return "REJECTED"
    return "PENDING"


def _side_from_fill_row(row: dict) -> str:
    if str(row.get("sll_buy_dvsn_cd") or "") == "01":
        return "SELL"
    if "매도" in str(row.get("sll_buy_dvsn_cd_name") or ""):
        return "SELL"
    return "BUY"


async def _with_retries(factory, *, attempts: int = 3):
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return await factory()
        except Exception as exc:  # noqa: PERF203 - retry loop keeps the logic easy to read
            last_error = exc
    assert last_error is not None
    raise last_error


async def reconcile_kis_paper_account(
    *,
    report_date: date | None = None,
    client: KISPaperApiClient | None = None,
    record_audit: bool = True,
    max_retries: int = 3,
) -> dict:
    settings = get_settings()
    backend = settings.paper_broker_backend.strip().lower()
    target_date = report_date or date.today()

    result = {
        "report_date": target_date.isoformat(),
        "backend": backend,
        "passed": False,
        "fallback_used": False,
        "position_updates": 0,
        "positions_cleared": 0,
        "orders_synced": 0,
        "new_trades": 0,
        "summary": "",
    }

    if backend not in {"kis", "kis_shadow"} and client is None:
        result["fallback_used"] = True
        result["passed"] = True
        result["summary"] = "PAPER_BROKER_BACKEND=internal 이므로 internal read model을 유지했습니다."
        if record_audit:
            await insert_operational_audit(
                audit_type="paper_reconciliation",
                passed=True,
                summary=result["summary"],
                details=result,
                executed_by="services.paper_reconciliation",
            )
        return result

    active_client = client or KISPaperApiClient(settings=settings)

    if not active_client.is_configured():
        result["fallback_used"] = True
        result["passed"] = backend != "kis"
        result["summary"] = "KIS 설정이 없어 internal read model을 유지했습니다."
        if record_audit:
            await insert_operational_audit(
                audit_type="paper_reconciliation",
                passed=result["passed"],
                summary=result["summary"],
                details=result,
                executed_by="services.paper_reconciliation",
            )
        return result

    try:
        balance_payload = await _with_retries(active_client.inquire_balance, attempts=max_retries)
        fill_payload = await _with_retries(
            lambda: active_client.inquire_daily_ccld(start_date=target_date, end_date=target_date),
            attempts=max_retries,
        )
    except KISAPIError as exc:
        result["fallback_used"] = True
        result["passed"] = backend != "kis"
        result["summary"] = f"KIS reconciliation 실패: {exc}"
        if record_audit:
            await insert_operational_audit(
                audit_type="paper_reconciliation",
                passed=result["passed"],
                summary=result["summary"],
                details=result,
                executed_by="services.paper_reconciliation",
            )
        return result

    existing_account = await get_trading_account("paper")
    existing_positions = await list_positions("paper")
    remote_positions = balance_payload["positions"]
    remote_tickers: set[str] = set()

    for item in remote_positions:
        ticker = str(item.get("pdno") or "").strip()
        if not ticker:
            continue

        quantity = _to_int(item.get("hldg_qty"))
        remote_tickers.add(ticker)
        await save_position(
            ticker=ticker,
            name=str(item.get("prdt_name") or ticker),
            quantity=quantity,
            avg_price=_to_int(item.get("pchs_avg_pric")),
            current_price=_to_int(item.get("prpr")),
            is_paper=True,
            account_scope="paper",
        )
        result["position_updates"] += 1

    for local in existing_positions:
        if local["ticker"] in remote_tickers:
            continue
        await save_position(
            ticker=str(local["ticker"]),
            name=str(local["name"]),
            quantity=0,
            avg_price=0,
            current_price=_to_int(local.get("current_price")),
            is_paper=True,
            account_scope="paper",
        )
        result["positions_cleared"] += 1

    summary = balance_payload["summary"] or {}
    cash_balance = _to_int(summary.get("dnca_tot_amt"))
    buying_power = _to_int(summary.get("dnca_tot_amt") or summary.get("nass_amt"))
    position_market_value = _to_int(summary.get("scts_evlu_amt") or summary.get("evlu_amt_smtl_amt"))
    total_equity = _to_int(summary.get("tot_evlu_amt")) or (cash_balance + position_market_value)
    total_pnl = _to_int(summary.get("evlu_pfls_smtl_amt"))
    seed_capital = int(existing_account["seed_capital"]) if existing_account else max(total_equity - total_pnl, total_equity)

    await upsert_trading_account(
        account_scope="paper",
        broker_name="한국투자증권 KIS",
        account_label="KIS 모의투자 계좌",
        seed_capital=seed_capital,
        cash_balance=cash_balance,
        buying_power=buying_power,
        total_equity=total_equity,
        is_active=True,
    )
    await record_account_snapshot(
        account_scope="paper",
        cash_balance=cash_balance,
        buying_power=buying_power,
        position_market_value=position_market_value,
        total_equity=total_equity,
        realized_pnl=0,
        unrealized_pnl=total_pnl,
        position_count=len(remote_tickers),
        snapshot_source="kis_reconcile",
    )

    for row in fill_payload["orders"]:
        broker_order_id = str(row.get("odno") or "").strip()
        if not broker_order_id:
            continue

        requested_quantity = _to_int(row.get("ord_qty"))
        filled_quantity = _to_int(row.get("tot_ccld_qty"))
        requested_price = _to_int(row.get("ord_unpr"))
        average_fill_price = _to_int(row.get("avg_prvs") or row.get("ord_unpr")) or None
        status = _status_from_fill_row(row)
        requested_at = _parse_kis_datetime(row.get("ord_dt"), row.get("ord_tmd"))
        filled_at = requested_at if filled_quantity > 0 else None
        side = _side_from_fill_row(row)
        ticker = str(row.get("pdno") or "").strip()
        name = str(row.get("prdt_name") or ticker)

        await upsert_kis_broker_order(
            account_scope="paper",
            broker_order_id=broker_order_id,
            ticker=ticker,
            name=name,
            side=side,
            requested_quantity=requested_quantity,
            requested_price=requested_price,
            filled_quantity=filled_quantity,
            avg_fill_price=average_fill_price,
            status=status,
            requested_at=requested_at,
            filled_at=filled_at,
        )
        result["orders_synced"] += 1

        if filled_quantity <= 0:
            continue

        inserted = await upsert_trade_fill(
            account_scope="paper",
            ticker=ticker,
            name=name,
            side=side,
            quantity=filled_quantity,
            price=average_fill_price or requested_price,
            signal_source="BLEND",
            agent_id="kis_reconciler",
            kis_order_id=broker_order_id,
            executed_at=filled_at,
        )
        if inserted:
            result["new_trades"] += 1

    result["passed"] = True
    result["summary"] = (
        f"KIS paper reconciliation 완료: positions={result['position_updates']}, "
        f"orders={result['orders_synced']}, new_trades={result['new_trades']}"
    )
    if record_audit:
        await insert_operational_audit(
            audit_type="paper_reconciliation",
            passed=True,
            summary=result["summary"],
            details=result,
            executed_by="services.paper_reconciliation",
        )
    return result
