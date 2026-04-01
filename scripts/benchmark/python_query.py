#!/usr/bin/env python3
"""
python_query.py — asyncpg 쿼리 성능 벤치마크

EXPLAIN ANALYZE 기반으로 주요 쿼리 패턴의 실행 계획과 성능을 측정합니다.

실행:
    python3 scripts/benchmark/python_query.py

환경변수:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS
"""
from __future__ import annotations

import asyncio
import os
import time

import asyncpg  # type: ignore[import-untyped]


DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "alpha_db")
DB_USER = os.environ.get("DB_USER", "alpha_user")
DB_PASS = os.environ.get("DB_PASS", "alpha_pass")

ITERATIONS = 5  # 각 쿼리 반복 횟수
SEPARATOR = "─" * 64


async def get_sample_tickers(conn: asyncpg.Connection, n: int = 20) -> list[str]:
    """데이터가 충분한 종목 N개를 랜덤 선택합니다."""
    rows = await conn.fetch(
        """
        SELECT instrument_id FROM (
            SELECT instrument_id, count(*) AS cnt
              FROM ohlcv_daily
             GROUP BY instrument_id
            HAVING count(*) > 100
             ORDER BY random()
             LIMIT $1
        ) t
        """,
        n,
    )
    return [r["instrument_id"] for r in rows]


async def explain_query(
    conn: asyncpg.Connection, query: str, *args: object
) -> tuple[str, float]:
    """EXPLAIN ANALYZE를 실행하고 플랜 텍스트 + execution time(ms)을 반환합니다."""
    explain_q = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {query}"
    rows = await conn.fetch(explain_q, *args)
    plan_lines = [r[0] for r in rows]
    plan_text = "\n".join(plan_lines)

    exec_time = 0.0
    for line in plan_lines:
        if "Execution Time" in line:
            # "Execution Time: 1.234 ms"
            parts = line.split(":")
            if len(parts) >= 2:
                exec_time = float(parts[1].strip().replace(" ms", ""))
    return plan_text, exec_time


async def timed_query(
    conn: asyncpg.Connection, query: str, *args: object
) -> tuple[list[asyncpg.Record], float]:
    """쿼리를 실행하고 결과 + wall-clock 시간(ms)을 반환합니다."""
    t0 = time.perf_counter()
    rows = await conn.fetch(query, *args)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return rows, elapsed_ms


async def bench_a_single_ticker_30d(
    conn: asyncpg.Connection, ticker: str
) -> None:
    """[A] 단일 종목 30일 조회 — 파티션 프루닝 확인."""
    query = """
        SELECT instrument_id, traded_at, open, high, low, close, volume
          FROM ohlcv_daily
         WHERE instrument_id = $1
           AND traded_at >= CURRENT_DATE - INTERVAL '30 days'
         ORDER BY traded_at DESC
    """
    print(f"\n{SEPARATOR}")
    print(f"  [A] 단일 종목 30일 조회 (ticker: {ticker})")
    print(f"{SEPARATOR}")

    plan, _ = await explain_query(conn, query, ticker)
    print(plan)

    times = []
    for _ in range(ITERATIONS):
        _, ms = await timed_query(conn, query, ticker)
        times.append(ms)

    avg = sum(times) / len(times)
    mn, mx = min(times), max(times)
    print(f"\n  {ITERATIONS}회 실행: avg={avg:.2f}ms  min={mn:.2f}ms  max={mx:.2f}ms")

    # 파티션 프루닝 확인
    if "Seq Scan on ohlcv_daily_" in plan or "Index Scan" in plan:
        pruned = [line for line in plan.split("\n") if "ohlcv_daily_" in line]
        n_partitions = len(set(line.strip().split()[-1] for line in pruned if "ohlcv_daily_" in line))
        print(f"  파티션 프루닝: {n_partitions}개 파티션만 스캔")
    else:
        print("  파티션 프루닝: 확인 필요 (위 EXPLAIN 출력 참고)")


