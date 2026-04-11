"""
test/test_ranking_calculator.py — RankingCalculator 스코어링 정확성 테스트

RankingCalculator의 각 랭킹 타입별 계산 로직과 정렬 정확성을 검증합니다.
DB 의존성은 mock으로 대체합니다.
"""
from __future__ import annotations

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.ranking_calculator import RankingCalculator
from src.db.models import DailyRanking


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_volume_rows(count: int = 5):
    """거래량 랭킹용 mock DB 결과."""
    rows = []
    for i in range(count):
        rows.append({
            "ticker": f"{i:06d}",
            "name": f"종목{i}",
            "total_volume": 1_000_000 * (count - i),
            "change_pct": (count - i) * 0.5,
        })
    return rows


def _mock_market_cap_rows(count: int = 5):
    """시가총액 랭킹용 mock DB 결과."""
    rows = []
    for i in range(count):
        rows.append({
            "ticker": f"{i:06d}",
            "name": f"종목{i}",
            "market_cap": 1_000_000_000_000 * (count - i),
            "change_pct": (count - i) * 0.3,
        })
    return rows


def _mock_turnover_rows(count: int = 5):
    """거래대금 랭킹용 mock DB 결과."""
    rows = []
    for i in range(count):
        rows.append({
            "ticker": f"{i:06d}",
            "name": f"종목{i}",
            "total_turnover": 500_000_000 * (count - i),
            "change_pct": (count - i) * 0.2,
        })
    return rows


def _mock_gainer_rows(count: int = 5):
    """상승률 랭킹용 mock DB 결과."""
    rows = []
    for i in range(count):
        rows.append({
            "ticker": f"{i:06d}",
            "name": f"종목{i}",
            "change_pct": 30.0 - i * 5,
        })
    return rows


def _mock_loser_rows(count: int = 5):
    """하락률 랭킹용 mock DB 결과."""
    rows = []
    for i in range(count):
        rows.append({
            "ticker": f"{i:06d}",
            "name": f"종목{i}",
            "change_pct": -30.0 + i * 5,
        })
    return rows


# ── Market Cap Ranking Tests ─────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestMarketCapRanking:
    """시가총액 랭킹 테스트."""

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_calculate_market_cap_ranking(self, mock_fetch):
        mock_fetch.return_value = _mock_market_cap_rows(5)
        calc = RankingCalculator()
        rankings = await calc.calculate_market_cap_ranking(date(2026, 4, 11))

        assert len(rankings) == 5
        assert all(isinstance(r, DailyRanking) for r in rankings)
        assert all(r.ranking_type == "market_cap" for r in rankings)

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_market_cap_rank_order(self, mock_fetch):
        mock_fetch.return_value = _mock_market_cap_rows(5)
        calc = RankingCalculator()
        rankings = await calc.calculate_market_cap_ranking(date(2026, 4, 11))

        # rank가 1부터 순서대로
        for i, r in enumerate(rankings):
            assert r.rank == i + 1

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_market_cap_value_populated(self, mock_fetch):
        mock_fetch.return_value = _mock_market_cap_rows(3)
        calc = RankingCalculator()
        rankings = await calc.calculate_market_cap_ranking(date(2026, 4, 11))

        # 첫 번째가 가장 큰 시가총액
        assert rankings[0].value > rankings[1].value

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_market_cap_empty_result(self, mock_fetch):
        mock_fetch.return_value = []
        calc = RankingCalculator()
        rankings = await calc.calculate_market_cap_ranking(date(2026, 4, 11))
        assert rankings == []

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_market_cap_custom_limit(self, mock_fetch):
        mock_fetch.return_value = _mock_market_cap_rows(10)
        calc = RankingCalculator()
        rankings = await calc.calculate_market_cap_ranking(date(2026, 4, 11), limit=10)
        assert len(rankings) == 10


# ── Volume Ranking Tests ─────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestVolumeRanking:
    """거래량 랭킹 테스트."""

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_calculate_volume_ranking(self, mock_fetch):
        mock_fetch.return_value = _mock_volume_rows(5)
        calc = RankingCalculator()
        rankings = await calc.calculate_volume_ranking(date(2026, 4, 11))

        assert len(rankings) == 5
        assert all(r.ranking_type == "volume" for r in rankings)

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_volume_value_decreasing(self, mock_fetch):
        mock_fetch.return_value = _mock_volume_rows(5)
        calc = RankingCalculator()
        rankings = await calc.calculate_volume_ranking(date(2026, 4, 11))

        values = [r.value for r in rankings]
        # DB에서 이미 정렬되어 있으므로 values가 내림차순
        for i in range(len(values) - 1):
            assert values[i] >= values[i + 1]


