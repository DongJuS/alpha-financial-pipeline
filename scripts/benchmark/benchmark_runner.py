#!/usr/bin/env python3
"""
benchmark_runner.py — 벤치마크 실행 + 보고서 생성

K8s Job 또는 로컬에서 실행 가능.
DB/S3 접속은 환경변수로 설정.

실행:
    python3 scripts/benchmark/benchmark_runner.py
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import random
import sys
import time
from datetime import datetime

sys.path.insert(0, os.environ.get("PYTHONPATH", "/app"))

TS = os.environ.get("BENCHMARK_TIMESTAMP", datetime.utcnow().strftime("%Y%m%d_%H%M%S"))

report = {
    "timestamp": TS,
    "generated_at": datetime.utcnow().isoformat() + "Z",
    "benchmarks": {},
    "summary": {},
}


def section(name: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")


async def query_bench() -> dict:
    import asyncpg
    conn = await asyncpg.connect(
        host=os.environ.get("DB_HOST", "alpha-pg-postgresql"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ.get("DB_NAME", "alpha_db"),
        user=os.environ.get("DB_USER", "alpha_user"),
        password=os.environ.get("DB_PASS", "alpha_pass"),
    )

    total_rows = await conn.fetchval("SELECT count(*) FROM ohlcv_daily")
    print(f"  Total rows: {total_rows:,}")

    queries = {
        "single_ticker_30d": {
            "sql": "SELECT * FROM ohlcv_daily WHERE instrument_id = '005930.KS' AND traded_at >= CURRENT_DATE - 30 * INTERVAL '1 day'",
            "desc": "단일 종목 30일 조회",
        },
        "single_ticker_720d": {
            "sql": "SELECT * FROM ohlcv_daily WHERE instrument_id = '005930.KS' AND traded_at >= CURRENT_DATE - 720 * INTERVAL '1 day'",
            "desc": "단일 종목 720일 조회",
        },
        "count_all": {
            "sql": "SELECT count(*) FROM ohlcv_daily",
            "desc": "전체 행 수 집계",
        },
        "top20_volume": {
            "sql": "SELECT instrument_id, sum(volume) as v FROM ohlcv_daily WHERE traded_at >= CURRENT_DATE - 30 * INTERVAL '1 day' GROUP BY instrument_id ORDER BY v DESC LIMIT 20",
            "desc": "30일 거래량 TOP 20",
        },
        "partition_pruning": {
            "sql": "SELECT * FROM ohlcv_daily WHERE instrument_id = '005930.KS' AND traded_at >= '2026-01-01' AND traded_at < '2026-04-01'",
            "desc": "파티션 pruning (2026 Q1)",
        },
    }

    results = {"total_rows": total_rows}
    for name, q in queries.items():
        times = []
        for _ in range(5):
            start = time.monotonic()
            await conn.fetch(q["sql"])
            times.append(round((time.monotonic() - start) * 1000, 2))
        avg = round(sum(times) / len(times), 2)
        results[name] = {"desc": q["desc"], "runs": times, "avg_ms": avg, "min_ms": min(times), "max_ms": max(times)}
        print(f"  {q['desc']}: {avg}ms (min={min(times)}, max={max(times)})")

    plan = await conn.fetch("EXPLAIN ANALYZE " + queries["partition_pruning"]["sql"])
    results["partition_explain"] = "\n".join(r[0] for r in plan)

    await conn.close()
    return results


async def insert_bench() -> dict:
    import asyncpg
    conn = await asyncpg.connect(
        host=os.environ.get("DB_HOST", "alpha-pg-postgresql"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ.get("DB_NAME", "alpha_db"),
        user=os.environ.get("DB_USER", "alpha_user"),
        password=os.environ.get("DB_PASS", "alpha_pass"),
    )

    results = {}
    for n in [1000, 10000, 50000]:
        from datetime import date as date_cls
        rows = [
            (f"BENCH{i:06d}.KS", date_cls(2020, 1, (i % 28) + 1),
             random.uniform(10000, 500000), random.uniform(10000, 500000),
             random.uniform(10000, 500000), random.uniform(10000, 500000),
             random.randint(1000, 10000000), random.uniform(-5, 5))
            for i in range(n)
        ]

        tx = conn.transaction()
        await tx.start()
        start = time.monotonic()
        await conn.executemany(
            "INSERT INTO ohlcv_daily (instrument_id, traded_at, open, high, low, close, volume, change_pct) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT DO NOTHING",
            rows,
        )
        em_time = time.monotonic() - start
        await tx.rollback()

        tx = conn.transaction()
        await tx.start()
        start = time.monotonic()
        await conn.copy_records_to_table(
            "ohlcv_daily", records=rows,
            columns=["instrument_id", "traded_at", "open", "high", "low", "close", "volume", "change_pct"],
        )
        cp_time = time.monotonic() - start
        await tx.rollback()

        results[f"{n}_rows"] = {
            "executemany_sec": round(em_time, 3), "executemany_rps": round(n / em_time),
            "copy_sec": round(cp_time, 3), "copy_rps": round(n / cp_time),
        }
        print(f"  {n:,}행: executemany={n / em_time:,.0f}행/초, COPY={n / cp_time:,.0f}행/초")

    await conn.close()
    return results


def s3_bench() -> dict:
    import boto3
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL", "http://minio:9000"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "minioadmin"),
        region_name="ap-northeast-2",
    )
    bucket = os.environ.get("S3_BUCKET_NAME", "alpha-lake")

    results = {}
    for size_kb in [100, 1000, 10000, 50000]:
        data = io.BytesIO(os.urandom(size_kb * 1024))
        key = f"benchmark/test_{size_kb}kb_{TS}.bin"
        mb = size_kb / 1024

        data.seek(0)
        start = time.monotonic()
        s3.upload_fileobj(data, bucket, key)
        up = time.monotonic() - start

        dl = io.BytesIO()
        start = time.monotonic()
        s3.download_fileobj(bucket, key, dl)
        dn = time.monotonic() - start

        s3.delete_object(Bucket=bucket, Key=key)

        results[f"{size_kb}kb"] = {
            "mb": round(mb, 2), "upload_sec": round(up, 3),
            "upload_mbps": round(mb / up, 1) if up > 0 else 0,
            "download_sec": round(dn, 3),
            "download_mbps": round(mb / dn, 1) if dn > 0 else 0,
        }
        print(f"  {size_kb}KB: upload={mb / up:.1f}MB/s, download={mb / dn:.1f}MB/s")
    return results


async def partition_stats() -> dict:
    import asyncpg
    conn = await asyncpg.connect(
        host=os.environ.get("DB_HOST", "alpha-pg-postgresql"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ.get("DB_NAME", "alpha_db"),
        user=os.environ.get("DB_USER", "alpha_user"),
        password=os.environ.get("DB_PASS", "alpha_pass"),
    )
    sizes = await conn.fetch("""
        SELECT schemaname||'.'||tablename as p,
               pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
               pg_total_relation_size(schemaname||'.'||tablename) as bytes
        FROM pg_tables WHERE tablename LIKE 'ohlcv_daily_%%' AND tablename != 'ohlcv_daily_default'
        ORDER BY tablename""")
    total_bytes = sum(r["bytes"] for r in sizes)
    result = {
        "partitions": [{"name": r["p"], "size": r["size"]} for r in sizes],
        "partition_count": len(sizes),
        "total_size_gb": round(total_bytes / (1024 * 1024 * 1024), 2),
    }
    for r in sizes:
        print(f"  {r['p']}: {r['size']}")
    print(f"  Total: {result['total_size_gb']} GB")
    await conn.close()
    return result


async def data_stats() -> dict:
    import asyncpg
    conn = await asyncpg.connect(
        host=os.environ.get("DB_HOST", "alpha-pg-postgresql"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ.get("DB_NAME", "alpha_db"),
        user=os.environ.get("DB_USER", "alpha_user"),
        password=os.environ.get("DB_PASS", "alpha_pass"),
    )
    stats = {}
    for tbl in ["ohlcv_daily", "instruments", "markets", "predictions", "trade_history", "event_logs", "error_logs"]:
        try:
            stats[tbl] = await conn.fetchval(f"SELECT count(*) FROM {tbl}")
            print(f"  {tbl}: {stats[tbl]:,}")
        except Exception:
            stats[tbl] = 0
    stats["distinct_tickers"] = await conn.fetchval("SELECT count(DISTINCT instrument_id) FROM ohlcv_daily")
    print(f"  distinct tickers: {stats['distinct_tickers']:,}")
    await conn.close()
    return stats


async def main() -> None:
    section("1/5 DB Query Performance")
    try:
        report["benchmarks"]["query"] = await query_bench()
    except Exception as e:
        report["benchmarks"]["query"] = {"error": str(e)}
        print(f"  ERROR: {e}")

    section("2/5 DB INSERT Speed")
    try:
        report["benchmarks"]["insert"] = await insert_bench()
    except Exception as e:
        report["benchmarks"]["insert"] = {"error": str(e)}
        print(f"  ERROR: {e}")

    section("3/5 S3 Upload/Download Speed")
    try:
        report["benchmarks"]["s3"] = s3_bench()
    except Exception as e:
        report["benchmarks"]["s3"] = {"error": str(e)}
        print(f"  ERROR: {e}")

    section("4/5 Partition Statistics")
    try:
        report["benchmarks"]["partitions"] = await partition_stats()
    except Exception as e:
        report["benchmarks"]["partitions"] = {"error": str(e)}
        print(f"  ERROR: {e}")

    section("5/5 Data Statistics")
    try:
        report["benchmarks"]["data_stats"] = await data_stats()
    except Exception as e:
        report["benchmarks"]["data_stats"] = {"error": str(e)}
        print(f"  ERROR: {e}")

    # 요약
    section("Summary")
    q = report["benchmarks"].get("query", {})
    ins = report["benchmarks"].get("insert", {})
    s3r = report["benchmarks"].get("s3", {})
    ds = report["benchmarks"].get("data_stats", {})

    report["summary"] = {
        "total_rows": q.get("total_rows", 0),
        "distinct_tickers": ds.get("distinct_tickers", 0),
        "query_single_30d_ms": q.get("single_ticker_30d", {}).get("avg_ms", 0),
        "query_count_all_ms": q.get("count_all", {}).get("avg_ms", 0),
        "insert_executemany_50k_rps": ins.get("50000_rows", {}).get("executemany_rps", 0),
        "insert_copy_50k_rps": ins.get("50000_rows", {}).get("copy_rps", 0),
        "s3_upload_50mb_mbps": s3r.get("50000kb", {}).get("upload_mbps", 0),
        "s3_download_50mb_mbps": s3r.get("50000kb", {}).get("download_mbps", 0),
    }
    print(json.dumps(report["summary"], indent=2))

    # 저장
    out_path = os.environ.get("REPORT_PATH", "/tmp/benchmark_report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📊 Report saved: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
