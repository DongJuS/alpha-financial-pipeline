"""
scripts/run_yfinance_krafton_rl_v2.py — yfinance 기반 크래프톤 RL V2 학습/테스트

V1 대비 변경:
- TabularQTrainerV2 사용 (상태 공간 확장 + 기회비용 리워드)
- 기본 에피소드 300, lookback 20, 멀티시드(5회)
- 거래 비용 2bps, 기회비용 0.5

기본값:
- 종목: 259960.KS (KRAFTON, Inc.)
- 데이터: yfinance 10y, 1d
- 분할: 80% 학습 / 20% 테스트
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
import sys

from dotenv import load_dotenv
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.agents.rl_trading import RLDataset, RLPolicyStore
from src.agents.rl_trading_v2 import TabularQTrainerV2
from src.agents.rl_experiment import RLExperimentManager, load_profile
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2


def _download_history(ticker: str, period: str, interval: str) -> pd.DataFrame:
    data = yf.download(
        ticker,
        period=period,
        interval=interval,
        progress=False,
        auto_adjust=False,
        actions=False,
        threads=False,
    )
    if data.empty:
        raise ValueError(
            f"yfinance 데이터가 비어 있습니다: ticker={ticker}, period={period}, interval={interval}"
        )

    if isinstance(data.columns, pd.MultiIndex):
        try:
            data = data.xs(ticker, axis=1, level="Ticker")
        except Exception:
            data.columns = [col[0] for col in data.columns]

    return data.reset_index()


def _timestamp_label(value: pd.Timestamp, interval: str) -> str:
    ts = pd.Timestamp(value)
    if interval.endswith(("m", "h")):
        if ts.tzinfo is not None:
            return ts.tz_convert("Asia/Seoul").isoformat(timespec="minutes")
        return ts.isoformat(timespec="minutes")
    return ts.date().isoformat()


def _save_price_csv(path: Path, ticker: str, history: pd.DataFrame, interval: str) -> None:
    fieldnames = ["ticker", "timestamp", "open", "high", "low", "close", "adj_close", "volume"]
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in history.to_dict(orient="records"):
            writer.writerow(
                {
                    "ticker": ticker,
                    "timestamp": _timestamp_label(row["Date"], interval),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "adj_close": float(row["Adj Close"]),
                    "volume": int(row["Volume"]),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="yfinance 기반 크래프톤 RL V2 학습/테스트")
    parser.add_argument("--ticker", default="259960.KS", help="Yahoo Finance ticker")
    parser.add_argument("--period", default="10y", help="yfinance period")
    parser.add_argument("--interval", default="1d", help="yfinance interval")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="학습 데이터 비율 (기본 0.8)")
    parser.add_argument("--episodes", type=int, default=300, help="Q-learning episodes")
    parser.add_argument("--lookback", type=int, default=20, help="state lookback window")
    parser.add_argument("--learning-rate", type=float, default=0.10, help="learning rate")
    parser.add_argument("--discount-factor", type=float, default=0.95, help="discount factor")
    parser.add_argument("--epsilon", type=float, default=0.30, help="exploration epsilon")
    parser.add_argument("--trade-penalty-bps", type=int, default=2, help="trade penalty in bps")
    parser.add_argument("--opportunity-cost", type=float, default=0.5, help="opportunity cost factor")
    parser.add_argument("--num-seeds", type=int, default=5, help="multi-seed training runs")
    parser.add_argument("--profile", default="tabular_q_v2_baseline", help="RL profile ID")
    parser.add_argument("--no-experiment", action="store_true", help="실험 기록 생략")
    args = parser.parse_args()

    output_dir = ROOT / "artifacts" / "rl" / "yfinance"
    output_dir.mkdir(parents=True, exist_ok=True)

    history = _download_history(args.ticker, args.period, args.interval)
    price_csv_path = output_dir / f"{args.ticker}_{args.period}_{args.interval}_prices.csv"
    _save_price_csv(price_csv_path, args.ticker, history, args.interval)

    dataset = RLDataset(
        ticker=args.ticker,
        closes=[float(value) for value in history["Close"].tolist()],
        timestamps=[_timestamp_label(value, args.interval) for value in history["Date"].tolist()],
    )

    trainer = TabularQTrainerV2(
        episodes=args.episodes,
        lookback=args.lookback,
        learning_rate=args.learning_rate,
        discount_factor=args.discount_factor,
        epsilon=args.epsilon,
        trade_penalty_bps=args.trade_penalty_bps,
        opportunity_cost_factor=args.opportunity_cost,
        num_seeds=args.num_seeds,
    )

    # 실험 run 생성 (--no-experiment가 아닌 경우)
    exp_manager = None
    run_id = None
    profile = load_profile(args.profile)
    if not args.no_experiment:
        exp_manager = RLExperimentManager()
        run_id = exp_manager.create_run(
            dataset=dataset,
            profile=profile,
            data_source="yfinance",
            data_range=args.period,
            state_version="qlearn_v2",
            trainer_overrides={
                "episodes": args.episodes,
                "lookback": args.lookback,
                "learning_rate": args.learning_rate,
                "discount_factor": args.discount_factor,
                "epsilon": args.epsilon,
                "trade_penalty_bps": args.trade_penalty_bps,
                "opportunity_cost_factor": args.opportunity_cost,
                "num_seeds": args.num_seeds,
            },
        )

    artifact, split_metadata = trainer.train_with_metadata(dataset, train_ratio=args.train_ratio)

    # 실험 메타데이터 기록
    if exp_manager and run_id:
        exp_manager.record_split(run_id, split_metadata)
        exp_manager.record_metrics(run_id, artifact.evaluation)

    # V2 정책 저장소 사용 (registry.json 기반)
    store_v2 = RLPolicyStoreV2()
    artifact = store_v2.save_policy(artifact, run_id=run_id)
    if artifact.evaluation.approved:
        activated = store_v2.activate_policy(artifact)
        if activated and exp_manager and run_id:
            exp_manager.mark_promoted(run_id)

    # 실험 ↔ 정책 링크
    if exp_manager and run_id:
        exp_manager.link_artifact(run_id, artifact.policy_id, artifact.artifact_path)

    latest_action, latest_confidence, latest_state, latest_q_values = trainer.infer_action(
        artifact,
        dataset.closes,
        current_position=0,
    )

    result = {
        "version": "v2",
        "ticker": args.ticker,
        "source": {
            "api": "yfinance",
            "period": args.period,
            "interval": args.interval,
            "actual_history_start": dataset.timestamps[0],
            "actual_history_end": dataset.timestamps[-1],
        },
        "data_period": {
            "from": dataset.timestamps[0],
            "to": dataset.timestamps[-1],
            "rows": len(dataset.timestamps),
            "price_csv_path": str(price_csv_path),
        },
        "hyperparams": {
            "episodes": args.episodes,
            "lookback": args.lookback,
            "learning_rate": args.learning_rate,
            "discount_factor": args.discount_factor,
            "epsilon": args.epsilon,
            "trade_penalty_bps": args.trade_penalty_bps,
            "opportunity_cost_factor": args.opportunity_cost,
            "num_seeds": args.num_seeds,
        },
        "split": asdict(split_metadata),
        "evaluation": asdict(artifact.evaluation),
        "latest_inference": {
            "action": latest_action,
            "confidence": latest_confidence,
            "state": latest_state,
            "q_values": latest_q_values,
        },
        "policy": {
            "policy_id": artifact.policy_id,
            "artifact_path": artifact.artifact_path,
            "approved": artifact.evaluation.approved,
            "state_version": "qlearn_v2",
            "run_id": run_id,
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