# ── Turnover Ranking Tests ───────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestTurnoverRanking:
    """거래대금 랭킹 테스트."""

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_calculate_turnover_ranking(self, mock_fetch):
        mock_fetch.return_value = _mock_turnover_rows(5)
        calc = RankingCalculator()
        rankings = await calc.calculate_turnover_ranking(date(2026, 4, 11))

        assert len(rankings) == 5
        assert all(r.ranking_type == "turnover" for r in rankings)


# ── Gainer Ranking Tests ────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestGainerRanking:
    """상승률 랭킹 테스트."""

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_calculate_gainer_ranking(self, mock_fetch):
        mock_fetch.return_value = _mock_gainer_rows(5)
        calc = RankingCalculator()
        rankings = await calc.calculate_gainer_ranking(date(2026, 4, 11))

        assert len(rankings) == 5
        assert all(r.ranking_type == "gainer" for r in rankings)

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_gainer_change_pct_populated(self, mock_fetch):
        mock_fetch.return_value = _mock_gainer_rows(3)
        calc = RankingCalculator()
        rankings = await calc.calculate_gainer_ranking(date(2026, 4, 11))

        assert all(r.change_pct is not None for r in rankings)
        assert all(r.change_pct > 0 for r in rankings)

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_gainer_descending_order(self, mock_fetch):
        mock_fetch.return_value = _mock_gainer_rows(5)
        calc = RankingCalculator()
        rankings = await calc.calculate_gainer_ranking(date(2026, 4, 11))

        pcts = [r.change_pct for r in rankings]
        for i in range(len(pcts) - 1):
            assert pcts[i] >= pcts[i + 1]


# ── Loser Ranking Tests ─────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestLoserRanking:
    """하락률 랭킹 테스트."""

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_calculate_loser_ranking(self, mock_fetch):
        mock_fetch.return_value = _mock_loser_rows(5)
        calc = RankingCalculator()
        rankings = await calc.calculate_loser_ranking(date(2026, 4, 11))

        assert len(rankings) == 5
        assert all(r.ranking_type == "loser" for r in rankings)

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_loser_change_pct_negative(self, mock_fetch):
        mock_fetch.return_value = _mock_loser_rows(5)
        calc = RankingCalculator()
        rankings = await calc.calculate_loser_ranking(date(2026, 4, 11))

        assert all(r.change_pct < 0 for r in rankings)

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_loser_ascending_order(self, mock_fetch):
        mock_fetch.return_value = _mock_loser_rows(5)
        calc = RankingCalculator()
        rankings = await calc.calculate_loser_ranking(date(2026, 4, 11))

        pcts = [r.change_pct for r in rankings]
        for i in range(len(pcts) - 1):
            assert pcts[i] <= pcts[i + 1]


# ── Calculate All Rankings Tests ─────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestCalculateAllRankings:
    """전체 랭킹 계산 테스트."""

    @patch("src.agents.ranking_calculator.get_redis", new_callable=AsyncMock)
    @patch("src.agents.ranking_calculator.set_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.ranking_calculator.insert_heartbeat", new_callable=AsyncMock)
    @patch("src.agents.ranking_calculator.upsert_daily_rankings", new_callable=AsyncMock, return_value=25)
    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_calculate_all_rankings(
        self, mock_fetch, mock_upsert, mock_insert_hb, mock_set_hb, mock_redis
    ):
        # 각 쿼리에 대해 결과 반환 설정
        mock_fetch.side_effect = [
            _mock_market_cap_rows(5),
            _mock_volume_rows(5),
            _mock_turnover_rows(5),
            _mock_gainer_rows(5),
            _mock_loser_rows(5),
        ]
        mock_redis_instance = AsyncMock()
        mock_redis.return_value = mock_redis_instance

        calc = RankingCalculator()
        saved = await calc.calculate_all_rankings(date(2026, 4, 11))

        assert saved == 25
        mock_upsert.assert_called_once()
        # 총 5개 타입 × 5개 = 25개 랭킹이 upsert에 전달
        rankings_arg = mock_upsert.call_args[0][0]
        assert len(rankings_arg) == 25

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock, return_value=[])
    async def test_calculate_all_rankings_empty(self, mock_fetch):
        calc = RankingCalculator()
        saved = await calc.calculate_all_rankings(date(2026, 4, 11))
        assert saved == 0


