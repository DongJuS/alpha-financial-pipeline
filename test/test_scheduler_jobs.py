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


# ── 스케줄러 에지케이스 (Agent 4 QA Round 2) ─────────────────────────────────


class TestWithRetryEdgeCases:
    """with_retry: ��양한 예외 타입, 단일 시도, 즉시 성공 후 기록."""

    @pytest.mark.asyncio
    async def test_different_exception_types(self):
        """다양한 예외 타입이 모두 재시도를 트리거."""
        from src.schedulers.job_wrapper import with_retry

        exceptions = [ValueError("val"), TypeError("type"), RuntimeError("rt")]
        attempt = 0

        async def _multi_exception():
            nonlocal attempt
            if attempt < len(exceptions):
                exc = exceptions[attempt]
                attempt += 1
                raise exc

        with (
            patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock) as mock_rec,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            wrapped = with_retry(_multi_exception, "test_multi_exc", max_retries=4, base_delay=0)
            await wrapped()

        assert attempt == 3  # 3번 실패 후 4번째에서 성공
        mock_rec.assert_awaited_once()
        assert mock_rec.call_args.args[1] == "success"

    @pytest.mark.asyncio
    async def test_single_retry_with_immediate_failure(self):
        """max_retries=1이면 한 번만 시도 후 failed 기록."""
        from src.schedulers.job_wrapper import with_retry

        call_count = 0

        async def _always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("DB down")

        with (
            patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock) as mock_rec,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            wrapped = with_retry(_always_fail, "test_single", max_retries=1, base_delay=0)
            await wrapped()

        assert call_count == 1
        assert mock_rec.call_args.args[1] == "failed"
        assert "DB down" in mock_rec.call_args.kwargs.get("error", "")

    @pytest.mark.asyncio
    async def test_zero_base_delay_no_sleep(self):
        """base_delay=0이면 sleep이 0초로 호출 (즉시 재시도)."""
        from src.schedulers.job_wrapper import with_retry

        sleep_calls = []

        async def _failing():
            raise RuntimeError("fail")

        async def _track_sleep(delay):
            sleep_calls.append(delay)

        with (
            patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=_track_sleep),
        ):
            wrapped = with_retry(_failing, "test_zero_delay", max_retries=3, base_delay=0)
            await wrapped()

        # base_delay=0 → 0*1=0, 0*2=0, so all delays are 0
        assert all(d == 0.0 for d in sleep_calls)


class TestDistributedLockEdgeCases:
    """DistributedLock: 동시 접근, 재진입 불가, 에러 시 락 해제."""

    @pytest.mark.asyncio
    async def test_lock_released_even_on_exception(self):
        """context body에서 예외 발��� 시에도 락이 해제되는지 확인."""
        from src.schedulers.distributed_lock import DistributedLock

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)

        with pytest.raises(ValueError, match="body error"):
            async with DistributedLock(mock_redis, "test:lock", ttl=10) as lock:
                assert lock.acquired is True
                raise ValueError("body error")

        # eval(Lua 스크립트)이 호출되어 락이 해제됨
        mock_redis.eval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sequential_acquisitions_use_different_tokens(self):
        """동일 키에 대한 순차 획득이 서로 다른 토큰을 사용."""
        from src.schedulers.distributed_lock import DistributedLock

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)

        tokens = []
        for _ in range(5):
            async with DistributedLock(mock_redis, "same:key", ttl=10) as lock:
                tokens.append(lock._token)

        assert len(set(tokens)) == 5  # 모두 고유

    @pytest.mark.asyncio
    async def test_acquired_false_after_release(self):
        """정상 해제 후 acquired가 False로 전환."""
        from src.schedulers.distributed_lock import DistributedLock

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)

        lock = DistributedLock(mock_redis, "test:key", ttl=10)
        async with lock:
            assert lock.acquired is True

        assert lock.acquired is False


class TestLockedJobEdgeCases:
    """_locked_job: 잡 내부 예외 시 동작, 락 TTL 매핑."""

    @pytest.mark.asyncio
    async def test_job_exception_propagated_through_retry(self):
        """잡 함수가 예외를 던지면 재시도 후에도 이력에 failed 기록."""
        from src.schedulers.unified_scheduler import _locked_job

        async def _boom():
            raise RuntimeError("job exploded")

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)

        with (
            patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis),
            patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock) as mock_rec,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            wrapped = _locked_job("test_boom", _boom)
            await wrapped()

        # with_retry가 failed를 기록해야 함
        mock_rec.assert_awaited_once()
        assert mock_rec.call_args.args[1] == "failed"

    @pytest.mark.asyncio
    async def test_locked_job_uses_correct_lock_key(self):
        """_locked_job이 올바른 키 형식으로 분산 락을 시도."""
        from src.schedulers.unified_scheduler import _locked_job

        async def _noop():
            pass

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)

        with (
            patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis),
            patch("src.schedulers.job_wrapper._record_history", new_callable=AsyncMock),
        ):
            wrapped = _locked_job("my_special_job", _noop)
            await wrapped()

        # redis.set이 호출된 키가 "scheduler:lock:my_special_job"인지 확인
        set_call = mock_redis.set.call_args
        assert set_call.args[0] == "scheduler:lock:my_special_job"
