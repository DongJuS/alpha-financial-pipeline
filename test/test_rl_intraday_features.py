"""test/test_rl_intraday_features.py — 일봉+분봉 join / 일중 특징 단위 테스트"""

import unittest
from datetime import date, datetime

from src.agents.rl_intraday_features import (
    INTRADAY_FEATURE_KEYS,
    INTRADAY_OBS_KEYS,
    NEUTRAL_INTRADAY,
    compute_day_intraday_features,
    intraday_obs_vector,
    join_daily_with_intraday,
)


def _mbar(h, m, o, hi, lo, c, v, vwap=None):
    return {
        "bucket_at": datetime(2026, 6, 1, h, m),
        "open": o, "high": hi, "low": lo, "close": c, "volume": v, "vwap": vwap,
    }


class ComputeDayFeaturesTest(unittest.TestCase):
    def test_empty_returns_neutral(self) -> None:
        self.assertEqual(compute_day_intraday_features([]), NEUTRAL_INTRADAY)

    def test_keys_and_float_types(self) -> None:
        bars = [_mbar(9, 0, 100, 105, 99, 102, 1000), _mbar(9, 1, 102, 108, 101, 107, 2000)]
        feats = compute_day_intraday_features(bars)
        self.assertEqual(set(feats.keys()), set(INTRADAY_FEATURE_KEYS))
        for v in feats.values():
            self.assertIsInstance(v, float)

    def test_intraday_range_and_return(self) -> None:
        # high=110, low=90, last_close=100, first_open=95
        bars = [_mbar(9, 0, 95, 100, 90, 96, 100), _mbar(9, 1, 96, 110, 95, 100, 100)]
        feats = compute_day_intraday_features(bars)
        self.assertAlmostEqual(feats["intraday_range_pct"], (110 - 90) / 100, places=6)
        self.assertAlmostEqual(feats["intraday_return"], (100 / 95) - 1.0, places=6)

    def test_volume_skew_morning_heavy(self) -> None:
        # 전반부 거래량 > 후반부 → 양수
        bars = [_mbar(9, 0, 100, 100, 100, 100, 9000), _mbar(9, 1, 100, 100, 100, 100, 1000)]
        feats = compute_day_intraday_features(bars)
        self.assertGreater(feats["volume_skew"], 0.0)

    def test_zero_volume_no_crash(self) -> None:
        bars = [_mbar(9, 0, 100, 100, 100, 100, 0), _mbar(9, 1, 100, 100, 100, 100, 0)]
        feats = compute_day_intraday_features(bars)  # vwap fallback, no ZeroDivision
        self.assertEqual(feats["volume_skew"], 0.0)
        self.assertIsInstance(feats["vwap_dev"], float)

    def test_unsorted_input_handled(self) -> None:
        a = _mbar(9, 0, 95, 100, 90, 96, 100)
        b = _mbar(9, 1, 96, 110, 95, 100, 100)
        feats_sorted = compute_day_intraday_features([a, b])
        feats_unsorted = compute_day_intraday_features([b, a])
        self.assertAlmostEqual(feats_sorted["intraday_return"], feats_unsorted["intraday_return"])


class JoinDailyIntradayTest(unittest.TestCase):
    def _daily(self, d: date, close: float) -> dict:
        return {"instrument_id": "005930.KS", "traded_at": d, "close": close, "volume": 1000}

    def test_day_with_minute_gets_features_and_flag(self) -> None:
        daily = [self._daily(date(2026, 6, 1), 100.0)]
        minute = [
            {"bucket_at": datetime(2026, 6, 1, 9, 0), "open": 95, "high": 110, "low": 90, "close": 100, "volume": 500, "vwap": 99},
        ]
        out = join_daily_with_intraday(daily, minute)
        self.assertEqual(out[0]["has_intraday"], 1.0)
        self.assertIn("intraday_range_pct", out[0])
        self.assertGreater(out[0]["intraday_range_pct"], 0.0)

    def test_day_without_minute_neutral_and_masked(self) -> None:
        daily = [self._daily(date(2026, 5, 1), 80.0)]  # 분봉 없는 과거
        out = join_daily_with_intraday(daily, [])
        self.assertEqual(out[0]["has_intraday"], 0.0)
        for k in INTRADAY_FEATURE_KEYS:
            self.assertEqual(out[0][k], 0.0)
        # 가격 백본(종가)은 일봉 그대로 — 합성 없음
        self.assertEqual(out[0]["close"], 80.0)

    def test_mixed_coverage_preserves_order_and_backbone(self) -> None:
        daily = [
            self._daily(date(2026, 5, 1), 80.0),   # 분봉 없음
            self._daily(date(2026, 6, 1), 100.0),  # 분봉 있음
        ]
        minute = [
            {"bucket_at": datetime(2026, 6, 1, 9, 0), "open": 99, "high": 102, "low": 98, "close": 101, "volume": 300, "vwap": 100},
        ]
        out = join_daily_with_intraday(daily, minute)
        self.assertEqual([r["close"] for r in out], [80.0, 100.0])  # 순서·백본 보존
        self.assertEqual(out[0]["has_intraday"], 0.0)
        self.assertEqual(out[1]["has_intraday"], 1.0)

    def test_obs_vector_fixed_dim_and_order(self) -> None:
        daily = [self._daily(date(2026, 6, 1), 100.0)]
        minute = [
            {"bucket_at": datetime(2026, 6, 1, 9, 0), "open": 99, "high": 102, "low": 98, "close": 101, "volume": 300, "vwap": 100},
        ]
        out = join_daily_with_intraday(daily, minute)
        vec = intraday_obs_vector(out[0])
        self.assertEqual(len(vec), len(INTRADAY_OBS_KEYS))  # 고정 차원
        self.assertEqual(vec[-1], 1.0)  # 마지막 = has_intraday


if __name__ == "__main__":
    unittest.main()