# ── DailyRanking Model Tests ────────────────────────────────────────────────


@pytest.mark.unit
class TestDailyRankingModel:
    """DailyRanking 모델 검증."""

    def test_ranking_model_creation(self):
        r = DailyRanking(
            ranking_date=date(2026, 4, 11),
            ranking_type="volume",
            rank=1,
            ticker="005930",
            name="삼성전자",
            value=10_000_000.0,
            change_pct=2.5,
        )
        assert r.rank == 1
        assert r.ranking_type == "volume"

    def test_ranking_model_optional_fields(self):
        r = DailyRanking(
            ranking_date=date(2026, 4, 11),
            ranking_type="gainer",
            rank=1,
            ticker="005930",
            name="삼성전자",
        )
        assert r.value is None
        assert r.change_pct is None
        assert r.extra is None


# ── Edge Cases ───────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestRankingEdgeCases:
    """랭킹 계산 에지 케이스."""

    def test_calculator_agent_id(self):
        calc = RankingCalculator()
        assert calc.agent_id == "ranking_calculator"

    def test_custom_agent_id(self):
        calc = RankingCalculator(agent_id="custom_ranking")
        assert calc.agent_id == "custom_ranking"

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_null_change_pct_handled(self, mock_fetch):
        """change_pct가 None/0인 경우 안전하게 처리."""
        mock_fetch.return_value = [{
            "ticker": "005930",
            "name": "삼성전자",
            "market_cap": 1_000_000_000_000,
            "change_pct": None,
        }]
        calc = RankingCalculator()
        rankings = await calc.calculate_market_cap_ranking(date(2026, 4, 11))
        assert len(rankings) == 1
        # change_pct가 None이면 None으로 유지
        # (코드에서 `if row["change_pct"]` → None → False → None)
        assert rankings[0].change_pct is None

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_null_value_handled(self, mock_fetch):
        mock_fetch.return_value = [{
            "ticker": "005930",
            "name": "삼성전자",
            "total_volume": None,
            "change_pct": 1.5,
        }]
        calc = RankingCalculator()
        rankings = await calc.calculate_volume_ranking(date(2026, 4, 11))
        assert len(rankings) == 1
        assert rankings[0].value is None

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_single_item_ranking(self, mock_fetch):
        """단일 종목 랭킹."""
        mock_fetch.return_value = [{
            "ticker": "005930",
            "name": "삼성전자",
            "total_volume": 10_000_000,
            "change_pct": 2.0,
        }]
        calc = RankingCalculator()
        rankings = await calc.calculate_volume_ranking(date(2026, 4, 11))
        assert len(rankings) == 1
        assert rankings[0].rank == 1


# ── Sector Heatmap Tests ──────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestSectorHeatmap:
    """calculate_sector_heatmap 테스트."""

    @patch("src.agents.ranking_calculator.get_redis", new_callable=AsyncMock)
    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_sector_heatmap_returns_data(self, mock_fetch, mock_redis):
        """섹터 히트맵이 올바른 구조로 반환되는지 검증."""
        mock_fetch.return_value = [
            {
                "sector": "반도체",
                "stock_count": 10,
                "avg_change_pct": 2.5,
                "total_market_cap": 500_000_000_000,
                "total_volume": 50_000_000,
            },
            {
                "sector": "바이오",
                "stock_count": 15,
                "avg_change_pct": -1.2,
                "total_market_cap": 200_000_000_000,
                "total_volume": 30_000_000,
            },
        ]
        mock_redis_instance = AsyncMock()
        mock_redis.return_value = mock_redis_instance

        calc = RankingCalculator()
        result = await calc.calculate_sector_heatmap(date(2026, 4, 11))

        assert "data" in result
        assert len(result["data"]) == 2
        assert result["data"][0]["sector"] == "반도체"
        assert result["data"][0]["stock_count"] == 10
        assert result["data"][0]["avg_change_pct"] == 2.5
        assert result["data"][0]["total_market_cap"] == 500_000_000_000
        assert result["data"][0]["total_volume"] == 50_000_000

    @patch("src.agents.ranking_calculator.get_redis", new_callable=AsyncMock)
    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_sector_heatmap_empty_result(self, mock_fetch, mock_redis):
        """섹터 데이터가 없으면 빈 리스트."""
        mock_fetch.return_value = []
        mock_redis_instance = AsyncMock()
        mock_redis.return_value = mock_redis_instance

        calc = RankingCalculator()
        result = await calc.calculate_sector_heatmap(date(2026, 4, 11))
        assert result["data"] == []

    @patch("src.agents.ranking_calculator.get_redis", new_callable=AsyncMock)
    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_sector_heatmap_cached_in_redis(self, mock_fetch, mock_redis):
        """히트맵 결과가 Redis에 캐시되는지 검증."""
        mock_fetch.return_value = [
            {
                "sector": "IT",
                "stock_count": 5,
                "avg_change_pct": 1.0,
                "total_market_cap": 100_000_000_000,
                "total_volume": 10_000_000,
            },
        ]
        mock_redis_instance = AsyncMock()
        mock_redis.return_value = mock_redis_instance

        calc = RankingCalculator()
        await calc.calculate_sector_heatmap(date(2026, 4, 11))

        mock_redis_instance.set.assert_awaited_once()
        call_args = mock_redis_instance.set.call_args
        assert "sector_heatmap" in call_args.args[0]

    @patch("src.agents.ranking_calculator.get_redis", new_callable=AsyncMock)
    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_sector_heatmap_default_date(self, mock_fetch, mock_redis):
        """ranking_date 미지정 시 오늘 날짜 사용."""
        mock_fetch.return_value = []
        mock_redis_instance = AsyncMock()
        mock_redis.return_value = mock_redis_instance

        calc = RankingCalculator()
        result = await calc.calculate_sector_heatmap()
        assert result["data"] == []
        mock_fetch.assert_awaited_once()


