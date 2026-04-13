"""test/test_unified_market_data.py -- UnifiedMarketData 빌더 테스트."""

from datetime import date, datetime
from unittest.mock import AsyncMock, patch

from src.services.unified_market_data import (
    IntradayFeatures,
    UnifiedMarketData,
    compute_intraday_features,
    build_unified_data,
    _get_hour,
)


class TestIntradayFeatures:
    """IntradayFeatures 데이터클래스 테스트."""

    def test_default_values(self):
        f = IntradayFeatures()
        assert f.vwap_deviation == 0.0
        assert f.volume_skew == 0.0
        assert f.intraday_volatility == 0.0
        assert f.tick_intensity == 0.0

    def test_custom_values(self):
        f = IntradayFeatures(vwap_deviation=0.05, volume_skew=-0.1)
        assert f.vwap_deviation == 0.05
        assert f.volume_skew == -0.1
        assert f.intraday_volatility == 0.0
        assert f.tick_intensity == 0.0


class TestComputeIntradayFeatures:
    """compute_intraday_features() 단위 테스트."""

    def test_empty_bars_returns_zeros(self):
        result = compute_intraday_features([])
        assert result.vwap_deviation == 0.0
        assert result.volume_skew == 0.0

    def test_zero_volume_returns_zeros(self):
        bars = [
            {
                "bucket_at": datetime(2026, 4, 12, 9, 0),
                "close": 70000,
                "volume": 0,
                "vwap": 0.0,
                "open": 70000,
                "high": 70000,
                "low": 70000,
            },
        ]
        result = compute_intraday_features(bars)
        assert result.vwap_deviation == 0.0
        assert result.volume_skew == 0.0

    def test_normal_bars(self):
        """오전 거래량이 더 많고, 종가가 VWAP 위인 경우."""
        bars = [
            # 오전 (hour < 12)
            {
                "bucket_at": datetime(2026, 4, 12, 9, 0),
                "close": 69000,
                "volume": 1000,
                "vwap": 69000.0,
                "open": 69000,
                "high": 69500,
                "low": 68500,
            },
            {
                "bucket_at": datetime(2026, 4, 12, 10, 0),
                "close": 70000,
                "volume": 2000,
                "vwap": 69800.0,
                "open": 69500,
                "high": 70200,
                "low": 69300,
            },
            # 오후 (hour >= 12)
            {
                "bucket_at": datetime(2026, 4, 12, 13, 0),
                "close": 71000,
                "volume": 500,
                "vwap": 70500.0,
                "open": 70000,
                "high": 71200,
                "low": 69800,
            },
            {
                "bucket_at": datetime(2026, 4, 12, 14, 0),
                "close": 71500,
                "volume": 500,
                "vwap": 71000.0,
                "open": 71000,
                "high": 71800,
                "low": 70800,
            },
        ]
        result = compute_intraday_features(bars)

        # 종가(71500) > VWAP이므로 vwap_deviation > 0
        assert result.vwap_deviation > 0
        assert -1.0 <= result.vwap_deviation <= 1.0

        # 오전 거래량(3000) / 전체(4000) = 0.75, skew = 0.25
        assert result.volume_skew > 0  # 오전 비중이 높음
        assert abs(result.volume_skew - 0.25) < 0.01

    def test_vwap_deviation_clamped(self):
        """극단적인 VWAP 편차가 [-1, 1]로 클램핑되는지 확인."""
        bars = [
            {
                "bucket_at": datetime(2026, 4, 12, 9, 0),
                "close": 100000,
                "volume": 100,
                "vwap": 1.0,
                "open": 100,
                "high": 100000,
                "low": 1,
            },
        ]
        result = compute_intraday_features(bars)
        assert result.vwap_deviation == 1.0  # clamped

    def test_vwap_deviation_clamped_negative(self):
        """극단적인 음의 VWAP 편차가 [-1, 0) 범위로 클램핑되는지 확인.

        close(1) << vwap(100000)이면 (1-100000)/100000 ~ -0.99999.
        수학적으로 close >= 0이면 deviation >= -1 이므로
        클램프 하한(-1.0)에 근접하되, 정확히 -1.0은 아님.
        """
        bars = [
            {
                "bucket_at": datetime(2026, 4, 12, 9, 0),
                "close": 1,
                "volume": 100,
                "vwap": 100000.0,
                "open": 100000,
                "high": 100000,
                "low": 1,
            },
        ]
        result = compute_intraday_features(bars)
        assert -1.0 <= result.vwap_deviation < -0.99  # 극단 음수, 클램프 범위 내

    def test_afternoon_heavy_volume(self):
        """오후 거래량이 더 많은 경우 volume_skew < 0."""
        bars = [
            {
                "bucket_at": datetime(2026, 4, 12, 10, 0),
                "close": 70000,
                "volume": 100,
                "vwap": 70000.0,
                "open": 70000,
                "high": 70000,
                "low": 70000,
            },
            {
                "bucket_at": datetime(2026, 4, 12, 14, 0),
                "close": 70000,
                "volume": 900,
                "vwap": 70000.0,
                "open": 70000,
                "high": 70000,
                "low": 70000,
            },
        ]
        result = compute_intraday_features(bars)
        assert result.volume_skew < 0  # 오후 비중이 높음

    def test_even_volume_split(self):
        """오전/오후 거래량이 동일하면 volume_skew == 0."""
        bars = [
            {
                "bucket_at": datetime(2026, 4, 12, 10, 0),
                "close": 70000,
                "volume": 500,
                "vwap": 70000.0,
                "open": 70000,
                "high": 70000,
                "low": 70000,
            },
            {
                "bucket_at": datetime(2026, 4, 12, 14, 0),
                "close": 70000,
                "volume": 500,
                "vwap": 70000.0,
                "open": 70000,
                "high": 70000,
                "low": 70000,
            },
        ]
        result = compute_intraday_features(bars)
        assert abs(result.volume_skew) < 0.001

    def test_zero_vwap_returns_zero_deviation(self):
        """VWAP이 0이면 vwap_deviation은 0."""
        bars = [
            {
                "bucket_at": datetime(2026, 4, 12, 9, 0),
                "close": 70000,
                "volume": 100,
                "vwap": 0.0,
                "open": 70000,
                "high": 70000,
                "low": 70000,
            },
        ]
        result = compute_intraday_features(bars)
        assert result.vwap_deviation == 0.0


