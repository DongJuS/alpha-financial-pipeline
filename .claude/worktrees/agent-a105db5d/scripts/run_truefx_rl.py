"""
scripts/run_truefx_rl.py - TrueFX CSV 기반 RL 학습/테스트 실행기

기본값:
- 입력: artifacts/rl/data/EURUSD-*.csv
- 전처리: bid/ask -> 1초 단위 mid-price close
- 분할: 80% 학습 / 20% 테스트
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from dotenv import load_dotenv
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.agents.rl_trading import RLDataset, RLPolicyStore, TabularQTrainer


def _load_truefx_history(pattern: str, aggregate_seconds: int) -> tuple[pd.DataFrame, list[str], str, int]:
    paths = sorted(Path().glob(pattern))
    if not paths:
        raise ValueError(f"TrueFX 파일을 찾지 못했습니다: pattern={pattern}")

    frames: list[pd.DataFrame] = []
    for path in paths:
        frame = pd.read_csv(
            path,
            header=None,
            names=["symbol", "timestamp", "bid", "ask"],
            dtype={
                "symbol": "string",
                "timestamp": "string",
                "bid": "float64",
                "ask": "float64",
            },
        )
        if frame.empty:
            continue
        frame["timestamp"] = pd.to_datetime(
            frame["timestamp"],
            format="%Y%m%d %H:%M:%S.%f",
            utc=True,
        )
        frame["mid"] = (frame["bid"] + frame["ask"]) / 2.0
        frame["spread"] = frame["ask"] - frame["bid"]
        frames.append(frame)

    if not frames:
        raise ValueError(f"TrueFX 파일이 비어 있습니다: pattern={pattern}")

    history = pd.concat(frames, ignore_index=True).sort_values("timestamp", kind="stable")
    raw_rows = int(len(history))
    bucket = f"{aggregate_seconds}s"
    history["bucket"] = history["timestamp"].dt.floor(bucket)
    history = history.groupby("bucket", sort=True, as_index=False).last()
    history = history.drop(columns=["timestamp"]).rename(columns={"bucket": "timestamp", "mid": "close"})
    history["timestamp_label"] = history["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    symbol = str(history["symbol"].iloc[0]).replace("/", "")
    return history, [str(path) for path in paths], symbol, raw_rows


def _build_result_path(symbol: str) -> Path:
    output_dir = ROOT / "artifacts" / "rl" / "truefx"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{symbol}_latest_run.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="TrueFX CSV 기반 RL 학습/테스트")
    parser.add_argument(
        "--pattern",
        default="artifacts/rl/data/EURUSD-*.csv",
        help="입력 TrueFX CSV glob pattern",
    )
    parser.add_argument("--train-ratio", type=float, default=0.8, help="학습 데이터 비율")
    parser.add_argument("--aggregate-seconds", type=int, default=1, help="집계 초 단위")
    parser.add_argument("--episodes", type=int, default=8, help="Q-learning episodes")
    parser.add_argument("--lookback", type=int, default=6, help="state lookback window")
    parser.add_argument("--learning-rate", type=float, default=0.18, help="learning rate")
    parser.add_argument("--discount-factor", type=float, default=0.92, help="discount factor")
    parser.add_argument("--epsilon", type=float, default=0.15, help="exploration epsilon")
    parser.add_argument("--trade-penalty-bps", type=int, default=5, help="trade penalty in bps")
    args = parser.parse_args()

    history, source_files, symbol, raw_rows = _load_truefx_history(args.pattern, args.aggregate_seconds)

    dataset = RLDataset(
        ticker=f"{symbol}_TRUEFX",
        closes=[float(value) for value in history["close"].tolist()],
        timestamps=[str(value) for value in history["timestamp_label"].tolist()],
    )

    trainer = TabularQTrainer(
        episodes=args.episodes,
        lookback=args.lookback,
        learning_rate=args.learning_rate,
        discount_factor=args.discount_factor,
        epsilon=args.epsilon,
        trade_penalty_bps=args.trade_penalty_bps,
    )
    artifact, split_metadata = trainer.train_with_metadata(dataset, train_ratio=args.train_ratio)

    policy_store = RLPolicyStore()
    artifact = policy_store.save_policy(artifact)
    if artifact.evaluation.approved:
        policy_store.activate_policy(artifact)

    latest_action, latest_confidence, latest_state, latest_q_values = trainer.infer_action(
        artifact,
        dataset.closes,
        current_position=0,
    )

    result = {
        "ticker": dataset.ticker,
        "source": {
            "provider": "TrueFX",
            "files": source_files,
            "aggregate_seconds": args.aggregate_seconds,
        },
        "data_period": {
            "from": dataset.timestamps[0],
            "to": dataset.timestamps[-1],
            "rows": len(dataset.timestamps),
            "raw_rows": raw_rows,
        },
        "market_microstructure": {
            "mean_spread": round(float(history["spread"].mean()), 8),
            "median_spread": round(float(history["spread"].median()), 8),
            "min_spread": round(float(history["spread"].min()), 8),
            "max_spread": round(float(history["spread"].max()), 8),
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
        },
    }

    result_path = _build_result_path(symbol)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
