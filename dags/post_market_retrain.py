"""장 후 RL 재학습 DAG — Alpha의 rl_retrain(16:00) + blend_weight_adjust(16:30) 이식"""
from __future__ import annotations
import json, subprocess
from datetime import datetime, timedelta
from airflow.decorators import dag, task

def _run(code: str) -> str:
    r = subprocess.run(["python", "-c", code], capture_output=True, text=True, timeout=300,
                       cwd="/opt/airflow", env={**__import__("os").environ, "PYTHONPATH": "/opt/airflow"})
    if r.returncode != 0:
        raise RuntimeError(f"Failed (rc={r.returncode}):\n{r.stderr[-500:]}")
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else "{}"

@dag(dag_id="post_market_retrain", schedule="0 7 * * 1-5", start_date=datetime(2026,3,29),
     catchup=False, max_active_runs=1, tags=["post-market","rl","load-test"],
     default_args={"retries":3,"retry_delay":timedelta(seconds=10),"execution_timeout":timedelta(minutes=15)})
def post_market_retrain():
    @task()
    def retrain_rl() -> dict:
        return json.loads(_run("""
import asyncio, json
from src.agents.rl_continuous_improver import RLContinuousImprover
async def main():
    improver = RLContinuousImprover()
    outcomes = await improver.retrain_all()
    success = sum(1 for o in outcomes if o.success)
    print(json.dumps({"success": success, "total": len(outcomes)}))
asyncio.run(main())
"""))

    @task()
    def adjust_weights(retrain_result: dict) -> dict:
        return json.loads(_run("""
import asyncio, json
from src.utils.blend_weight_optimizer import BlendWeightOptimizer
async def main():
    optimizer = BlendWeightOptimizer(base_weights={"A":0.33,"B":0.33,"RL":0.34})
    weights = await optimizer.optimize()
    print(json.dumps({"weights": {k: round(v,4) for k,v in weights.items()}}))
asyncio.run(main())
"""))

    @task()
    def log_result(retrain: dict, weights: dict) -> None:
        print(f"=== Post-market complete: retrain={retrain}, weights={weights} ===")

    r = retrain_rl()
    w = adjust_weights(r)
    log_result(r, w)

post_market_retrain()
