"""
test/test_list_tickers_integration.py — list_tickers 통합 테스트

src/db/queries.py의 list_tickers()가 instruments + trading_universe 조인을 통해
올바른 결과를 반환하는지 검증합니다.

DB fetch를 mock하여 미리 정의된 행을 반환하도록 설정합니다.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Test data fixtures
# ---------------------------------------------------------------------------

PAPER_ROWS = [
    {
        "instrument_id": "005930.KS",
        "ticker": "005930",
        "name": "삼성전자",
        "market": "KOSPI",
        "priority": 10,
        "max_weight_pct": None,
    },
    {
        "instrument_id": "000660.KS",
        "ticker": "000660",
        "name": "SK하이닉스",
        "market": "KOSPI",
        "priority": 5,
        "max_weight_pct": 15.0,
    },
    {
        "instrument_id": "035420.KS",
        "ticker": "035420",
        "name": "NAVER",
        "market": "KOSPI",
        "priority": 5,
        "max_weight_pct": 10.0,
    },
]

REAL_ROWS = [
    {
        "instrument_id": "005930.KS",
        "ticker": "005930",
        "name": "삼성전자",
        "market": "KOSPI",
        "priority": 20,
        "max_weight_pct": 30.0,
    },
    {
        "instrument_id": "000660.KS",
        "ticker": "000660",
        "name": "SK하이닉스",
        "market": "KOSPI",
        "priority": 15,
        "max_weight_pct": 20.0,
    },
]


class _MockRecord(dict):
    """asyncpg.Record처럼 dict 변환이 가능한 mock 객체."""
    pass


def _to_records(rows: list[dict]) -> list[_MockRecord]:
    """dict 리스트를 MockRecord 리스트로 변환합니다."""
    return [_MockRecord(r) for r in rows]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestListTickersReturnsSeededData:
    """instruments + trading_universe에 데이터가 있을 때 list_tickers가 올바른 결과를 반환합니다."""

    async def test_list_tickers_returns_seeded_data(self):
        """paper 모드로 호출하면 시딩된 3종목이 priority 내림차순으로 반환됩니다."""
        mock_fetch = AsyncMock(return_value=_to_records(PAPER_ROWS))

        with patch("src.db.queries.fetch", mock_fetch):
            from src.db.queries import list_tickers

            result = await list_tickers(mode="paper")

        assert len(result) == 3

        # priority 내림차순 확인
        assert result[0]["instrument_id"] == "005930.KS"
        assert result[0]["priority"] == 10
        assert result[0]["ticker"] == "005930"
        assert result[0]["name"] == "삼성전자"

        # fetch가 paper scope로 호출됨
        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args
        assert call_args[0][1] == "paper"  # 두 번째 인자: mode


@pytest.mark.integration
class TestListTickersEmptyWithoutUniverse:
    """trading_universe가 비어있을 때 list_tickers가 빈 리스트를 반환합니다."""

    async def test_list_tickers_empty_without_universe(self):
        """trading_universe에 매핑이 없으면 빈 리스트를 반환해야 합니다."""
        mock_fetch = AsyncMock(return_value=[])

        with patch("src.db.queries.fetch", mock_fetch):
            from src.db.queries import list_tickers

            result = await list_tickers(mode="paper")

        assert result == []
        mock_fetch.assert_called_once()


@pytest.mark.integration
class TestListTickersFiltersByMode:
    """paper와 real 모드가 서로 다른 결과셋을 반환하는지 확인합니다."""

    async def test_list_tickers_filters_by_mode(self):
        """paper vs real 호출 시 각각 다른 결과를 반환해야 합니다."""

        async def _mode_aware_fetch(query, mode, limit):
            if mode == "paper":
                return _to_records(PAPER_ROWS)
            elif mode == "real":
                return _to_records(REAL_ROWS)
            return []

        mock_fetch = AsyncMock(side_effect=_mode_aware_fetch)

        with patch("src.db.queries.fetch", mock_fetch):
            from src.db.queries import list_tickers

            paper_result = await list_tickers(mode="paper")
            real_result = await list_tickers(mode="real")

        # paper: 3종목, real: 2종목
        assert len(paper_result) == 3
        assert len(real_result) == 2

        # real에는 NAVER가 없음
        real_tickers = {r["ticker"] for r in real_result}
        assert "035420" not in real_tickers

        # paper에는 NAVER가 있음
        paper_tickers = {r["ticker"] for r in paper_result}
        assert "035420" in paper_tickers

        # fetch가 2회 호출됨 (paper + real)
        assert mock_fetch.call_count == 2

        # 각 호출에서 올바른 mode가 전달됨
        calls = mock_fetch.call_args_list
        assert calls[0][0][1] == "paper"
        assert calls[1][0][1] == "real"

    async def test_list_tickers_respects_limit(self):
        """limit 파라미터가 fetch 쿼리에 전달되는지 확인합니다."""
        mock_fetch = AsyncMock(return_value=_to_records(PAPER_ROWS[:1]))

        with patch("src.db.queries.fetch", mock_fetch):
            from src.db.queries import list_tickers

            result = await list_tickers(mode="paper", limit=1)

        assert len(result) == 1
        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args
        # limit이 세 번째 인자로 전달됨
        assert call_args[0][2] == 1

    async def test_list_tickers_returns_dict_list(self):
        """반환값이 dict 리스트인지 확인합니다 (asyncpg.Record가 아님)."""
        mock_fetch = AsyncMock(return_value=_to_records(PAPER_ROWS))

        with patch("src.db.queries.fetch", mock_fetch):
            from src.db.queries import list_tickers

            result = await list_tickers(mode="paper")

        for item in result:
            assert isinstance(item, dict)
            assert "instrument_id" in item
            assert "ticker" in item
            assert "priority" in item
