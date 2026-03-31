#!/usr/bin/env python3
"""
fdr_throughput.py — FDR 수집 파이프라인 처리량 벤치마크

FDR에서 종목 데이터를 수집하여 ohlcv_daily에 INSERT하는 전체 파이프라인의
처리량(종목/분, 행/초)을 측정합니다.

실행:
    python3 scripts/benchmark/fdr_throughput.py
    python3 scripts/benchmark/fdr_throughput.py --tickers 100
    python3 scripts/benchmark/fdr_throughput.py --tickers ALL

환경변수:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import FinanceDataReader as fdr
import asyncpg


async def get_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ.get("DB_NAME", "alpha_db"),
        user=os.environ.get("DB_USER", "alpha_user"),
        password=os.environ.get("DB_PASS", "alpha_pass"),
        min_size=2,
        max_size=10,
    )


async def benchmark_fdr(ticker_count: int | str) -> dict:
    # 종목 목록 준비
    print(f"[1/3] 종목 목록 조회 중...")
    kospi = fdr.StockListing("KOSPI")
    kosdaq = fdr.StockListing("KOSDAQ")
    all_tickers = [(r["Code"], "KOSPI") for _, r in kospi.iterrows()] + \
                  [(r["Code"], "KOSDAQ") for _, r in kosdaq.iterrows()]

    if ticker_count == "ALL":
        target = all_tickers
    else:
        target = all_tickers[:int(ticker_count)]

    print(f"[2/3] FDR 수집 + DB INSERT 시작 ({len(target)}종목)...")
    pool = await get_pool()

    total_rows = 0
    success = 0
    failed = 0
    started = time.monotonic()

    for i, (code, market) in enumerate(target, 1):
        try:
            df = fdr.DataReader(code, "2024-01-01")
            if df is None or df.empty:
                failed += 1
                continue

            suffix = ".KS" if market == "KOSPI" else ".KQ"
            instrument_id = f"{code}{suffix}"
            rows = [
                (instrument_id, d.date(), float(r["Open"]), float(r["High"]),
                 float(r["Low"]), float(r["Close"]), int(r["Volume"]),
                 float(r.get("Change", 0)) * 100 if r.get("Change") is not None else None)
                for d, r in df.iterrows()
            ]

            async with pool.acquire() as conn:
                await conn.executemany(
                    """INSERT INTO ohlcv_daily (instrument_id, traded_at, open, high, low, close, volume, change_pct)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT (instrument_id, traded_at) DO UPDATE SET
                        close = EXCLUDED.close, volume = EXCLUDED.volume""",
                    rows,
                )

            total_rows += len(rows)
            success += 1

            if i % 50 == 0:
                elapsed = time.monotonic() - started
                rate = total_rows / elapsed if elapsed > 0 else 0
                print(f"  {i}/{len(target)} 종목 ({total_rows:,}행, {rate:,.0f}행/초)")

            await asyncio.sleep(0.2)  # FDR rate limit

        except Exception as e:
            failed += 1

    elapsed = time.monotonic() - started
    await pool.close()

    result = {
        "benchmark": "fdr_throughput",
        "target_tickers": len(target),
        "success": success,
        "failed": failed,
        "total_rows": total_rows,
        "elapsed_seconds": round(elapsed, 2),
        "rows_per_second": round(total_rows / elapsed, 1) if elapsed > 0 else 0,
        "tickers_per_minute": round(success / (elapsed / 60), 1) if elapsed > 0 else 0,
        "summary": f"{success}종목 {total_rows:,}행을 {elapsed:.1f}초({elapsed/60:.1f}분)에 적재. {total_rows/elapsed:,.0f}행/초",
    }

    print(f"\n[3/3] 완료")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 결과 저장
    result_dir = Path(__file__).parent / "results"
    result_dir.mkdir(exist_ok=True)
    with open(result_dir / "fdr_throughput.json", "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def main():
    parser = argparse.ArgumentParser(description="FDR 수집 처리량 벤치마크")
    parser.add_argument("--tickers", default="100", help="측정 종목 수 (100, 1000, ALL)")
    args = parser.parse_args()
    asyncio.run(benchmark_fdr(args.tickers))


if __name__ == "__main__":
    main()
