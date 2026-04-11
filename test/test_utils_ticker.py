"""
test/test_utils_ticker.py -- src/utils/ticker.py 종목코드 파싱/변환 단위 테스트
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = [pytest.mark.unit]


class TestIsCanonical:
    def test_canonical_kospi(self):
        from src.utils.ticker import is_canonical

        assert is_canonical("005930.KS") is True

    def test_canonical_kosdaq(self):
        from src.utils.ticker import is_canonical

        assert is_canonical("259960.KQ") is True

    def test_raw_code_not_canonical(self):
        from src.utils.ticker import is_canonical

        assert is_canonical("005930") is False

    def test_lowercase_suffix_not_canonical(self):
        from src.utils.ticker import is_canonical

        assert is_canonical("005930.ks") is False

    def test_three_letter_suffix_not_canonical(self):
        from src.utils.ticker import is_canonical

        assert is_canonical("AAPL.NYSE") is False


class TestToRaw:
    def test_strips_suffix(self):
        from src.utils.ticker import to_raw

        assert to_raw("005930.KS") == "005930"

    def test_no_suffix_unchanged(self):
        from src.utils.ticker import to_raw

        assert to_raw("005930") == "005930"

    def test_multiple_dots(self):
        from src.utils.ticker import to_raw

        assert to_raw("A.B.CD") == "A.B"


class TestSuffixOf:
    def test_returns_suffix(self):
        from src.utils.ticker import suffix_of

        assert suffix_of("005930.KS") == "KS"

    def test_returns_none_for_raw(self):
        from src.utils.ticker import suffix_of

        assert suffix_of("005930") is None


class TestMarketOf:
    def test_kospi(self):
        from src.utils.ticker import market_of

        assert market_of("005930.KS") == "KOSPI"

    def test_kosdaq(self):
        from src.utils.ticker import market_of

        assert market_of("259960.KQ") == "KOSDAQ"

    def test_unknown_suffix(self):
        from src.utils.ticker import market_of

        assert market_of("XXX.ZZ") is None

    def test_no_suffix(self):
        from src.utils.ticker import market_of

        assert market_of("005930") is None


class TestFromRaw:
    def test_kospi(self):
        from src.utils.ticker import from_raw

        assert from_raw("005930", "KOSPI") == "005930.KS"

    def test_kosdaq(self):
        from src.utils.ticker import from_raw

        assert from_raw("259960", "KOSDAQ") == "259960.KQ"

    def test_us_market(self):
        from src.utils.ticker import from_raw

        assert from_raw("AAPL", "NYSE") == "AAPL.US"

    def test_unknown_market_defaults_ks(self):
        from src.utils.ticker import from_raw

        result = from_raw("000000", "UNKNOWN_MARKET")
        assert result == "000000.KS"

    def test_case_insensitive_market(self):
        from src.utils.ticker import from_raw

        assert from_raw("005930", "kospi") == "005930.KS"


class TestNormalize:
    def setup_method(self):
        from src.utils.ticker import clear_cache

        clear_cache()

    def test_already_canonical(self):
        from src.utils.ticker import normalize

        assert normalize("005930.KS") == "005930.KS"

    def test_with_market_argument(self):
        from src.utils.ticker import normalize

        assert normalize("005930", market="KOSPI") == "005930.KS"

    def test_six_digit_defaults_to_kospi(self):
        from src.utils.ticker import normalize

        assert normalize("005930") == "005930.KS"

    def test_cache_hit(self):
        from src.utils.ticker import normalize

        # First call caches
        normalize("005930", market="KOSDAQ")
        # Second call hits cache
        assert normalize("005930") == "005930.KQ"

    def test_strips_whitespace(self):
        from src.utils.ticker import normalize

        assert normalize("  005930.KS  ") == "005930.KS"

    def test_non_six_digit_returns_as_is(self):
        from src.utils.ticker import normalize

        # Non-6-digit, non-canonical, no market → warning, return as-is
        result = normalize("AAPL")
        assert result == "AAPL"


class TestNormalizeList:
    def test_normalizes_list(self):
        from src.utils.ticker import clear_cache, normalize_list

        clear_cache()
        result = normalize_list(["005930", "000660.KS"], market="KOSPI")
        assert result == ["005930.KS", "000660.KS"]


class TestNormalizeWithDb:
    @pytest.mark.asyncio
    async def test_already_canonical_skips_db(self):
        from src.utils.ticker import clear_cache, normalize_with_db

        clear_cache()
        result = await normalize_with_db("005930.KS")
        assert result == "005930.KS"

    @pytest.mark.asyncio
    async def test_instruments_db_lookup(self):
        from src.utils.ticker import clear_cache, normalize_with_db

        clear_cache()
        mock_row = {"instrument_id": "005930.KS"}
        # fetchrow is lazy-imported inside normalize_with_db from src.utils.db_client
        with patch("src.utils.db_client.fetchrow", new_callable=AsyncMock, return_value=mock_row):
            result = await normalize_with_db("005930")

        assert result == "005930.KS"

    @pytest.mark.asyncio
    async def test_krx_stock_master_fallback(self):
        from src.utils.ticker import clear_cache, normalize_with_db

        clear_cache()
        # instruments returns None, krx_stock_master returns row
        with patch(
            "src.utils.db_client.fetchrow",
            new_callable=AsyncMock,
            side_effect=[None, {"ticker": "005930", "market": "KOSPI"}],
        ):
            result = await normalize_with_db("005930")

        assert result == "005930.KS"

    @pytest.mark.asyncio
    async def test_db_failure_falls_back_to_normalize(self):
        from src.utils.ticker import clear_cache, normalize_with_db

        clear_cache()
        with patch("src.utils.db_client.fetchrow", new_callable=AsyncMock, side_effect=Exception("DB down")):
            result = await normalize_with_db("005930")

        # falls back to normalize() which defaults to .KS for 6-digit
        assert result == "005930.KS"


class TestBuildCache:
    def test_build_and_use_cache(self):
        from src.utils.ticker import build_cache, clear_cache, normalize

        clear_cache()
        build_cache([("005930", "005930.KS"), ("259960", "259960.KQ")])

        assert normalize("005930") == "005930.KS"
        assert normalize("259960") == "259960.KQ"


class TestClearCache:
    def test_clear_removes_entries(self):
        from src.utils.ticker import _cache, build_cache, clear_cache

        build_cache([("005930", "005930.KS")])
        assert len(_cache) > 0
        clear_cache()
        assert len(_cache) == 0


class TestMatches:
    def test_same_canonical(self):
        from src.utils.ticker import matches

        assert matches("005930.KS", "005930.KS") is True

    def test_raw_vs_canonical(self):
        from src.utils.ticker import matches

        assert matches("005930", "005930.KS") is True

    def test_different_tickers(self):
        from src.utils.ticker import matches

        assert matches("005930", "000660") is False

    def test_different_suffix_same_raw(self):
        from src.utils.ticker import matches

        assert matches("005930.KS", "005930.KQ") is True


class TestFindInMap:
    def test_direct_match(self):
        from src.utils.ticker import clear_cache, find_in_map

        clear_cache()
        result = find_in_map("005930.KS", {"005930.KS": "policy_123"})
        assert result == "policy_123"

    def test_raw_to_canonical_match(self):
        from src.utils.ticker import clear_cache, find_in_map

        clear_cache()
        result = find_in_map("005930", {"005930.KS": "policy_123"})
        assert result == "policy_123"

    def test_canonical_to_raw_match(self):
        from src.utils.ticker import clear_cache, find_in_map

        clear_cache()
        result = find_in_map("005930.KS", {"005930": "policy_123"})
        assert result == "policy_123"

    def test_no_match_returns_none(self):
        from src.utils.ticker import clear_cache, find_in_map

        clear_cache()
        result = find_in_map("999999", {"005930.KS": "policy_123"})
        assert result is None

    def test_none_value_skipped(self):
        from src.utils.ticker import clear_cache, find_in_map

        clear_cache()
        result = find_in_map("005930", {"005930": None, "005930.KS": "found"})
        assert result == "found"


class TestMarketSuffixMaps:
    def test_all_markets_have_suffixes(self):
        from src.utils.ticker import MARKET_SUFFIX_MAP

        expected = {"KOSPI", "KOSDAQ", "KONEX", "NYSE", "NASDAQ", "AMEX", "COMMODITY", "CURRENCY", "RATE"}
        assert expected.issubset(set(MARKET_SUFFIX_MAP.keys()))

    def test_suffix_market_reverse_map(self):
        from src.utils.ticker import SUFFIX_MARKET_MAP

        assert SUFFIX_MARKET_MAP["KS"] == "KOSPI"
        assert SUFFIX_MARKET_MAP["KQ"] == "KOSDAQ"
        assert SUFFIX_MARKET_MAP["US"] == "NYSE"