# ── Tie-Handling Tests ────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.strategy
class TestRankingTieHandling:
    """동점 시 순위 결정 로직 테스트.

    DB에서 ORDER BY 로 정렬된 결과가 오면 rank는 enumerate로 순차 부여.
    동일 값이면 DB 정렬 순서에 따라 rank가 결정됨.
    """

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_volume_ranking_tied_values(self, mock_fetch):
        """거래량이 동일한 종목들도 각각 고유 rank를 가짐."""
        mock_fetch.return_value = [
            {"ticker": "000001", "name": "종목A", "total_volume": 1_000_000, "change_pct": 1.0},
            {"ticker": "000002", "name": "종목B", "total_volume": 1_000_000, "change_pct": 2.0},
            {"ticker": "000003", "name": "종목C", "total_volume": 1_000_000, "change_pct": 3.0},
        ]
        calc = RankingCalculator()
        rankings = await calc.calculate_volume_ranking(date(2026, 4, 11))

        assert len(rankings) == 3
        ranks = [r.rank for r in rankings]
        assert ranks == [1, 2, 3]  # 순차적 rank 부여

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_gainer_ranking_tied_change_pct(self, mock_fetch):
        """change_pct가 동일한 종목들도 순차 rank."""
        mock_fetch.return_value = [
            {"ticker": "000001", "name": "종목A", "change_pct": 5.0},
            {"ticker": "000002", "name": "종목B", "change_pct": 5.0},
        ]
        calc = RankingCalculator()
        rankings = await calc.calculate_gainer_ranking(date(2026, 4, 11))

        assert len(rankings) == 2
        assert rankings[0].rank == 1
        assert rankings[1].rank == 2
        # 동일 change_pct 확인
        assert rankings[0].change_pct == rankings[1].change_pct

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_market_cap_ranking_tied_values(self, mock_fetch):
        """시가총액이 동일해도 순차 rank."""
        mock_fetch.return_value = [
            {"ticker": "000001", "name": "종목A", "market_cap": 1_000_000_000, "change_pct": 1.0},
            {"ticker": "000002", "name": "종목B", "market_cap": 1_000_000_000, "change_pct": -1.0},
        ]
        calc = RankingCalculator()
        rankings = await calc.calculate_market_cap_ranking(date(2026, 4, 11))

        assert len(rankings) == 2
        assert rankings[0].rank == 1
        assert rankings[1].rank == 2

    @patch("src.agents.ranking_calculator.fetch", new_callable=AsyncMock)
    async def test_loser_ranking_tied_negative_change(self, mock_fetch):
        """하락률이 동일해도 순차 rank."""
        mock_fetch.return_value = [
            {"ticker": "000001", "name": "종목A", "change_pct": -10.0},
            {"ticker": "000002", "name": "종목B", "change_pct": -10.0},
            {"ticker": "000003", "name": "종목C", "change_pct": -5.0},
        ]
        calc = RankingCalculator()
        rankings = await calc.calculate_loser_ranking(date(2026, 4, 11))

        assert len(rankings) == 3
        assert rankings[0].rank == 1
        assert rankings[1].rank == 2
        assert rankings[2].rank == 3
