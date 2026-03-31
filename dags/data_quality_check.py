"""데이터 품질 검증 DAG — ohlcv_daily 정합성 자동 체크"""
from __future__ import annotations
import json, subprocess
from datetime import datetime, timedelta
from airflow.decorators import dag, task

def _run(code: str) -> str:
    r = subprocess.run(["python", "-c", code], capture_output=True, text=True, timeout=120,
                       cwd="/opt/airflow", env={**__import__("os").environ, "PYTHONPATH": "/opt/airflow"})
    if r.returncode != 0:
        raise RuntimeError(f"Failed:\n{r.stderr[-500:]}")
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else "{}"

@dag(dag_id="data_quality_check", schedule="*/10 * * * *", start_date=datetime(2026,3,29),
     catchup=False, max_active_runs=1, tags=["quality","load-test"],
     default_args={"retries":2,"retry_delay":timedelta(seconds=5),"execution_timeout":timedelta(minutes=3)})
def data_quality_check():
    @task()
    def check_null_values() -> dict:
        return json.loads(_run("""
import asyncio, json
from src.utils.db_client import fetchval, get_pool
async def main():
    await get_pool()
    nulls = await fetchval("SELECT COUNT(*) FROM ohlcv_daily WHERE close IS NULL OR volume IS NULL")
    print(json.dumps({"null_count": nulls}))
asyncio.run(main())
"""))

    @task()
    def check_duplicates() -> dict:
        return json.loads(_run("""
import asyncio, json
from src.utils.db_client import fetchval, get_pool
async def main():
    await get_pool()
    dups = await fetchval("SELECT COUNT(*) FROM (SELECT instrument_id, traded_at FROM ohlcv_daily GROUP BY 1,2 HAVING COUNT(*)>1) x")
    print(json.dumps({"duplicate_count": dups}))
asyncio.run(main())
"""))

    @task()
    def check_freshness() -> dict:
        return json.loads(_run("""
import asyncio, json
from src.utils.db_client import fetchval, get_pool
async def main():
    await get_pool()
    latest = await fetchval("SELECT MAX(traded_at)::text FROM ohlcv_daily")
    total = await fetchval("SELECT COUNT(*) FROM ohlcv_daily")
    instruments = await fetchval("SELECT COUNT(*) FROM instruments")
    print(json.dumps({"latest_date": latest, "total_rows": total, "instruments": instruments}))
asyncio.run(main())
"""))

    @task()
    def validate(nulls: dict, dups: dict, fresh: dict) -> None:
        issues = []
        if nulls.get("null_count", 0) > 0:
            issues.append(f"NULL values: {nulls['null_count']}")
        if dups.get("duplicate_count", 0) > 0:
            issues.append(f"Duplicates: {dups['duplicate_count']}")
        if issues:
            print(f"QUALITY ISSUES: {issues}")
        else:
            print(f"QUALITY OK: {fresh}")

    n = check_null_values()
    d = check_duplicates()
    f = check_freshness()
    validate(n, d, f)

data_quality_check()
