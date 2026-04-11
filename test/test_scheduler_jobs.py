"""
test/test_scheduler_jobs.py -- 스케줄러 잡 래퍼/분산 락 추가 테스트

test_schedulers.py의 기존 테스트를 보강합니다.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


# ── with_retry 상세 테스트 ──────────────────────────────────────────────────


class TestWithRetryDetailed:
    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self):
        """재시도 지연이 exponential로 증가하는지 확인."""
        from src.schedulers.job_wrapper import with_retry

        call_count = 0
        sleep_delays = []

        async def _failing():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        async def _mock_sleep(delay):
            sleep_delays.append(delay)

        with (
            patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=_mock_sleep),
        ):
            wrapped = with_retry(_failing, "test_exp", max_retries=4, base_delay=1.0)
            await wrapped()

        assert call_count == 4
        # delays: 1.0, 2.0, 4.0 (3 retries after first attempt)
        assert len(sleep_delays) == 3
        assert sleep_delays[0] == 1.0
        assert sleep_delays[1] == 2.0
        assert sleep_delays[2] == 4.0

    @pytest.mark.asyncio
    async def test_custom_max_retries(self):
        from src.schedulers.job_wrapper import with_retry

        call_count = 0

        async def _failing():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        with (
            patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            wrapped = with_retry(_failing, "test_custom", max_retries=1, base_delay=0)
            await wrapped()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_history_duration_recorded(self):
        """실행 시간이 기록되는지 확인."""
        from src.schedulers.job_wrapper import with_retry

        async def _fn():
            pass

        with patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock) as mock_rec:
            wrapped = with_retry(_fn, "test_dur")
            await wrapped()

        args = mock_rec.call_args.args
        duration_ms = args[2]
        assert isinstance(duration_ms, float)
        assert duration_ms >= 0


# ── _record_history ─────────────────────────────────────────────────────────


class TestRecordHistory:
    @pytest.mark.asyncio
    async def test_records_success_to_redis(self):
        from src.schedulers.job_wrapper import _record_history

        mock_redis = AsyncMock()
        # pipeline() returns a sync-api pipeline where lpush/ltrim are sync, execute is async
        mock_pipe = MagicMock()
        mock_pipe.lpush = MagicMock()
        mock_pipe.ltrim = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[1, True])
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            await _record_history("test_job", "success", 123.4)

        mock_pipe.lpush.assert_called_once()
        args = mock_pipe.lpush.call_args.args
        entry = json.loads(args[1])
        assert entry["job_id"] == "test_job"
        assert entry["status"] == "success"
        assert entry["duration_ms"] == 123.4

    @pytest.mark.asyncio
    async def test_records_failure_with_error(self):
        from src.schedulers.job_wrapper import _record_history

        mock_redis = AsyncMock()
        mock_pipe = MagicMock()
        mock_pipe.lpush = MagicMock()
        mock_pipe.ltrim = MagicMock()
        mock_pipe.execute = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            await _record_history("test_job", "failed", 500.0, error="timeout")

        args = mock_pipe.lpush.call_args.args
        entry = json.loads(args[1])
        assert entry["status"] == "failed"
        assert entry["error"] == "timeout"

    @pytest.mark.asyncio
    async def test_redis_failure_silently_ignored(self):
        """Redis 접속 실패 시 예외를 던지지 않음."""
        from src.schedulers.job_wrapper import _record_history

        with patch(
            "src.utils.redis_client.get_redis",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Redis down"),
        ):
            # should not raise
            await _record_history("test_job", "success", 100.0)


# ── DistributedLock 추가 테스트 ─────────────────────────────────────────────


class TestDistributedLockDetailed:
    @pytest.mark.asyncio
    async def test_lock_uses_unique_token(self):
        """매 획득 시 UUID 토큰이 새로 생성되는지 확인."""
        from src.schedulers.distributed_lock import DistributedLock

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)

        tokens = []
        for _ in range(3):
            async with DistributedLock(mock_redis, "test:lock", ttl=10) as lock:
                tokens.append(lock._token)

        # all tokens should be unique
        assert len(set(tokens)) == 3

    @pytest.mark.asyncio
    async def test_lock_ttl_passed_to_redis(self):
        from src.schedulers.distributed_lock import DistributedLock

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)

        async with DistributedLock(mock_redis, "test:lock", ttl=42):
            pass

        call_kwargs = mock_redis.set.call_args
        assert call_kwargs.kwargs.get("ex") == 42

    @pytest.mark.asyncio
    async def test_lock_not_released_on_fail(self):
        """락 획득 실패 시 release(eval)를 호출하지 않음."""
        from src.schedulers.distributed_lock import DistributedLock

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)

        async with DistributedLock(mock_redis, "test:lock", ttl=10) as lock:
            assert lock.acquired is False

        mock_redis.eval.assert_not_called()


# ── _locked_job 래퍼 ────────────────────────────────────────────────────────


class TestLockedJob:
    @pytest.mark.asyncio
    async def test_locked_job_skips_when_lock_not_acquired(self):
        """분산 락 획득 실패 시 잡 함수가 실행되지 않음."""
        from src.schedulers.unified_scheduler import _locked_job

        call_count = 0

        async def _inner():
            nonlocal call_count
            call_count += 1

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)  # lock not acquired

        with patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            with patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock):
                wrapped = _locked_job("test_locked", _inner)
                await wrapped()

        assert call_count == 0

    @pytest.mark.asyncio
    async def test_locked_job_runs_when_lock_acquired(self):
        """분산 락 획득 성공 시 잡 함수가 실행됨."""
        from src.schedulers.unified_scheduler import _locked_job

        call_count = 0

        async def _inner():
            nonlocal call_count
            call_count += 1

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)

        with patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            with patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock):
                wrapped = _locked_job("test_locked", _inner)
                await wrapped()

        assert call_count == 1
