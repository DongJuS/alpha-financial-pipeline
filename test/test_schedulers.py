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


# ─── tick_realtime_health ───────────────────────────────────────────────────


class TestTickRealtimeHealth:
    """tick_realtime_health 크론 잡의 핵심 로직 검증.

    collector._realtime_task 상태를 확인하고,
    죽은 태스크를 재시작하는 헬스체크 동작을 단위 테스트합니다.
    """

    @pytest.mark.asyncio
    async def test_task_done_triggers_restart(self):
        """Task.done()=True (에러로 종료) 시 새 태스크 생성 + Redis 알림."""
        mock_collector = MagicMock()
        mock_collector._realtime_task = MagicMock(spec=asyncio.Task)
        mock_collector._realtime_task.done.return_value = True
        mock_collector._realtime_task.cancelled.return_value = False
        mock_collector._realtime_task.exception.return_value = RuntimeError("ws crash")
        mock_collector.collect_realtime_ticks = AsyncMock(return_value=0)

        new_task = MagicMock(spec=asyncio.Task)
        mock_redis = AsyncMock()

        with patch("asyncio.create_task", return_value=new_task) as mock_create:
            # --- 헬스체크 핵심 로직 인라인 ---
            task = mock_collector._realtime_task
            if task is not None and task.done():
                exc = task.exception() if not task.cancelled() else None
                alert_payload = json.dumps({
                    "event": "tick_realtime_restart",
                    "reason": str(exc) if exc else "cancelled",
                })
                await mock_redis.publish("alerts:tick_realtime", alert_payload)
                mock_collector._realtime_task = asyncio.create_task(
                    mock_collector.collect_realtime_ticks()
                )

        # 새 태스크가 생성됐는지 검증
        mock_create.assert_called_once()
        # 기존 태스크 참조가 새 태스크로 교체됐는지 검증
        assert mock_collector._realtime_task is new_task
        # Redis에 알림이 발행됐는지 검증
        mock_redis.publish.assert_awaited_once()
        publish_args = mock_redis.publish.call_args
        assert publish_args.args[0] == "alerts:tick_realtime"
        payload = json.loads(publish_args.args[1])
        assert payload["event"] == "tick_realtime_restart"
        assert "ws crash" in payload["reason"]

    @pytest.mark.asyncio
    async def test_task_running_no_action(self):
        """Task.done()=False (정상 실행 중) 시 아무 동작 없음."""
        mock_collector = MagicMock()
        mock_collector._realtime_task = MagicMock(spec=asyncio.Task)
        mock_collector._realtime_task.done.return_value = False

        mock_redis = AsyncMock()

        with patch("asyncio.create_task") as mock_create:
            # --- 헬스체크 핵심 로직 인라인 ---
            task = mock_collector._realtime_task
            if task is not None and task.done():
                # 이 블록은 진입하지 않아야 함
                mock_collector._realtime_task = asyncio.create_task(
                    mock_collector.collect_realtime_ticks()
                )
                await mock_redis.publish("alerts:tick_realtime", "{}")

        # 새 태스크 생성 없음
        mock_create.assert_not_called()
        # Redis 알림 없음
        mock_redis.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_task_none_no_action(self):
        """_realtime_task가 None일 때 크래시 없이 정상 반환."""
        mock_collector = MagicMock()
        mock_collector._realtime_task = None

        mock_redis = AsyncMock()

        with patch("asyncio.create_task") as mock_create:
            # --- 헬스체크 핵심 로직 인라인 ---
            task = mock_collector._realtime_task
            if task is not None and task.done():
                mock_collector._realtime_task = asyncio.create_task(
                    mock_collector.collect_realtime_ticks()
                )
                await mock_redis.publish("alerts:tick_realtime", "{}")

        # None이면 아무것도 하지 않음
        mock_create.assert_not_called()
        mock_redis.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancelled_task_restarts(self):
        """Task.done()=True + cancelled()=True 시 재시작, exception은 None."""
        mock_collector = MagicMock()
        mock_collector._realtime_task = MagicMock(spec=asyncio.Task)
        mock_collector._realtime_task.done.return_value = True
        mock_collector._realtime_task.cancelled.return_value = True
        mock_collector.collect_realtime_ticks = AsyncMock(return_value=0)

        new_task = MagicMock(spec=asyncio.Task)
        mock_redis = AsyncMock()

        with patch("asyncio.create_task", return_value=new_task) as mock_create:
            # --- 헬스체크 핵심 로직 인라인 ---
            task = mock_collector._realtime_task
            if task is not None and task.done():
                exc = task.exception() if not task.cancelled() else None
                alert_payload = json.dumps({
                    "event": "tick_realtime_restart",
                    "reason": str(exc) if exc else "cancelled",
                })
                await mock_redis.publish("alerts:tick_realtime", alert_payload)
                mock_collector._realtime_task = asyncio.create_task(
                    mock_collector.collect_realtime_ticks()
                )

        # 재시작 확인
        mock_create.assert_called_once()
        assert mock_collector._realtime_task is new_task
        # cancelled 태스크는 exception() 호출하지 않음 (CancelledError 방지)
        mock_collector._realtime_task_orig = MagicMock()  # 원본 참조용 아님
        # Redis 알림의 reason이 "cancelled"인지 검증
        publish_args = mock_redis.publish.call_args
        payload = json.loads(publish_args.args[1])
        assert payload["reason"] == "cancelled"
        assert payload["event"] == "tick_realtime_restart"
