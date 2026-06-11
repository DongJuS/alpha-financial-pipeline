"""test/test_rl_dreamer_combined_smoke.py — 덤프→combined 데이터셋→DreamerV3 학습 smoke(합성)"""

import importlib.util
import os
import pathlib
import unittest

from src.agents.rl_dreamer import DreamerConfig, DreamerV3Trainer

# 스크립트 모듈 로드 (scripts/ 는 패키지가 아니므로 파일 경로로 import)
_SMOKE_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "rl_dreamer_combined_smoke.py"
_spec = importlib.util.spec_from_file_location("rl_dreamer_combined_smoke", _SMOKE_PATH)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


def _synthetic_dump(n: int = 60, recent_minute_days: int = 12) -> dict:
    from datetime import date as _date
    from datetime import timedelta

    base = _date(2026, 1, 1)
    daily = []
    for i in range(n):
        date = (base + timedelta(days=i)).isoformat()  # 유일·순차 날짜
        daily.append({
            "instrument_id": "005930.KS", "traded_at": date,
            "open": 100.0 + i, "high": 102.0 + i, "low": 99.0 + i,
            "close": 100.0 + i, "volume": 1000 + i, "change_pct": 0.5,
        })
    # 최근 recent_minute_days 거래일에만 분봉 존재
    minute = []
    for r in daily[-recent_minute_days:]:
        d = r["traded_at"]
        for m in range(5):
            minute.append({
                "bucket_at": f"{d}T0{1 + m}:00:00+00:00",
                "open": r["open"], "high": r["high"], "low": r["low"],
                "close": r["close"] + m, "volume": 500 + m, "vwap": r["close"],
            })
    return {"daily": daily, "minute": minute}


class CombinedSmokeTest(unittest.TestCase):
    def test_build_combined_dataset_shape_and_mask(self) -> None:
        dump = _synthetic_dump(60, recent_minute_days=12)
        ds = smoke.build_combined_dataset(dump)
        self.assertEqual(len(ds.closes), 60)
        self.assertEqual(len(ds.features), 60)
        self.assertEqual(len(ds.features[0]), 6)  # INTRADAY_OBS_KEYS
        # 최근 12 거래일만 has_intraday=1
        has = sum(1 for f in ds.features if f[-1] == 1.0)
        self.assertEqual(has, 12)

    def test_dreamer_train_on_combined_real_shape(self) -> None:
        dump = _synthetic_dump(60, recent_minute_days=12)
        ds = smoke.build_combined_dataset(dump)
        cfg = DreamerConfig(
            deter_dim=16, stoch_dim=8, hidden_dim=32, horizon=3, seq_len=16,
            batch_size=8, train_iters=5, collect_episodes=3, lookback=10, seed=11,
        )
        trainer = DreamerV3Trainer(cfg=cfg)
        artifact, split = trainer.train_with_metadata(ds, train_ratio=0.7)
        try:
            self.assertEqual(artifact.algorithm, "dreamer_v3")
            self.assertTrue(os.path.exists(artifact.model_path))
            self.assertEqual(split.train_size + split.test_size, 60)
        finally:
            if artifact.model_path and os.path.exists(artifact.model_path):
                os.remove(artifact.model_path)


if __name__ == "__main__":
    unittest.main()