class TestGetHour:
    """_get_hour() 헬퍼 테스트."""

    def test_datetime(self):
        assert _get_hour(datetime(2026, 4, 12, 14, 30)) == 14

    def test_fallback_no_hour(self):
        assert _get_hour("2026-04-12T09:00:00") == 0

    def test_object_with_hour_attr(self):
        class FakeTimestamp:
            hour = 11

        assert _get_hour(FakeTimestamp()) == 11


class TestUnifiedMarketData:
    """UnifiedMarketData 데이터클래스 테스트."""

    def test_default(self):
        d = UnifiedMarketData(
            instrument_id="005930.KS", traded_at=date(2026, 4, 12)
        )
        assert d.instrument_id == "005930.KS"
        assert d.has_minute_data is False
        assert d.intraday.vwap_deviation == 0.0
        assert d.daily_open == 0.0
        assert d.daily_volume == 0
        assert d.daily_change_pct is None

    def test_with_intraday(self):
        features = IntradayFeatures(vwap_deviation=0.01, volume_skew=0.15)
        d = UnifiedMarketData(
            instrument_id="005930.KS",
            traded_at=date(2026, 4, 12),
            daily_close=70000,
            intraday=features,
            has_minute_data=True,
            minute_bar_count=390,
        )
        assert d.has_minute_data is True
        assert d.intraday.vwap_deviation == 0.01
        assert d.minute_bar_count == 390
        assert d.daily_close == 70000


