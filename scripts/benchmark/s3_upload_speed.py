#!/usr/bin/env python3
"""
s3_upload_speed.py — S3(MinIO) Parquet 업로드 속도 벤치마크

다양한 크기의 Parquet 파일을 S3에 업로드하여 처리량(MB/초)을 측정합니다.

실행:
    python3 scripts/benchmark/s3_upload_speed.py
    python3 scripts/benchmark/s3_upload_speed.py --sizes 1,10,50,100

환경변수:
    S3_ENDPOINT_URL, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET_NAME
"""
from __future__ import annotations

import argparse
import io
import json
import os
import time
from pathlib import Path

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
import numpy as np


def create_parquet_buffer(target_mb: float) -> tuple[io.BytesIO, int]:
    """주어진 크기(MB)에 근접하는 Parquet 파일을 메모리에 생성합니다."""
    # 1행 ≈ 100 bytes in Parquet (압축 후)
    rows_estimate = int(target_mb * 1024 * 1024 / 100)
    rows = max(1000, rows_estimate)

    table = pa.table({
        "instrument_id": pa.array([f"{i:06d}.KS" for i in range(rows)]),
        "traded_at": pa.array([f"2026-01-{(i%28)+1:02d}" for i in range(rows)]),
        "open": pa.array(np.random.uniform(10000, 500000, rows), type=pa.float64()),
        "high": pa.array(np.random.uniform(10000, 500000, rows), type=pa.float64()),
        "low": pa.array(np.random.uniform(10000, 500000, rows), type=pa.float64()),
        "close": pa.array(np.random.uniform(10000, 500000, rows), type=pa.float64()),
        "volume": pa.array(np.random.randint(1000, 10000000, rows), type=pa.int64()),
        "change_pct": pa.array(np.random.uniform(-5, 5, rows), type=pa.float64()),
    })

    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    actual_size = buf.tell()
    buf.seek(0)
    return buf, actual_size


def benchmark_s3(sizes_mb: list[float]) -> dict:
    endpoint = os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000")
    access_key = os.environ.get("S3_ACCESS_KEY", os.environ.get("MINIO_ROOT_USER", "minioadmin"))
    secret_key = os.environ.get("S3_SECRET_KEY", os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin"))
    bucket = os.environ.get("S3_BUCKET_NAME", "alpha-lake")

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="ap-northeast-2",
    )

    results = []
    print(f"S3 endpoint: {endpoint}, bucket: {bucket}")

    for target_mb in sizes_mb:
        print(f"\n--- {target_mb}MB 테스트 ---")
        buf, actual_bytes = create_parquet_buffer(target_mb)
        actual_mb = actual_bytes / (1024 * 1024)
        key = f"benchmark/test_{target_mb}mb_{int(time.time())}.parquet"

        # 업로드
        buf.seek(0)
        start = time.monotonic()
        s3.upload_fileobj(buf, bucket, key)
        upload_time = time.monotonic() - start

        # 다운로드
        download_buf = io.BytesIO()
        start = time.monotonic()
        s3.download_fileobj(bucket, key, download_buf)
        download_time = time.monotonic() - start

        # 정리
        s3.delete_object(Bucket=bucket, Key=key)

        entry = {
            "target_mb": target_mb,
            "actual_mb": round(actual_mb, 2),
            "upload_seconds": round(upload_time, 3),
            "upload_mb_per_sec": round(actual_mb / upload_time, 2) if upload_time > 0 else 0,
            "download_seconds": round(download_time, 3),
            "download_mb_per_sec": round(actual_mb / download_time, 2) if download_time > 0 else 0,
        }
        results.append(entry)
        print(f"  실제 크기: {actual_mb:.2f}MB")
        print(f"  업로드: {upload_time:.3f}초 ({actual_mb/upload_time:.1f}MB/s)")
        print(f"  다운로드: {download_time:.3f}초 ({actual_mb/download_time:.1f}MB/s)")

    output = {
        "benchmark": "s3_upload_speed",
        "endpoint": endpoint,
        "bucket": bucket,
        "tests": results,
        "summary": {
            "avg_upload_mb_per_sec": round(sum(r["upload_mb_per_sec"] for r in results) / len(results), 2),
            "avg_download_mb_per_sec": round(sum(r["download_mb_per_sec"] for r in results) / len(results), 2),
        },
    }

    print("\n=== 결과 ===")
    print(json.dumps(output, ensure_ascii=False, indent=2))

    # 결과 저장
    result_dir = Path(__file__).parent / "results"
    result_dir.mkdir(exist_ok=True)
    with open(result_dir / "s3_upload_speed.json", "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return output


def main():
    parser = argparse.ArgumentParser(description="S3 Parquet 업로드 속도 벤치마크")
    parser.add_argument("--sizes", default="1,10,50", help="테스트 크기(MB) 쉼표 구분")
    args = parser.parse_args()
    sizes = [float(s.strip()) for s in args.sizes.split(",")]
    benchmark_s3(sizes)


if __name__ == "__main__":
    main()
