"""
scripts/db/seed_all_instruments.py — FDR 전 종목 등록 + 12년 일봉 수집

1단계: KOSPI/KOSDAQ/NYSE/NASDAQ 종목을 instruments 테이블에 등록
2단계: 각 종목의 FDR 최대 일봉(~3000일)을 ohlcv_daily에 수집 (float NUMERIC)

사용법:
  python scripts/db/seed_all_instruments.py                    # 전체 (KR+US)
  python scripts/db/seed_all_instruments.py --market KR        # 한국만
  python scripts/db/seed_all_instruments.py --market US        # 미장만
  python scripts/db/seed_all_instruments.py --instruments-only # 종목 등록만
  python scripts/db/seed_all_instruments.py --ohlcv-only       # 일봉 수집만
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import FinanceDataReader as fdr
from src.utils.db_client import execute, executemany, fetchval, get_pool
from src.utils.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


# ── 종목 등록 ─────────────────────────────────────────────────


async def seed_instruments(markets: list[str]) -> int:
    """FDR StockListing으로 instruments 테이블에 종목 등록."""
    total = 0

    for market_id in markets:
        logger.info("[instruments] %s 종목 목록 조회 중...", market_id)
        listing = fdr.StockListing(market_id)

        if market_id in ("KOSPI", "KOSDAQ"):
            suffix = ".KS" if market_id == "KOSPI" else ".KQ"
            code_col, name_col = "Code", "Name"
            sector_col = None
            industry_col = None
            isin_col = "ISU_CD" if "ISU_CD" in listing.columns else None
            marcap_col = "Marcap" if "Marcap" in listing.columns else None
            stocks_col = "Stocks" if "Stocks" in listing.columns else None
        else:
            suffix = ".US"
            code_col = "Symbol"
            name_col = "Name"
            sector_col = None
            industry_col = "Industry" if "Industry" in listing.columns else None
            isin_col = None
            marcap_col = None
            stocks_col = None

        rows = []
        for _, row in listing.iterrows():
            raw_code = str(row[code_col]).strip()
            if not raw_code or len(raw_code) > 15:
                continue
            instrument_id = f"{raw_code}{suffix}"
            name = str(row[name_col]).strip() if row[name_col] else raw_code

            rows.append((
                instrument_id,
                raw_code,
                name,
                market_id,
                str(row[sector_col]) if sector_col and row.get(sector_col) else None,
                str(row[industry_col]) if industry_col and row.get(industry_col) else None,
                "stock",
                str(row[isin_col]) if isin_col and row.get(isin_col) else None,
                int(row[marcap_col]) if marcap_col and row.get(marcap_col) else None,
                int(row[stocks_col]) if stocks_col and row.get(stocks_col) else None,
            ))

        query = """
            INSERT INTO instruments (
                instrument_id, raw_code, name, market_id,
                sector, industry, asset_type, isin,
                market_cap, total_shares
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (instrument_id) DO UPDATE SET
                name = EXCLUDED.name,
                sector = EXCLUDED.sector,
                industry = EXCLUDED.industry,
                market_cap = EXCLUDED.market_cap,
                total_shares = EXCLUDED.total_shares,
                updated_at = now()
        """
        await executemany(query, rows)
        logger.info("[instruments] %s: %d종목 등록 완료", market_id, len(rows))
        total += len(rows)

    return total


# ── OHLCV 수집 ────────────────────────────────────────────────


async def seed_ohlcv(markets: list[str], batch_size: int = 50) -> dict:
    """instruments에 등록된 종목의 FDR 최대 일봉을 ohlcv_daily에 수집."""
    pool = await get_pool()

    stats = {"total": 0, "success": 0, "failed": 0, "rows": 0}

    for market_id in markets:
        # 해당 시장 종목 조회
        async with pool.acquire() as conn:
            instruments = await conn.fetch(
                "SELECT instrument_id, raw_code FROM instruments "
                "WHERE market_id = $1 AND is_active = true ORDER BY instrument_id",
                market_id,
            )

        logger.info("[ohlcv] %s: %d종목 수집 시작", market_id, len(instruments))
        stats["total"] += len(instruments)

        for i, inst in enumerate(instruments, 1):
            instrument_id = inst["instrument_id"]
            raw_code = inst["raw_code"]

            try:
                # FDR 최대 기간 조회
                df = fdr.DataReader(raw_code, "2010-01-01")

                if df is None or df.empty:
                    logger.debug("[ohlcv] %s: 데이터 없음, 스킵", instrument_id)
                    stats["failed"] += 1
                    continue

                # float 변환 + upsert 준비
                rows = []
                for date_idx, row in df.iterrows():
                    traded_at = date_idx.date() if hasattr(date_idx, "date") else date_idx
                    rows.append((
                        instrument_id,
                        traded_at,
                        float(row.get("Open", 0)),
                        float(row.get("High", 0)),
                        float(row.get("Low", 0)),
                        float(row.get("Close", 0)),
                        int(row.get("Volume", 0)),
                        float(row.get("Change", 0)) * 100 if row.get("Change") is not None else None,
                        float(row.get("Adj Close", 0)) if "Adj Close" in row.index else None,
                    ))

                query = """
                    INSERT INTO ohlcv_daily (
                        instrument_id, traded_at, open, high, low, close,
                        volume, change_pct, adj_close
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (instrument_id, traded_at) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        change_pct = EXCLUDED.change_pct,
                        adj_close = EXCLUDED.adj_close
                """
                await executemany(query, rows)

                stats["success"] += 1
                stats["rows"] += len(rows)

                if i % batch_size == 0 or i == len(instruments):
                    logger.info(
                        "[ohlcv] %s: %d/%d 완료 (성공: %d, 누적 행: %s)",
                        market_id, i, len(instruments),
                        stats["success"], f"{stats['rows']:,}",
                    )

                # FDR rate limit
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.warning("[ohlcv] %s 수집 실패: %s", instrument_id, e)
                stats["failed"] += 1
                await asyncio.sleep(1.0)

    return stats


# ── 메인 ──────────────────────────────────────────────────────


async def main_async(args: argparse.Namespace) -> None:
    started = time.time()

    if args.market == "KR":
        markets = ["KOSPI", "KOSDAQ"]
    elif args.market == "US":
        markets = ["NYSE", "NASDAQ"]
    else:
        markets = ["KOSPI", "KOSDAQ", "NYSE", "NASDAQ"]

    if not args.ohlcv_only:
        count = await seed_instruments(markets)
        logger.info("=== instruments 등록 완료: %d종목 ===", count)

    if not args.instruments_only:
        stats = await seed_ohlcv(markets)
        elapsed = time.time() - started
        logger.info(
            "\n=== OHLCV 수집 완료 ===\n"
            "  종목: %d (성공: %d, 실패: %d)\n"
            "  총 행: %s\n"
            "  소요 시간: %.1f분",
            stats["total"], stats["success"], stats["failed"],
            f"{stats['rows']:,}",
            elapsed / 60,
        )


def main():
    parser = argparse.ArgumentParser(description="FDR 전 종목 등록 + 12년 일봉 수집")
    parser.add_argument("--market", choices=["KR", "US", "ALL"], default="ALL")
    parser.add_argument("--instruments-only", action="store_true", help="종목 등록만")
    parser.add_argument("--ohlcv-only", action="store_true", help="일봉 수집만")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
