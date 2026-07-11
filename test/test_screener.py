"""test/test_screener.py — 스크리너 단위 테스트"""

import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from src.agents.screener import _score_ticker, screen_tickers


class ScoreTickerTest(unittest.TestCase):
    def _make_bars(self, today_vol: int, today_chg: float, past_vol: int = 1000, days: int = 20):
        bars = [{"volume": today_vol, "change_pct": today_chg}]
        bars.extend({"volume": past_vol, "change_pct": 0.5} for _ in range(days))
        return bars

    def test_volume_surge_passes(self) -> None:
        bars = self._make_bars(today_vol=3000, today_chg=1.0)
        passes, score = _score_ticker(bars, vol_threshold=2.0, pct_threshold=3.0)
        self.assertTrue(passes)  # 3000/1000 = 3.0 >= 2.0

    def test_change_pct_passes(self) -> None:
        bars = self._make_bars(today_vol=500, today_chg=-4.0)
        passes, score = _score_ticker(bars, vol_threshold=2.0, pct_threshold=3.0)
        self.assertTrue(passes)  # abs(-4.0) >= 3.0

    def test_neither_passes(self) -> None:
        bars = self._make_bars(today_vol=1200, today_chg=1.0)
        passes, score = _score_ticker(bars, vol_threshold=2.0, pct_threshold=3.0)
        self.assertFalse(passes)  # 1.2 < 2.0 and 1.0 < 3.0

    def test_both_pass_higher_score(self) -> None:
        bars_both = self._make_bars(today_vol=5000, today_chg=5.0)
        bars_one = self._make_bars(today_vol=2500, today_chg=1.0)
        _, score_both = _score_ticker(bars_both, 2.0, 3.0)
        _, score_one = _score_ticker(bars_one, 2.0, 3.0)
        self.assertGreater(score_both, score_one)

    def test_none_change_pct_treated_as_zero(self) -> None:
        bars = self._make_bars(today_vol=500, today_chg=0.0)
        bars[0]["change_pct"] = None
        passes, _ = _score_ticker(bars, 2.0, 3.0)
        self.assertFalse(passes)

    def test_decimal_inputs_no_typeerror(self) -> None:
        """asyncpg NUMERIC -> Decimal 입력이 와도 float 와 산술 시 크래시가 없어야 한다.

        실시간 틱 전환 후 change_pct(NUMERIC) 가 Decimal 로 들어와
        `Decimal / float` TypeError 로 매 사이클 크래시하던 회귀를 가드한다.
        """
        bars = [{"volume": Decimal("5000"), "change_pct": Decimal("4.0000")}]
        bars.extend({"volume": Decimal("1000"), "change_pct": Decimal("0.5000")} for _ in range(20))
        passes, score = _score_ticker(bars, vol_threshold=2.0, pct_threshold=3.0)
        self.assertTrue(passes)  # abs(4.0) >= 3.0
        self.assertIsInstance(score, float)

    def test_decimal_negative_and_zero_change_pct(self) -> None:
        """음수 Decimal 은 abs 로, Decimal('0')/None 은 0.0 으로 안전 처리돼야 한다."""
        neg = self._make_bars(today_vol=500, today_chg=0.0)
        neg[0]["change_pct"] = Decimal("-4.0")
        passes_neg, _ = _score_ticker(neg, 2.0, 3.0)
        self.assertTrue(passes_neg)  # abs(-4.0) >= 3.0

        zero = self._make_bars(today_vol=500, today_chg=0.0)
        zero[0]["change_pct"] = Decimal("0")
        passes_zero, score_zero = _score_ticker(zero, 2.0, 3.0)
        self.assertFalse(passes_zero)
        self.assertIsInstance(score_zero, float)


class ScreenTickersTest(unittest.IsolatedAsyncioTestCase):
    def _bars_for(self, vol: int, chg: float, days: int = 21):
        bars = [{"volume": vol, "change_pct": chg, "instrument_id": "X", "ticker": "X", "name": "X", "traded_at": None, "open": 0, "high": 0, "low": 0, "close": 0, "adj_close": None}]
        for _ in range(days - 1):
            bars.append({**bars[0], "volume": 1000, "change_pct": 0.5})
        return bars

    @patch("src.agents.screener.fetch_recent_market_data")
    async def test_filters_and_caps(self, mock_fetch: AsyncMock) -> None:
        async def side_effect(ticker, **kw):
            mapping = {
                "A": self._bars_for(5000, 5.0),   # passes both
                "B": self._bars_for(3000, 1.0),    # passes vol only
                "C": self._bars_for(500, 0.5),     # fails both
                "D": self._bars_for(500, 4.0),     # passes chg only
            }
            return mapping[ticker]

        mock_fetch.side_effect = side_effect
        result = await screen_tickers(
            ["A", "B", "C", "D"],
            volume_surge_ratio=2.0,
            change_pct_threshold=3.0,
            max_results=2,
        )
        self.assertEqual(len(result), 2)
        self.assertIn("A", result)
        self.assertNotIn("C", result)

    @patch("src.agents.screener.fetch_recent_market_data")
    async def test_empty_on_quiet_day(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = self._bars_for(1000, 0.5)
        result = await screen_tickers(["A", "B"], max_results=10)
        self.assertEqual(result, [])

    @patch("src.agents.screener.fetch_recent_market_data")
    async def test_skips_insufficient_data(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = [{"volume": 1000, "change_pct": 5.0}]  # only 1 day
        result = await screen_tickers(["A"])
        self.assertEqual(result, [])

    @patch("src.agents.screener.fetch_recent_market_data")
    async def test_skips_on_fetch_error(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.side_effect = Exception("DB down")
        result = await screen_tickers(["A"])
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
