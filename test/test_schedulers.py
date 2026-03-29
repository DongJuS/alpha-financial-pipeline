"""
test/test_schedulers.py — 스케줄러 통합 유닛 테스트

외부 의존성(DB, Redis, APScheduler) 없이 순수 로직을 검증합니다.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


# ─── distributed_lock ────────────────────────────────────────────────────────


class TestDistributedLock:
    """DistributedLock 동작 검증."""

    @pytest.mark.asyncio
    async def test_acquire_success(self):
        """SET NX 성공 시 acquired=True."""
        from src.schedulers.distributed_lock import DistributedLock

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)

        async with DistributedLock(mock_redis, "test:lock", ttl=10) as lock:
            assert lock.acquired is True

        mock_redis.set.assert_awaited_once()
        mock_redis.eval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acquire_fail_no_raise(self):
        """SET NX 실패 시 acquired=False (raise_on_fail=False)."""
        from src.schedulers.distributed_lock import DistributedLock

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)  # NX 실패

        async with DistributedLock(mock_redis, "test:lock", ttl=10) as lock:
            assert lock.acquired is False

        mock_redis.eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_acquire_fail_raises(self):
        """raise_on_fail=True 시 LockAcquisitionError 발생."""
        from src.schedulers.distributed_lock import DistributedLock, LockAcquisitionError

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)

        with pytest.raises(LockAcquisitionError):
            async with DistributedLock(mock_redis, "test:lock", ttl=10, raise_on_fail=True):
                pass

    @pytest.mark.asyncio
    async def test_release_only_own_lock(self):
        """락 해제는 Lua 스크립트로 원자적으로 수행."""
        from src.schedulers.distributed_lock import DistributedLock

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)

        async with DistributedLock(mock_redis, "test:lock", ttl=10) as lock:
            token = lock._token
            assert token is not None

        # eval 호출 시 토큰이 인자로 전달됐는지 확인
        call_args = mock_redis.eval.call_args
        assert token in call_args.args or token in str(call_args)


# ─── job_wrapper ─────────────────────────────────────────────────────────────


class TestJobWrapper:
    """with_retry 재시도 로직 검증."""

    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        """첫 시도 성공 시 재시도 없음."""
        from src.schedulers.job_wrapper import with_retry

        call_count = 0

        async def _fn():
            nonlocal call_count
            call_count += 1

        with patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock):
            wrapped = with_retry(_fn, "test_job")
            await wrapped()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """실패 시 최대 max_retries까지 재시도."""
        from src.schedulers.job_wrapper import with_retry

        call_count = 0

        async def _failing():
            nonlocal call_count
            call_count += 1
            raise ValueError("intentional error")

        with patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock):
            with patch("asyncio.sleep", new_callable=AsyncMock):  # sleep 스킵
                wrapped = with_retry(_failing, "test_job", max_retries=3, base_delay=0)
                await wrapped()

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_success_after_retry(self):
        """재시도 후 성공하면 종료."""
        from src.schedulers.job_wrapper import with_retry

        attempts = []

        async def _flaky():
            attempts.append(1)
            if len(attempts) < 2:
                raise RuntimeError("transient error")

        with patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                wrapped = with_retry(_flaky, "test_job", max_retries=3, base_delay=0)
                await wrapped()

        assert len(attempts) == 2

    @pytest.mark.asyncio
    async def test_history_recorded_on_success(self):
        """성공 시 이력 기록 함수 호출."""
        from src.schedulers.job_wrapper import with_retry

        async def _fn():
            pass

        with patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock) as mock_rec:
            wrapped = with_retry(_fn, "test_job")
            await wrapped()

        mock_rec.assert_awaited_once()
        args = mock_rec.call_args.args
        assert args[0] == "test_job"
        assert args[1] == "success"

    @pytest.mark.asyncio
    async def test_history_recorded_on_final_failure(self):
        """최종 실패 시 이력에 failed 기록."""
        from src.schedulers.job_wrapper import with_retry

        async def _fn():
            raise Exception("boom")

        with patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock) as mock_rec:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                wrapped = with_retry(_fn, "test_job", max_retries=2, base_delay=0)
                await wrapped()

        mock_rec.assert_awaited_once()
        call = mock_rec.call_args
        assert call.args[1] == "failed"
        assert "boom" in call.kwargs.get("error", "")  # keyword arg


# ─── unified_scheduler ───────────────────────────────────────────────────────


class TestGetSchedulerStatus:
    """get_scheduler_status 반환값 검증."""

    def test_returns_not_running_when_none(self):
        """스케줄러 미시작 시 running=False 반환."""
        import src.schedulers.unified_scheduler as mod

        original = mod._scheduler
        mod._scheduler = None
        try:
            result = mod.get_scheduler_status()
            assert result["running"] is False
            assert result["jobs"] == []
        finally:
            mod._scheduler = original

    def test_returns_running_status(self):
        """스케줄러 실행 중 상태 반환."""
        import src.schedulers.unified_scheduler as mod

        mock_scheduler = MagicMock()
        mock_scheduler.running = True
        mock_job = MagicMock()
        mock_job.id = "test_job"
        mock_job.name = "Test Job"
        mock_job.next_run_time = None
        mock_job.trigger = MagicMock(__str__=lambda _: "interval[0:00:30]")
        mock_scheduler.get_jobs.return_value = [mock_job]

        original = mod._scheduler
        mod._scheduler = mock_scheduler
        try:
            result = mod.get_scheduler_status()
            assert result["running"] is True
            assert result["job_count"] == 1
            assert result["jobs"][0]["id"] == "test_job"
        finally:
            mod._scheduler = original
