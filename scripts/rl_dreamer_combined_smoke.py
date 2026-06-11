"""
scripts/rl_dreamer_combined_smoke.py — 실데이터 일봉+분봉 join → DreamerV3 학습/평가 smoke

ohlcv_daily + ohlcv_minute 덤프(JSON)를 받아 combined 데이터셋(일중 특징 + 마스킹)을
구성하고, DreamerV3 월드모델을 학습한 뒤 홀드아웃 평가 지표를 출력한다.
RL 파이프라인 전체(Feature1~6)를 실데이터로 end-to-end 검증하는 용도.

덤프 형식: {"daily": [ohlcv_daily 행...], "minute": [ohlcv_minute 행...]}
사용:
  python scripts/rl_dreamer_combined_smoke.py --dump /tmp/005930_dump.json --iters 80
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.rl_dreamer import DreamerConfig, DreamerV3Trainer  # noqa: E402
from src.agents.rl_intraday_features import (  # noqa: E402
    INTRADAY_OBS_KEYS,
    intraday_obs_vector,
    join_daily_with_intraday,
)


def build_combined_dataset(dump: dict, *, ticker: str = "005930.KS"):
    daily = sorted(dump["daily"], key=lambda r: r["traded_at"])
    joined = join_daily_with_intraday(daily, dump.get("minute", []))
    valid = [r for r in joined if r.get("close")]
    return types.SimpleNamespace(
        ticker=ticker,
        closes=[float(r["close"]) for r in valid],
        timestamps=[str(r["traded_at"]) for r in valid],
        features=[intraday_obs_vector(r) for r in valid],
        feature_keys=INTRADAY_OBS_KEYS,
    )


def _report(tag: str, artifact) -> None:
    ev = artifact.evaluation
    print(f"[{tag}] policy_id={artifact.policy_id} obs=combined")
    print(
        f"  return={ev.total_return_pct:.2f}%  baseline={ev.baseline_return_pct:.2f}%  "
        f"excess={ev.excess_return_pct:.2f}%"
    )
    print(
        f"  drawdown={ev.max_drawdown_pct:.2f}%  trades={ev.trades}  "
        f"win_rate={ev.win_rate:.2f}  holdout={ev.holdout_steps}  approved={ev.approved}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True, help="{daily, minute} JSON 덤프 경로")
    ap.add_argument("--iters", type=int, default=80, help="월드모델/AC 업데이트 횟수")
    ap.add_argument("--ticker", default="005930.KS")
    args = ap.parse_args()

    with open(args.dump) as f:
        dump = json.load(f)

    ds = build_combined_dataset(dump, ticker=args.ticker)
    has = sum(1 for f in ds.features if f[-1] == 1.0)
    print(
        f"[data] ticker={ds.ticker} closes={len(ds.closes)} "
        f"feat_dim={len(ds.features[0])} has_intraday={has}/{len(ds.features)} "
        f"(분봉 매칭 거래일)"
    )

    cfg = DreamerConfig(
        deter_dim=48, stoch_dim=24, hidden_dim=96, horizon=6, seq_len=24,
        batch_size=16, train_iters=args.iters, collect_episodes=6, lookback=20, seed=42,
    )
    trainer = DreamerV3Trainer(cfg=cfg)
    artifact, split = trainer.train_with_metadata(ds, train_ratio=0.7)
    print(
        f"[split] train={split.train_size} test={split.test_size} "
        f"({split.train_start}~{split.train_end} / {split.test_start}~{split.test_end})"
    )
    _report("dreamer_v3 combined", artifact)
    print(f"  model_path={artifact.model_path}")

    if artifact.model_path and os.path.exists(artifact.model_path):
        os.remove(artifact.model_path)
        print("  (model checkpoint cleaned up)")


if __name__ == "__main__":
    main()