async def bench_b_all_latest_close(conn: asyncpg.Connection) -> None:
    """[B] 전체 종목 최신 종가 집계."""
    query = """
        SELECT instrument_id, close, volume
          FROM ohlcv_daily
         WHERE traded_at = (SELECT MAX(traded_at) FROM ohlcv_daily)
         ORDER BY close DESC
         LIMIT 50
    """
    print(f"\n{SEPARATOR}")
    print("  [B] 전체 종목 최신 종가 집계 (TOP 50)")
    print(f"{SEPARATOR}")

    plan, _ = await explain_query(conn, query)
    print(plan)

    times = []
    for _ in range(ITERATIONS):
        rows, ms = await timed_query(conn, query)
        times.append(ms)

    avg = sum(times) / len(times)
    print(f"\n  {ITERATIONS}회 실행: avg={avg:.2f}ms  min={min(times):.2f}ms  max={max(times):.2f}ms")
    print(f"  반환 행 수: {len(rows)}")


async def bench_c_n_plus_one_vs_batch(
    conn: asyncpg.Connection, tickers: list[str]
) -> None:
    """[C] N+1 패턴 vs 배치 패턴 비교."""
    n = min(len(tickers), 20)
    test_tickers = tickers[:n]

    print(f"\n{SEPARATOR}")
    print(f"  [C] N+1 패턴 vs 배치 패턴 비교 ({n}개 종목)")
    print(f"{SEPARATOR}")

    # N+1 패턴: 종목별 개별 쿼리
    single_query = """
        SELECT instrument_id, traded_at, close, volume
          FROM ohlcv_daily
         WHERE instrument_id = $1
           AND traded_at >= CURRENT_DATE - INTERVAL '30 days'
         ORDER BY traded_at DESC
    """
    n1_times = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        for t in test_tickers:
            await conn.fetch(single_query, t)
        elapsed = (time.perf_counter() - t0) * 1000
        n1_times.append(elapsed)

    # 배치 패턴: IN 절로 한 번에 조회
    batch_query = """
        SELECT instrument_id, traded_at, close, volume
          FROM ohlcv_daily
         WHERE instrument_id = ANY($1::text[])
           AND traded_at >= CURRENT_DATE - INTERVAL '30 days'
         ORDER BY instrument_id, traded_at DESC
    """
    batch_times = []
    for _ in range(ITERATIONS):
        _, ms = await timed_query(conn, batch_query, test_tickers)
        batch_times.append(ms)

    n1_avg = sum(n1_times) / len(n1_times)
    batch_avg = sum(batch_times) / len(batch_times)
    speedup = n1_avg / batch_avg if batch_avg > 0 else float("inf")

    print(f"\n  N+1 패턴   ({n}개 개별 쿼리): avg={n1_avg:.2f}ms")
    print(f"  배치 패턴  (ANY 1회 쿼리)  : avg={batch_avg:.2f}ms")
    print(f"  속도 개선: {speedup:.1f}x")

    # 배치 쿼리 EXPLAIN
    print("\n  배치 쿼리 EXPLAIN:")
    plan, _ = await explain_query(conn, batch_query, test_tickers)
    print(plan)


async def bench_d_partition_vs_full(
    conn: asyncpg.Connection, ticker: str
) -> None:
    """[D] 파티션 프루닝 vs 전체 스캔 비교."""
    pruned_query = """
        SELECT instrument_id, traded_at, close, volume
          FROM ohlcv_daily
         WHERE instrument_id = $1
           AND traded_at >= '2025-01-01' AND traded_at < '2026-01-01'
         ORDER BY traded_at DESC
    """
    full_query = """
        SELECT instrument_id, traded_at, close, volume
          FROM ohlcv_daily
         WHERE instrument_id = $1
         ORDER BY traded_at DESC
    """

    print(f"\n{SEPARATOR}")
    print(f"  [D] 파티션 프루닝 vs 전체 스캔 (ticker: {ticker})")
    print(f"{SEPARATOR}")

    # Pruned
    print("\n  --- 파티션 프루닝 (2025년만) ---")
    plan_pruned, _ = await explain_query(conn, pruned_query, ticker)
    print(plan_pruned)

    pruned_times = []
    for _ in range(ITERATIONS):
        _, ms = await timed_query(conn, pruned_query, ticker)
        pruned_times.append(ms)

    # Full scan
    print("\n  --- 전체 스캔 (날짜 조건 없음) ---")
    plan_full, _ = await explain_query(conn, full_query, ticker)
    print(plan_full)

    full_times = []
    for _ in range(ITERATIONS):
        _, ms = await timed_query(conn, full_query, ticker)
        full_times.append(ms)

    pruned_avg = sum(pruned_times) / len(pruned_times)
    full_avg = sum(full_times) / len(full_times)
    speedup = full_avg / pruned_avg if pruned_avg > 0 else float("inf")

    print(f"\n  프루닝 쿼리 : avg={pruned_avg:.2f}ms")
    print(f"  전체 스캔   : avg={full_avg:.2f}ms")
    print(f"  속도 개선   : {speedup:.1f}x")


