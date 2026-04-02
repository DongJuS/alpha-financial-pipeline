"""전체 사이클 DAG — 수집 → 분석 → 적재 end-to-end"""
from __future__ import annotations
import json, subprocess
from datetime import datetime, timedelta
from airflow.decorators import dag, task

def _run(code: str) -> str:
    r = subprocess.run(["python", "-c", code], capture_output=True, text=True, timeout=300,
                       cwd="/opt/airflow", env={**__import__("os").environ, "PYTHONPATH": "/opt/airflow"})
    if r.returncode != 0:
        raise RuntimeError(f"Failed:\n{r.stderr[-500:]}")
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else "{}"

@dag(dag_id="full_cycle", schedule="*/15 * * * *", start_date=datetime(2026,3,29),
     catchup=False, max_active_runs=1, tags=["e2e","load-test"],
     default_args={"retries":3,"retry_delay":timedelta(seconds=10),"execution_timeout":timedelta(minutes=10)})
def full_cycle():
    @task()
    def collect() -> dict:
        return json.loads(_run("""
import asyncio, json
from src.agents.collector import CollectorAgent
async def main():
    agent = CollectorAgent()
    tickers = await agent.resolve_tickers(requested=None, limit=5)
    count = 0
    for ticker, name, market in tickers:
        try:
            await agent.collect_daily_bars(ticker=ticker, name=name, market=market, days=3)
            count += 1
        except: pass
    print(json.dumps({"collected": count}))
asyncio.run(main())
"""))

    @task()
    def analyze(collect_result: dict) -> dict:
        return json.loads(_run("""
import asyncio, json
from src.utils.db_client import fetchval, get_pool
async def main():
    await get_pool()
    total = await fetchval("SELECT COUNT(*) FROM ohlcv_daily")
    latest = await fetchval("SELECT MAX(traded_at)::text FROM ohlcv_daily")
    print(json.dumps({"total_rows": total, "latest": latest}))
asyncio.run(main())
"""))

    @task()
    def store_report(analysis: dict) -> None:
        print(f"=== Full Cycle Report: {analysis} ===")

    c = collect()
    a = analyze(c)
    store_report(a)

full_cycle()