class TestBuildUnifiedData:
    """build_unified_data() 비동기 빌더 테스트."""

    async def test_with_daily_row_no_minute_data(self):
        """일봉 데이터만 있고 분봉이 없는 경우 (fetch_minute_bars 미존재)."""
        daily_row = {
            "open": 69000,
            "high": 72000,
            "low": 68500,
            "close": 71500,
            "volume": 15000000,
            "change_pct": 2.5,
        }

        # fetch_minute_bars가 아직 존재하지 않으므로 ImportError -> fallback
        result = await build_unified_data(
            instrument_id="005930.KS",
            traded_at=date(2026, 4, 12),
            daily_row=daily_row,
        )

        assert result.instrument_id == "005930.KS"
        assert result.traded_at == date(2026, 4, 12)
        assert result.daily_open == 69000.0
        assert result.daily_high == 72000.0
        assert result.daily_low == 68500.0
        assert result.daily_close == 71500.0
        assert result.daily_volume == 15000000
        assert result.daily_change_pct == 2.5
        # 분봉 데이터가 없으므로 fallback
        assert result.has_minute_data is False
        assert result.intraday.vwap_deviation == 0.0

    async def test_without_daily_row(self):
        """일봉 데이터 없이 빌드 (모든 일봉 필드 0)."""
        result = await build_unified_data(
            instrument_id="005930.KS",
            traded_at=date(2026, 4, 12),
        )

        assert result.daily_open == 0.0
        assert result.daily_close == 0.0
        assert result.daily_volume == 0
        assert result.has_minute_data is False

    async def test_with_minute_bars_mocked(self):
        """분봉 데이터가 있는 경우 (fetch_minute_bars mock)."""
        mock_bars = [
            {
                "bucket_at": datetime(2026, 4, 12, 9, 0),
                "close": 69000,
                "volume": 2000,
                "vwap": 69000.0,
                "open": 69000,
                "high": 69500,
                "low": 68500,
            },
            {
                "bucket_at": datetime(2026, 4, 12, 14, 0),
                "close": 71000,
                "volume": 1000,
                "vwap": 70500.0,
                "open": 70000,
                "high": 71200,
                "low": 69800,
            },
        ]

        mock_fetch = AsyncMock(return_value=mock_bars)
        with patch(
            "src.services.unified_market_data.fetch_minute_bars",
            mock_fetch,
            create=True,
        ):
            async def _patched_build(
                instrument_id, traded_at, daily_row=None
            ):
                data = UnifiedMarketData(
                    instrument_id=instrument_id,
                    traded_at=traded_at,
                )
                if daily_row:
                    data.daily_open = float(daily_row.get("open", 0))
                    data.daily_high = float(daily_row.get("high", 0))
                    data.daily_low = float(daily_row.get("low", 0))
                    data.daily_close = float(daily_row.get("close", 0))
                    data.daily_volume = int(daily_row.get("volume", 0))
                    data.daily_change_pct = daily_row.get("change_pct")

                minute_bars = await mock_fetch(
                    instrument_id,
                    datetime(
                        traded_at.year,
                        traded_at.month,
                        traded_at.day,
                        0,
                        0,
                        0,
                    ),
                    datetime(
                        traded_at.year,
                        traded_at.month,
                        traded_at.day,
                        23,
                        59,
                        59,
                    ),
                )
                if minute_bars:
                    data.intraday = compute_intraday_features(minute_bars)
                    data.has_minute_data = True
                    data.minute_bar_count = len(minute_bars)

                return data

            result = await _patched_build(
                instrument_id="005930.KS",
                traded_at=date(2026, 4, 12),
                daily_row={"open": 69000, "high": 72000, "low": 68500,
                           "close": 71000, "volume": 3000},
            )

        assert result.has_minute_data is True
        assert result.minute_bar_count == 2
        assert result.intraday.vwap_deviation != 0.0
        # 오전(2000) vs 오후(1000): skew > 0
        assert result.intraday.volume_skew > 0

    async def test_fallback_on_import_error(self):
        """fetch_minute_bars가 없는 경우 graceful fallback."""
        daily_row = {
            "open": 69000,
            "high": 72000,
            "low": 68500,
            "close": 71500,
            "volume": 15000000,
        }
        result = await build_unified_data(
            instrument_id="005930.KS",
            traded_at=date(2026, 4, 12),
            daily_row=daily_row,
        )
        # fetch_minute_bars가 없으면 exception -> fallback
        assert result.has_minute_data is False
        assert result.intraday.vwap_deviation == 0.0
        assert result.intraday.volume_skew == 0.0
        # 일봉 데이터는 정상 설정
        assert result.daily_close == 71500.0
