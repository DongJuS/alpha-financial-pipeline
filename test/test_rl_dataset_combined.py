"""test/test_rl_dataset_combined.py — RLDataset combined(일봉+분봉) 모드 단위 테스트"""

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from src.agents.rl_intraday_features import INTRADAY_OBS_KEYS
from src.agents.rl_trading import RLDataset, RLDatasetBuilder


def _daily_rows(n: int = 50) -> list[dict]:
    base = date(2026, 1, 1)
    return [
        {
            "instrument_id": "005930.KS",
            "traded_at": base + timedelta(days=i),
            "close": 100.0 + i,
            "volume": 1000,
        }
        for i in range(n)
    ]


def _combined_rows(n: int = 50, recent: int = 10) -> list[dict]:
    """fetch_daily_with_intraday 가 돌려주는 형태 (일중 컬럼 + has_intraday 포함)."""
    rows = _daily_rows(n)
    for j, r in enumerate(rows):
        for k in INTRADAY_OBS_KEYS:
            r[k] = 0.0
        if j >= n - recent:  # 최근 recent 일만 분봉 있음
            r["has_intraday"] = 1.0
            r["intraday_range_pct"] = 0.02
    return rows


class BuildDatasetCombinedTest(unittest.IsolatedAsyncioTestCase):
    @patch("src.agents.rl_trading.fetch_recent_market_data")
    async def test_daily_mode_backward_compatible(self, mock_fetch) -> None:
        mock_fetch.return_value = _daily_rows(50)
        ds = await RLDatasetBuilder(min_history_points=40).build_dataset(
            "005930.KS", days=120
        )
        self.assertIsInstance(ds, RLDataset)
        self.assertIsNone(ds.features)  # daily 모드는 features 없음 (하위 호환)
        self.assertIsNone(ds.feature_keys)
        self.assertEqual(len(ds.closes), 50)

    @patch("src.db.queries.fetch_daily_with_intraday")
    async def test_combined_mode_features_aligned(self, mock_join) -> None:
        mock_join.return_value = _combined_rows(50, recent=10)
        ds = await RLDatasetBuilder(min_history_points=40).build_dataset(
            "005930.KS", days=120, data_scope="combined"
        )
        self.assertIsNotNone(ds.features)
        # 1) closes 와 features 1:1 정렬
        self.assertEqual(len(ds.features), len(ds.closes))
        # 2) feature_keys 고정
        self.assertEqual(ds.feature_keys, INTRADAY_OBS_KEYS)
        # 3) 각 벡터 차원 고정
        self.assertTrue(all(len(f) == len(INTRADAY_OBS_KEYS) for f in ds.features))

    @patch("src.db.queries.fetch_daily_with_intraday")
    async def test_combined_has_intraday_mask_position(self, mock_join) -> None:
        mock_join.return_value = _combined_rows(50, recent=10)
        ds = await RLDatasetBuilder(min_history_points=40).build_dataset(
            "005930.KS", days=120, data_scope="combined"
        )
        has_idx = INTRADAY_OBS_KEYS.index("has_intraday")
        # 정렬 후 오래된 날(앞)=마스킹 0.0, 최근 날(뒤)=1.0
        self.assertEqual(ds.features[0][has_idx], 0.0)
        self.assertEqual(ds.features[-1][has_idx], 1.0)

    @patch("FinanceDataReader.DataReader", side_effect=Exception("no network in test"))
    @patch("src.db.queries.fetch_daily_with_intraday")
    async def test_combined_insufficient_raises(self, mock_join, _mock_fdr) -> None:
        mock_join.return_value = _combined_rows(5)  # 40 미만 → FDR 폴백(차단)→ 학습 이력 부족
        with self.assertRaises(ValueError):
            await RLDatasetBuilder(min_history_points=40).build_dataset(
                "005930.KS", days=120, data_scope="combined"
            )


if __name__ == "__main__":
    unittest.main()
