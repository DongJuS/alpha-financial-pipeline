"""백필 파이프라인 DAG — 특정 종목 과거 데이터 수집"""
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

@dag(dag_id="backfill_pipeline", schedule="30 23 * * 0-4", start_date=datetime(2026,3,29),
     catchup=False, max_active_runs=1, tags=["backfill","load-test"],
     default_args={"retries":3,"retry_delay":timedelta(seconds=15),"execution_timeout":timedelta(minutes=10)})
def backfill_pipeline():
    @task()
    def backfill_top_tickers() -> dict:
        return json.loads(_run("""
import asyncio, json
from src.agents.collector import CollectorAgent
async def main():
    agent = CollectorAgent()
    tickers = await agent.resolve_tickers(requested=None, limit=10)
    count = 0
    for ticker, name, market in tickers:
        try:
            await agent.collect_daily_bars(ticker=ticker, name=name, market=market, days=30)
            count += 1
        except Exception as e:
            print(f"skip {ticker}: {e}", flush=True)
    print(json.dumps({"backfilled_tickers": count, "days": 30}))
asyncio.run(main())
"""))

    @task()
    def verify_backfill(result: dict) -> None:
        count = result.get("backfilled_tickers", 0)
        if count == 0:
            print("WARNING: 0 tickers backfilled")
        else:
            print(f"Backfill OK: {count} tickers, {result.get('days')} days each")

    r = backfill_top_tickers()
    verify_backfill(r)

backfill_pipeline()