async def main() -> None:
    conn = await asyncpg.connect(
        host=DB_HOST, port=DB_PORT,
        database=DB_NAME, user=DB_USER, password=DB_PASS,
    )

    print("=" * 64)
    print("  asyncpg 쿼리 벤치마크 — ohlcv_daily")
    print("=" * 64)

    # 테이블 기본 정보
    count = await conn.fetchval("SELECT count(*) FROM ohlcv_daily")
    tickers_count = await conn.fetchval(
        "SELECT count(DISTINCT instrument_id) FROM ohlcv_daily"
    )
    size = await conn.fetchval(
        "SELECT pg_size_pretty(pg_total_relation_size('ohlcv_daily'))"
    )
    print(f"\n  행 수      : {count:,}")
    print(f"  종목 수    : {tickers_count:,}")
    print(f"  테이블 크기: {size}")

    # 샘플 종목 준비
    tickers = await get_sample_tickers(conn, 20)
    if not tickers:
        print("\n  ERROR: 데이터가 부족합니다. ohlcv_daily에 데이터를 먼저 적재하세요.")
        await conn.close()
        return

    sample_ticker = tickers[0]

    # 벤치마크 실행
    await bench_a_single_ticker_30d(conn, sample_ticker)
    await bench_b_all_latest_close(conn)
    await bench_c_n_plus_one_vs_batch(conn, tickers)
    await bench_d_partition_vs_full(conn, sample_ticker)

    # 최종 요약 테이블
    print(f"\n{'=' * 64}")
    print("  최종 요약")
    print(f"{'=' * 64}")
    print()
    print(f"  {'쿼리 패턴':<35} {'평균 (ms)':>10} {'비고'}")
    print(f"  {'─' * 35} {'─' * 10} {'─' * 25}")

    # 요약을 위해 다시 간단히 측정
    summary_queries = [
        ("단일 종목 30일", f"""
            SELECT * FROM ohlcv_daily
            WHERE instrument_id = '{sample_ticker}'
              AND traded_at >= CURRENT_DATE - INTERVAL '30 days'
        """, "파티션 프루닝"),
        ("전체 최신 종가 TOP50", """
            SELECT instrument_id, close FROM ohlcv_daily
            WHERE traded_at = (SELECT MAX(traded_at) FROM ohlcv_daily)
            ORDER BY close DESC LIMIT 50
        """, "서브쿼리"),
        ("배치 IN 20종목 30일", f"""
            SELECT * FROM ohlcv_daily
            WHERE instrument_id = ANY(ARRAY{tickers!r}::text[])
              AND traded_at >= CURRENT_DATE - INTERVAL '30 days'
        """, "ANY 연산자"),
        ("전체 스캔 (프루닝 없음)", f"""
            SELECT * FROM ohlcv_daily
            WHERE instrument_id = '{sample_ticker}'
            ORDER BY traded_at DESC
        """, "모든 파티션"),
    ]

    for label, q, note in summary_queries:
        times = []
        for _ in range(3):
            _, ms = await timed_query(conn, q)
            times.append(ms)
        avg = sum(times) / len(times)
        print(f"  {label:<35} {avg:>10.2f} {note}")

    print()
    print("=" * 64)

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
