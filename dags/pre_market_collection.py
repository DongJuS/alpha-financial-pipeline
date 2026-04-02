"""
dags/pre_market_collection.py — 장 전 수집 파이프라인 DAG

Alpha의 unified_scheduler.py 장 전 잡(08:10~08:55)을 Airflow DAG로 이식.
동일한 src/ 코드를 subprocess로 호출하여 APScheduler vs Airflow를 1:1 비교한다.

subprocess 방식을 사용하는 이유:
- Alpha 코드가 전부 async이고, Airflow LocalExecutor의 fork 환경에서
  asyncio event loop 충돌이 발생함
- subprocess로 분리하면 독립 프로세스에서 asyncio가 정상 동작
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta

from airflow.decorators import dag, task


def _run_python(code: str) -> str:
    """Python 코드를 subprocess로 실행하고 stdout 마지막 줄(JSON)을 반환."""
    result = subprocess.run(
        ["python", "-c", code],
        capture_output=True,
        text=True,
        timeout=300,
        cwd="/opt/airflow",
        env={**__import__("os").environ, "PYTHONPATH": "/opt/airflow"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"Task failed (rc={result.returncode}):\n{result.stderr[-1000:]}")
    # stdout에 로그가 섞이므로 마지막 줄만 JSON으로 취급
    lines = result.stdout.strip().splitlines()
    return lines[-1] if lines else "{}"


@dag(
    dag_id="pre_market_collection",
    description="장 전 수집 파이프라인 — Alpha unified_scheduler 잡 이식",
    schedule="10 23 * * 0-4",  # UTC 23:10 = KST 08:10, 월~금
    start_date=datetime(2026, 3, 29),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "alpha",
        "retries": 3,
        "retry_delay": timedelta(seconds=10),
        "execution_timeout": timedelta(minutes=10),
    },
    tags=["collection", "pre-market", "alpha-spike"],
)
def pre_market_collection():

    @task()
    def collect_stock_master() -> dict:
        """종목 마스터 수집 — Alpha의 stock_master_daily 잡과 동일."""
        output = _run_python("""
import asyncio, json
from src.agents.stock_master_collector import StockMasterCollector
async def main():
    c = StockMasterCollector()
    r = await c.collect_stock_master(include_etf=True)
    print(json.dumps({"stock_master": r or 0}))
asyncio.run(main())
""")
        return json.loads(output)

    @task()
    def collect_macro() -> dict:
        """거시경제 지표 수집 — Alpha의 macro_daily 잡과 동일."""
        output = _run_python("""
import asyncio, json
from src.agents.macro_collector import MacroCollector
async def main():
    await MacroCollector().collect_all()
    print(json.dumps({"macro": "collected"}))
asyncio.run(main())
""")
        return json.loads(output)

    @task()
    def collect_index_warmup() -> dict:
        """지수 데이터 워밍업 — Alpha의 index_warmup 잡과 동일."""
        output = _run_python("""
import asyncio, json
from src.agents.index_collector import IndexCollector
async def main():
    await IndexCollector().collect_once()
    print(json.dumps({"index": "warmed_up"}))
asyncio.run(main())
""")
        return json.loads(output)

    @task()
    def collect_daily_bars() -> dict:
        """전종목 일봉 수집 — Alpha의 collector_daily 잡과 동일."""
        output = _run_python("""
import asyncio, json
from src.agents.collector import CollectorAgent
async def main():
    agent = CollectorAgent()
    tickers = await agent.resolve_tickers(requested=None, limit=20)
    count = 0
    for ticker, name, market in tickers:
        try:
            await agent.collect_daily_bars(ticker=ticker, name=name, market=market, days=5)
            count += 1
        except Exception as e:
            print(f"skip {ticker}: {e}", flush=True)
    print(json.dumps({"daily_bars_tickers": count}))
asyncio.run(main())
""")
        return json.loads(output)

    @task()
    def validate_collection(
        stock_master: dict, macro: dict, index: dict, daily_bars: dict,
    ) -> dict:
        """수집 결과 검증 — Alpha에는 없는 Airflow 부가가치."""
        results = {**stock_master, **macro, **index, **daily_bars}
        total = daily_bars.get("daily_bars_tickers", 0)
        # 주말/공휴일은 수집 데이터 없을 수 있음 — 경고만 출력
        if total == 0:
            print(f"WARNING: 수집 종목 0건 (주말/공휴일 가능): {results}")
        return {"validated": total > 0, "total_tickers": total, **results}

    @task()
    def log_completion(validation: dict) -> None:
        """수집 완료 로그."""
        print(f"=== 장 전 수집 완료: {validation} ===")

    master = collect_stock_master()
    macro = collect_macro()
    index = collect_index_warmup()
    bars = collect_daily_bars()
    validate = validate_collection(master, macro, index, bars)

    master >> macro >> index >> bars >> validate >> log_completion(validate)


pre_market_collection()
