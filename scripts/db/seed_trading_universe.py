"""
scripts/db/seed_trading_universe.py — trading_universe 시딩 스크립트

instruments 테이블에 등록된 종목을 trading_universe에 매핑하여
특정 account_scope(paper/real/virtual)에서 운용할 종목을 지정한다.

사용법:
  python scripts/db/seed_trading_universe.py                              # 기본: paper 3종목
  python scripts/db/seed_trading_universe.py --scope real --tickers 005930.KS,000660.KS
  python scripts/db/seed_trading_universe.py --scope paper --from-instruments --max-weight 20
  python scripts/db/seed_trading_universe.py --scope paper --clear       # 기존 삭제 후 재시딩
  python scripts/db/seed_trading_universe.py --dry-run                   # 미리보기
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.utils.db_client import get_pool  # noqa: E402
from src.utils.logging import get_logger, setup_logging  # noqa: E402

setup_logging()
logger = get_logger(__name__)

# ── 기본 종목 (OHLCV 데이터가 확보된 핵심 3종목) ─────────────

DEFAULT_TICKERS: list[tuple[str, int]] = [
    ("005930.KS", 10),  # 삼성전자
    ("000660.KS", 8),   # SK하이닉스
    ("035420.KS", 6),   # NAVER
]


# ── 검증 ─────────────────────────────────────────────────────


async def validate_scope(pool, scope: str) -> bool:
    """account_scope가 trading_accounts에 존재하는지 확인."""
    row = await pool.fetchval(
        "SELECT 1 FROM trading_accounts WHERE account_scope = $1",
        scope,
    )
    return row is not None


async def validate_instruments(pool, instrument_ids: list[str]) -> list[str]:
    """instruments 테이블에 존재하지 않는 instrument_id 목록을 반환."""
    if not instrument_ids:
        return []
    rows = await pool.fetch(
        "SELECT instrument_id FROM instruments WHERE instrument_id = ANY($1::text[])",
        instrument_ids,
    )
    found = {r["instrument_id"] for r in rows}
    return [iid for iid in instrument_ids if iid not in found]


async def fetch_active_instruments(pool) -> list[str]:
    """is_active=True인 모든 instrument_id를 반환."""
    rows = await pool.fetch(
        "SELECT instrument_id FROM instruments WHERE is_active = TRUE ORDER BY instrument_id",
    )
    return [r["instrument_id"] for r in rows]


# ── 시딩 ─────────────────────────────────────────────────────


async def seed(
    scope: str,
    entries: list[tuple[str, int, Decimal | None, str | None]],
    *,
    clear: bool = False,
    dry_run: bool = False,
) -> int:
    """trading_universe에 UPSERT 시딩.

    Args:
        scope: account_scope (paper/real/virtual)
        entries: [(instrument_id, priority, max_weight_pct, memo), ...]
        clear: True면 해당 scope의 기존 레코드를 모두 삭제 후 삽입
        dry_run: True면 실제 DB 변경 없이 미리보기만 출력

    Returns:
        삽입/갱신된 행 수
    """
    pool = await get_pool()

    # ── 검증: scope
    if not await validate_scope(pool, scope):
        logger.error(
            "account_scope '%s'가 trading_accounts에 없습니다. "
            "먼저 trading_accounts에 해당 scope를 등록하세요.",
            scope,
        )
        sys.exit(1)

    # ── 검증: instrument_ids
    instrument_ids = [e[0] for e in entries]
    missing = await validate_instruments(pool, instrument_ids)
    if missing:
        logger.error(
            "instruments 테이블에 없는 종목이 있습니다: %s\n"
            "먼저 scripts/db/seed_all_instruments.py 를 실행하세요.",
            ", ".join(missing),
        )
        sys.exit(1)

    # ── dry-run 미리보기
    if dry_run:
        logger.info("=== DRY-RUN 모드 (실제 DB 변경 없음) ===")
        if clear:
            logger.info("  [DELETE] trading_universe WHERE account_scope = '%s'", scope)
        for iid, pri, weight, memo in entries:
            weight_str = f"{weight}%" if weight is not None else "NULL"
            memo_str = memo or "NULL"
            logger.info(
                "  [UPSERT] (%s, %s) priority=%d, max_weight=%s, memo=%s",
                scope, iid, pri, weight_str, memo_str,
            )
        logger.info("  총 %d건 예정", len(entries))
        return 0

    # ── 실행
    async with pool.acquire() as conn:
        async with conn.transaction():
            if clear:
                deleted = await conn.execute(
                    "DELETE FROM trading_universe WHERE account_scope = $1",
                    scope,
                )
                logger.info("[clear] scope='%s' 기존 레코드 삭제: %s", scope, deleted)

            upsert_query = """
                INSERT INTO trading_universe
                    (account_scope, instrument_id, priority, max_weight_pct, memo)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (account_scope, instrument_id) DO UPDATE SET
                    priority = EXCLUDED.priority,
                    max_weight_pct = EXCLUDED.max_weight_pct,
                    memo = EXCLUDED.memo
            """
            rows = [(scope, iid, pri, weight, memo) for iid, pri, weight, memo in entries]
            await conn.executemany(upsert_query, rows)

    logger.info("=== trading_universe 시딩 완료: scope='%s', %d건 ===", scope, len(entries))
    return len(entries)


# ── 검증 쿼리 ────────────────────────────────────────────────


async def verify(scope: str) -> None:
    """시딩 결과를 list_tickers 동등 쿼리로 확인."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT i.instrument_id, i.ticker, sm.name, i.market_id AS market,
               tu.priority, tu.max_weight_pct
        FROM instruments i
        JOIN trading_universe tu ON i.instrument_id = tu.instrument_id
        LEFT JOIN krx_stock_master sm ON i.ticker = sm.ticker
        WHERE tu.account_scope = $1 AND i.is_active = TRUE
        ORDER BY tu.priority DESC, i.instrument_id
        """,
        scope,
    )

    if not rows:
        logger.warning("[verify] scope='%s'에 활성 종목이 없습니다.", scope)
        return

    logger.info("\n=== 검증: list_tickers(mode='%s') — %d종목 ===", scope, len(rows))
    header = f"  {'instrument_id':<16} {'ticker':<10} {'name':<20} {'market':<8} {'priority':>8} {'max_weight':>10}"
    logger.info(header)
    logger.info("  " + "-" * (len(header) - 2))
    for r in rows:
        name = r["name"] or "(미등록)"
        weight = f"{r['max_weight_pct']}%" if r["max_weight_pct"] is not None else "-"
        logger.info(
            "  %-16s %-10s %-20s %-8s %8d %10s",
            r["instrument_id"], r["ticker"], name, r["market"],
            r["priority"], weight,
        )


# ── 메인 ─────────────────────────────────────────────────────


def build_entries(
    args: argparse.Namespace,
) -> list[tuple[str, int, Decimal | None, str | None]]:
    """CLI 인자에서 시딩 항목 리스트를 생성."""
    weight = Decimal(str(args.max_weight)) if args.max_weight is not None else None
    memo = args.memo

    if args.tickers:
        # --tickers 지정: 모두 동일 priority
        ids = [t.strip() for t in args.tickers.split(",") if t.strip()]
        return [(iid, args.priority, weight, memo) for iid in ids]

    if args.from_instruments:
        # --from-instruments: 비동기로 조회해야 하므로 placeholder 반환
        # 실제 조회는 main_async에서 처리
        return []  # sentinel — main_async에서 대체

    # 기본: 핵심 3종목 (개별 priority)
    return [(iid, pri, weight, memo) for iid, pri in DEFAULT_TICKERS]


async def main_async(args: argparse.Namespace) -> None:
    pool = await get_pool()

    # --from-instruments 모드: 활성 종목 전체 조회
    if args.from_instruments:
        instrument_ids = await fetch_active_instruments(pool)
        if not instrument_ids:
            logger.error("instruments 테이블에 활성 종목이 없습니다.")
            sys.exit(1)

        weight = Decimal(str(args.max_weight)) if args.max_weight is not None else None
        entries = [(iid, args.priority, weight, args.memo) for iid in instrument_ids]
        logger.info("[from-instruments] 활성 종목 %d개를 scope='%s'에 시딩합니다.", len(entries), args.scope)
    else:
        entries = build_entries(args)

    if not entries:
        logger.error("시딩할 종목이 없습니다.")
        sys.exit(1)

    await seed(
        args.scope,
        entries,
        clear=args.clear,
        dry_run=args.dry_run,
    )

    # dry-run이 아니면 검증 쿼리 실행
    if not args.dry_run:
        await verify(args.scope)
    else:
        logger.info("(dry-run 모드에서는 검증 쿼리를 건너뜁니다)")


def main():
    parser = argparse.ArgumentParser(
        description="trading_universe 시딩 — 종목을 account_scope에 매핑",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  %(prog)s                              # 기본: paper 3종목
  %(prog)s --scope real --tickers 005930.KS,000660.KS
  %(prog)s --scope paper --from-instruments --max-weight 20
  %(prog)s --scope paper --clear        # 기존 삭제 후 재시딩
  %(prog)s --dry-run                    # 미리보기
        """,
    )
    parser.add_argument(
        "--scope", default="paper",
        help="account_scope (default: paper)",
    )
    parser.add_argument(
        "--tickers",
        help="콤마 구분 instrument_id (예: 005930.KS,000660.KS,035420.KS)",
    )
    parser.add_argument(
        "--from-instruments", action="store_true",
        help="instruments 테이블의 모든 활성 종목을 시딩",
    )
    parser.add_argument(
        "--priority", type=int, default=0,
        help="priority 값 (default: 0, --tickers/--from-instruments 시 적용)",
    )
    parser.add_argument(
        "--max-weight", type=float, default=None,
        help="max_weight_pct (예: 20 → 20%%)",
    )
    parser.add_argument(
        "--memo", default=None,
        help="memo 텍스트",
    )
    parser.add_argument(
        "--clear", action="store_true",
        help="해당 scope의 기존 레코드를 모두 삭제 후 재시딩",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="실제 DB 변경 없이 미리보기만 출력",
    )
    args = parser.parse_args()

    if args.tickers and args.from_instruments:
        parser.error("--tickers와 --from-instruments는 동시에 사용할 수 없습니다.")

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
