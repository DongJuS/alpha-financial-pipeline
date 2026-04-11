"""
test/test_scheduler_cron.py -- 스케줄러 크론 표현식 / 장중-장외 판별 테스트
"""

from __future__ import annotations

from datetime import datetime, time
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

pytestmark = [pytest.mark.unit]

KST = ZoneInfo("Asia/Seoul")


# ── 크론 트리거 검증 ────────────────────────────────────────────────────────


class TestCronTriggerConfig:
    """unified_scheduler.py에 등록되는 크론 설정 검증."""

    def test_lock_ttl_keys_match_expected_jobs(self):
        from src.schedulers.unified_scheduler import _LOCK_TTL

        expected_keys = {
            "rl_bootstrap",
            "predictor_warmup",
            "stock_master_daily",
            "macro_daily",
            "collector_daily",
            "index_warmup",
            "index_collection",
            "s3_tick_flush",
            "rl_retrain",
            "blend_weight_adjust",
        }
        assert expected_keys == set(_LOCK_TTL.keys())

    def test_lock_ttl_values_are_positive(self):
        from src.schedulers.unified_scheduler import _LOCK_TTL

        for job_id, ttl in _LOCK_TTL.items():
            assert ttl > 0, f"{job_id} TTL should be positive, got {ttl}"

    def test_rl_jobs_have_longer_ttl(self):
        """RL 관련 잡은 학습 시간이 길어 TTL이 충분해야 함."""
        from src.schedulers.unified_scheduler import _LOCK_TTL

        assert _LOCK_TTL["rl_bootstrap"] >= 1800  # 30분 이상
        assert _LOCK_TTL["rl_retrain"] >= 1800

    def test_index_collection_ttl_shorter_than_interval(self):
        """index_collection은 30초 간격이므로 TTL이 그보다 짧아야 함."""
        from src.schedulers.unified_scheduler import _LOCK_TTL

        assert _LOCK_TTL["index_collection"] < 30


# ── 장중/장외 판별 ──────────────────────────────────────────────────────────


class TestMarketHoursJudgment:
    """is_market_open_now 및 market_session_status 상세 검증."""

    @pytest.mark.asyncio
    async def test_exactly_at_open(self):
        """09:00 정각은 장중."""
        now = datetime(2026, 4, 13, 9, 0, 0, tzinfo=KST)  # Monday
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import is_market_open_now
            assert await is_market_open_now() is True

    @pytest.mark.asyncio
    async def test_exactly_at_close(self):
        """15:30 정각은 장중 (<=)."""
        now = datetime(2026, 4, 13, 15, 30, 0, tzinfo=KST)  # Monday
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import is_market_open_now
            assert await is_market_open_now() is True

    @pytest.mark.asyncio
    async def test_one_second_after_close(self):
        """15:30:01은 장 마감."""
        now = datetime(2026, 4, 13, 15, 30, 1, tzinfo=KST)  # Monday
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import is_market_open_now
            assert await is_market_open_now() is False

    @pytest.mark.asyncio
    async def test_pre_market_830(self):
        """08:30은 프리마켓."""
        now = datetime(2026, 4, 13, 8, 30, 0, tzinfo=KST)
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import market_session_status
            assert await market_session_status() == "pre_market"

    @pytest.mark.asyncio
    async def test_pre_market_859(self):
        """08:59은 프리마켓."""
        now = datetime(2026, 4, 13, 8, 59, 0, tzinfo=KST)
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import market_session_status
            assert await market_session_status() == "pre_market"

    @pytest.mark.asyncio
    async def test_midnight_closed(self):
        """00:00은 장 마감."""
        now = datetime(2026, 4, 14, 0, 0, 0, tzinfo=KST)  # Tuesday
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import market_session_status
            assert await market_session_status() == "closed"

    @pytest.mark.asyncio
    async def test_sunday_always_closed(self):
        """일요일은 항상 장 마감."""
        now = datetime(2026, 4, 12, 10, 0, 0, tzinfo=KST)  # Sunday
        with patch("src.utils.market_hours.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from src.utils.market_hours import is_market_open_now
            assert await is_market_open_now() is False


# ── 스케줄러 상태 조회 ──────────────────────────────────────────────────────


class TestGetSchedulerStatusDetailed:
    def test_jobs_have_required_fields(self):
        """각 잡에 id, name, next_run, trigger 필드가 있는지 확인."""
        import src.schedulers.unified_scheduler as mod

        mock_scheduler = MagicMock()
        mock_scheduler.running = True

        mock_job = MagicMock()
        mock_job.id = "test_id"
        mock_job.name = "Test Name"
        mock_job.next_run_time = datetime(2026, 4, 13, 8, 0, tzinfo=KST)
        mock_job.trigger = MagicMock(__str__=lambda _: "cron[hour='8']")
        mock_scheduler.get_jobs.return_value = [mock_job]

        original = mod._scheduler
        mod._scheduler = mock_scheduler
        try:
            status = mod.get_scheduler_status()
            assert status["running"] is True
            job_info = status["jobs"][0]
            assert "id" in job_info
            assert "name" in job_info
            assert "next_run" in job_info
            assert "trigger" in job_info
            assert job_info["next_run"] is not None
        finally:
            mod._scheduler = original


# ── stop_unified_scheduler ──────────────────────────────────────────────────


class TestStopScheduler:
    @pytest.mark.asyncio
    async def test_stop_when_running(self):
        import src.schedulers.unified_scheduler as mod

        mock_scheduler = MagicMock()
        mock_scheduler.running = True
        mock_scheduler.shutdown = MagicMock()

        original = mod._scheduler
        mod._scheduler = mock_scheduler
        try:
            await mod.stop_unified_scheduler()
            mock_scheduler.shutdown.assert_called_once_with(wait=True)
            assert mod._scheduler is None
        finally:
            mod._scheduler = original

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        import src.schedulers.unified_scheduler as mod

        original = mod._scheduler
        mod._scheduler = None
        try:
            await mod.stop_unified_scheduler()  # should not raise
        finally:
            mod._scheduler = original
