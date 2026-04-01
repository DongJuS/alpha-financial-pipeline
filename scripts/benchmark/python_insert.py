#!/usr/bin/env python3
"""
python_insert.py — asyncpg 배치 INSERT 처리량 벤치마크

ohlcv_daily 테이블에 대한 배치 INSERT 성능을 측정합니다.
트랜잭션 롤백으로 실제 데이터를 오염시키지 않습니다.

실행:
    python3 scripts/benchmark/python_insert.py
    python3 scripts/benchmark/python_insert.py --rows 100000

환경변수:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import time
from datetime import date, timedelta

import asyncpg  # type: ignore[import-untyped]


DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "alpha_db")
DB_USER = os.environ.get("DB_USER", "alpha_user")
DB_PASS = os.environ.get("DB_PASS", "alpha_pass")


def generate_rows(n: int) -> list[tuple]:
    """벤치마크용 가짜 OHLCV 행을 생성합니다."""
    base_date = date(2099, 1, 1)  # 실제 데이터와 겹치지 않는 미래 날짜
    rows = []
    for i in range(n):
        ticker = f"BENCH_{i % 500:04d}.KS"
        traded = base_date + timedelta(days=i // 500)
        o = round(50000 + random.random() * 50000, 4)
        h = round(o + random.random() * 5000, 4)
        low = round(o - random.random() * 5000, 4)
        c = round(o + (random.random() - 0.5) * 3000, 4)
        v = random.randint(1000, 10_000_000)
        chg = round((random.random() - 0.5) * 10, 4)
        rows.append((ticker, traded, o, h, low, c, v, chg, None))
    return rows


async def bench_executemany(
    conn: asyncpg.Connection, rows: list[tuple], label: str
) -> dict:
    """executemany INSERT 후 ROLLBACK, 소요시간 측정."""
    query = """
        INSERT INTO ohlcv_daily (
            instrument_id, traded_at,
            open, high, low, close, volume,
            change_pct, adj_close
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (instrument_id, traded_at) DO NOTHING
    """
    tr = conn.transaction()
    await tr.start()
    try:
        t0 = time.perf_counter()
        await conn.executemany(query, rows)
        elapsed = time.perf_counter() - t0
    finally:
        await tr.rollback()

    rps = len(rows) / elapsed if elapsed > 0 else 0
    return {
        "label": label,
        "rows": len(rows),
        "elapsed_sec": round(elapsed, 3),
        "rows_per_sec": round(rps),
    }


async def bench_copy(
    conn: asyncpg.Connection, rows: list[tuple], label: str
) -> dict:
    """COPY (binary) INSERT 후 ROLLBACK, 소요시간 측정."""
    columns = [
        "instrument_id", "traded_at",
        "open", "high", "low", "close", "volume",
        "change_pct", "adj_close",
    ]
    tr = conn.transaction()
    await tr.start()
    try:
        t0 = time.perf_counter()
        await conn.copy_records_to_table(
            "ohlcv_daily", records=rows, columns=columns
        )
        elapsed = time.perf_counter() - t0
    finally:
        await tr.rollback()

    rps = len(rows) / elapsed if elapsed > 0 else 0
    return {
        "label": label,
        "rows": len(rows),
        "elapsed_sec": round(elapsed, 3),
        "rows_per_sec": round(rps),
    }


async def main(row_counts: list[int]) -> None:
    conn = await asyncpg.connect(
        host=DB_HOST, port=DB_PORT,
        database=DB_NAME, user=DB_USER, password=DB_PASS,
    )

    print("=" * 64)
    print("  asyncpg INSERT 벤치마크 — ohlcv_daily")
    print("=" * 64)
    print()

    # 현재 테이블 크기 확인
    count = await conn.fetchval("SELECT count(*) FROM ohlcv_daily")
    size = await conn.fetchval(
        "SELECT pg_size_pretty(pg_total_relation_size('ohlcv_daily'))"
    )
    print(f"  현재 행 수 : {count:,}")
    print(f"  테이블 크기: {size}")
    print()

    results = []

    for n in row_counts:
        print(f"  생성 중: {n:,} rows ...", end=" ", flush=True)
        rows = generate_rows(n)
        print("완료")

        # executemany
        print(f"  executemany {n:,} rows ...", end=" ", flush=True)
        r = await bench_executemany(conn, rows, f"executemany_{n}")
        results.append(r)
        print(f"{r['elapsed_sec']}s ({r['rows_per_sec']:,} rows/sec)")

        # COPY
        print(f"  COPY        {n:,} rows ...", end=" ", flush=True)
        r = await bench_copy(conn, rows, f"copy_{n}")
        results.append(r)
        print(f"{r['elapsed_sec']}s ({r['rows_per_sec']:,} rows/sec)")

        print()

    # 결과 테이블
    print("=" * 64)
    print("  결과 요약")
    print("=" * 64)
    print()
    print(f"  {'Method':<25} {'Rows':>10} {'Time (s)':>10} {'Rows/sec':>12}")
    print(f"  {'─' * 25} {'─' * 10} {'─' * 10} {'─' * 12}")
    for r in results:
        print(
            f"  {r['label']:<25} {r['rows']:>10,} {r['elapsed_sec']:>10.3f} "
            f"{r['rows_per_sec']:>12,}"
        )
    print()
    print("  * 모든 INSERT는 트랜잭션 ROLLBACK 처리되어 실제 데이터에 영향 없음")
    print("=" * 64)

    await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="asyncpg INSERT benchmark")
    parser.add_argument(
        "--rows", type=int, nargs="+",
        default=[10_000, 100_000],
        help="테스트할 행 수 목록 (기본: 10000 100000)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.rows))
