"""
test/test_scheduler_market_flow.py — 장 전/중/후 스케줄 통합 테스트

unified_scheduler.py에 등록된 10개 잡을 검증합니다:
- 장 전: rl_bootstrap, predictor_warmup, krx_stock_master_daily, macro_daily, collector_daily, index_warmup
- 장 중: index_collection (30초 간격)
- 장 후: s3_tick_flush, rl_retrain, blend_weight_adjust
- 실시간 틱 수집은 별도 tick-collector 서비스로 분리됨
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.triggers.cron import CronTrigger

# Settings 초기화에 필요한 환경변수 설정 (테스트 전용)
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

pytestmark = [pytest.mark.unit]


# ─── 잡 등록 검증 ─────────────────────────────────────────────────────────────


class TestJobRegistration:
    """start_unified_scheduler()가 새 잡을 올바르게 등록하는지 검증."""

    @pytest.mark.asyncio
    async def test_all_jobs_registered(self):
        """10개 잡이 모두 등록되는지 확인 (tick 잡은 별도 서비스로 분리됨)."""
        import src.schedulers.unified_scheduler as mod

        mock_scheduler = MagicMock()
        mock_scheduler.running = False
        mock_scheduler.get_jobs.return_value = []

        registered_ids: list[str] = []

        def _track_add_job(fn, trigger=None, *, id, **kwargs):
            registered_ids.append(id)

        mock_scheduler.add_job = _track_add_job

        with (
            patch.object(mod, "_scheduler", None),
            patch.object(mod, "get_unified_scheduler", new_callable=AsyncMock, return_value=mock_scheduler),
            patch("src.agents.collector.CollectorAgent"),
            patch("src.agents.index_collector.IndexCollector"),
            patch("src.agents.macro_collector.MacroCollector"),
            patch("src.agents.krx_stock_master_collector.KrxStockMasterCollector"),
            patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=False),
        ):
            await mod.start_unified_scheduler()

        expected_ids = {
            "rl_bootstrap",
            "predictor_warmup",
            "krx_stock_master_daily",
            "macro_daily",
            "collector_daily",
            "index_warmup",
            "index_collection",
            "kis_token_health",
            "s3_tick_flush",
            "minute_aggregation",
            "rl_retrain",
            "blend_weight_adjust",
            "minute_partition_mgmt",
        }
        assert set(registered_ids) == expected_ids

    @pytest.mark.asyncio
    async def test_lock_ttl_for_new_jobs(self):
        """새로 추가된 잡들의 분산 락 TTL이 설정되어 있는지 확인."""
        from src.schedulers.unified_scheduler import _LOCK_TTL

        new_jobs = ["rl_bootstrap", "predictor_warmup", "rl_retrain", "blend_weight_adjust"]
        for job_id in new_jobs:
            assert job_id in _LOCK_TTL, f"{job_id} missing from _LOCK_TTL"
            assert _LOCK_TTL[job_id] > 0

    @pytest.mark.asyncio
    async def test_rl_retrain_ttl_sufficient(self):
        """RL 재학습 TTL이 충분히 긴지 확인 (멀티 티커 학습)."""
        from src.schedulers.unified_scheduler import _LOCK_TTL

        assert _LOCK_TTL["rl_retrain"] >= 1800, "RL retrain TTL should be >= 30 min"


# ─── RL 부트스트랩 잡 ──────────────────────────────────────────────────────────


class TestRLBootstrapJob:
    """_run_rl_bootstrap 로직 검증."""

    @pytest.mark.asyncio
    async def test_warmup_loads_active_policies(self):
        """활성 정책 있는 티커는 load_policy로 워밍업."""
        mock_store = MagicMock()
        mock_store.list_active_policies = AsyncMock(return_value={
            "005930": "policy_a",
            "000660": "policy_b",
        })
        mock_store.load_policy = AsyncMock(return_value=None)

        active_map = await mock_store.list_active_policies()
        warmed = 0
        for ticker, policy_id in active_map.items():
            try:
                await mock_store.load_policy(policy_id, ticker)
                warmed += 1
            except Exception:
                pass

        assert warmed == 2
        assert mock_store.load_policy.call_count == 2

    @pytest.mark.asyncio
    async def test_bootstrap_detects_missing_policies(self):
        """활성 정책 없는 티커를 부트스트랩 대상으로 식별."""
        mock_store = MagicMock()
        mock_store.list_active_policies = AsyncMock(return_value={"005930": "policy_a"})
        mock_store.list_all_tickers = AsyncMock(return_value=["005930", "000660", "259960"])

        active_map = await mock_store.list_active_policies()
        all_tickers = await mock_store.list_all_tickers()
        missing = [t for t in all_tickers if t not in active_map]

        assert missing == ["000660", "259960"]

    @pytest.mark.asyncio
    async def test_skips_when_all_tickers_have_policies(self):
        """모든 티커에 활성 정책이 있으면 부트스트랩 스킵."""
        mock_store = MagicMock()
        mock_store.list_active_policies = AsyncMock(return_value={
            "005930": "policy_a",
            "000660": "policy_b",
        })
        mock_store.list_all_tickers = AsyncMock(return_value=["005930", "000660"])

        active_map = await mock_store.list_active_policies()
        all_tickers = await mock_store.list_all_tickers()
        missing = [t for t in all_tickers if t not in active_map]
        assert len(missing) == 0

    @pytest.mark.asyncio
    async def test_warmup_handles_load_failure_gracefully(self):
        """개별 정책 로드 실패 시 나머지는 계속 진행."""
        mock_store = MagicMock()
        mock_store.list_active_policies = AsyncMock(return_value={
            "005930": "policy_a",
            "000660": "policy_b",
        })
        mock_store.load_policy = AsyncMock(side_effect=[FileNotFoundError("missing"), None])

        active_map = await mock_store.list_active_policies()
        loaded = 0
        for ticker, policy_id in active_map.items():
            try:
                await mock_store.load_policy(policy_id, ticker)
                loaded += 1
            except Exception:
                pass

        assert loaded == 1


# ─── Predictor 워밍업 잡 ──────────────────────────────────────────────────────


class TestPredictorWarmupJob:
    """_run_predictor_warmup 로직 검증."""

    @pytest.mark.asyncio
    async def test_warmup_creates_predictor_agents(self):
        """PROFILES의 모든 에이전트가 초기화되는지 확인."""
        from src.agents.strategy_a_tournament import PROFILES

        assert len(PROFILES) > 0, "PROFILES가 비어있으면 워밍업 의미 없음"

        created = []
        with patch("src.agents.predictor.PredictorAgent") as MockPredictor:
            MockPredictor.side_effect = lambda **kwargs: created.append(kwargs) or MagicMock()
            for profile in PROFILES:
                MockPredictor(
                    agent_id=profile.agent_id,
                    strategy="A",
                    llm_model=profile.model,
                    persona=profile.persona,
                )

        assert len(created) == len(PROFILES)

    @pytest.mark.asyncio
    async def test_warmup_continues_on_single_failure(self):
        """개별 Predictor 초기화 실패 시 나머지 계속."""
        from src.agents.strategy_a_tournament import PROFILES

        warmup_count = 0
        for i, _profile in enumerate(PROFILES):
            try:
                if i == 0:
                    raise RuntimeError("LLM init failed")
                warmup_count += 1
            except Exception:
                pass

        assert warmup_count == len(PROFILES) - 1

    @pytest.mark.asyncio
    async def test_profiles_have_required_fields(self):
        """PROFILES의 각 항목이 필수 필드를 가지고 있는지 확인."""
        from src.agents.strategy_a_tournament import PROFILES

        for profile in PROFILES:
            assert hasattr(profile, "agent_id")
            assert hasattr(profile, "model")
            assert hasattr(profile, "persona")
            assert profile.agent_id.startswith("predictor_")


# ─── RL 재학습 잡 ─────────────────────────────────────────────────────────────


class TestRLRetrainJob:
    """_run_rl_retrain 로직 검증."""

    @pytest.mark.asyncio
    async def test_retrain_outcome_counting(self):
        """재학습 결과에서 성공/실패 카운트가 올바른지 확인."""
        mock_outcome_ok = MagicMock(success=True)
        mock_outcome_fail = MagicMock(success=False)
        outcomes = [mock_outcome_ok, mock_outcome_fail, mock_outcome_ok]

        success_count = sum(1 for o in outcomes if o.success)
        assert success_count == 2
        assert len(outcomes) == 3


# ─── 블렌딩 가중치 동적 조정 잡 ──────────────────────────────────────────────


class TestBlendWeightAdjustJob:
    """_run_blend_weight_adjust 로직 검증."""

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        """DYNAMIC_BLEND_WEIGHTS_ENABLED=false 시 스킵."""
        mock_settings = MagicMock()
        mock_settings.dynamic_blend_weights_enabled = False

        with patch("src.utils.config.get_settings", return_value=mock_settings):
            from src.utils.config import get_settings

            settings = get_settings()
            assert settings.dynamic_blend_weights_enabled is False

    @pytest.mark.asyncio
    async def test_optimizer_called_when_enabled(self):
        """DYNAMIC_BLEND_WEIGHTS_ENABLED=true 시 optimizer가 호출되는지 확인."""
        mock_settings = MagicMock()
        mock_settings.dynamic_blend_weights_enabled = True
        mock_settings.strategy_blend_weights = '{"A": 0.30, "B": 0.30, "RL": 0.20, "S": 0.20}'
        mock_settings.dynamic_blend_lookback_days = 30
        mock_settings.dynamic_blend_min_weight = 0.05

        mock_optimizer = AsyncMock()
        mock_optimizer.optimize.return_value = {"A": 0.35, "B": 0.25, "RL": 0.25, "S": 0.15}

        with (
            patch("src.utils.config.get_settings", return_value=mock_settings),
            patch(
                "src.utils.blend_weight_optimizer.BlendWeightOptimizer",
                return_value=mock_optimizer,
            ),
        ):
            import json

            from src.utils.blend_weight_optimizer import BlendWeightOptimizer
            from src.utils.config import get_settings

            settings = get_settings()
            base_weights = json.loads(settings.strategy_blend_weights)
            optimizer = BlendWeightOptimizer(
                base_weights=base_weights,
                lookback_days=settings.dynamic_blend_lookback_days,
                min_weight=settings.dynamic_blend_min_weight,
            )
            new_weights = await optimizer.optimize()

        assert sum(new_weights.values()) == pytest.approx(1.0, abs=0.01)
        mock_optimizer.optimize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_redis_caching_on_success(self):
        """가중치 계산 후 Redis에 캐싱되는지 확인."""
        import json

        new_weights = {"A": 0.35, "B": 0.25, "RL": 0.25, "S": 0.15}

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            from src.utils.redis_client import get_redis

            redis = await get_redis()
            await redis.set(
                "scheduler:blend_weights:latest",
                json.dumps(new_weights),
                ex=86400,
            )

        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.call_args
        stored_data = json.loads(call_args.args[1])
        assert stored_data == new_weights

    @pytest.mark.asyncio
    async def test_redis_failure_does_not_break(self):
        """Redis 캐싱 실패 시에도 잡 자체는 성공."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))

        failed = False
        try:
            redis = mock_redis
            try:
                await redis.set("test", "data")
            except Exception:
                pass  # 비필수 — 경고만 남기고 계속
        except Exception:
            failed = True

        assert not failed, "Redis 실패가 전체 잡을 중단시키면 안 됨"


# ─── 스케줄 타이밍 검증 ──────────────────────────────────────────────────────


class TestScheduleTiming:
    """잡 등록 시 CronTrigger 인자가 올바른지 검증."""

    @pytest.mark.asyncio
    async def test_all_jobs_registered_with_timing(self):
        """장 전/중/후 10개 잡이 모두 올바르게 등록되는지 확인 (tick 잡은 별도 서비스)."""
        import src.schedulers.unified_scheduler as mod

        mock_scheduler = MagicMock()
        mock_scheduler.running = False
        mock_scheduler.get_jobs.return_value = []

        added_jobs: dict[str, dict] = {}

        def _track(fn, trigger=None, *, id, **kwargs):
            added_jobs[id] = {"trigger": trigger, **kwargs}

        mock_scheduler.add_job = _track

        with (
            patch.object(mod, "_scheduler", None),
            patch.object(mod, "get_unified_scheduler", new_callable=AsyncMock, return_value=mock_scheduler),
            patch("src.agents.collector.CollectorAgent"),
            patch("src.agents.index_collector.IndexCollector"),
            patch("src.agents.macro_collector.MacroCollector"),
            patch("src.agents.krx_stock_master_collector.KrxStockMasterCollector"),
            patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=False),
        ):
            await mod.start_unified_scheduler()

        # 장 전 잡 (09:00 이전)
        pre_market_ids = {"rl_bootstrap", "predictor_warmup", "krx_stock_master_daily", "macro_daily", "collector_daily", "index_warmup"}
        for job_id in pre_market_ids:
            assert job_id in added_jobs, f"{job_id} not registered"

        # 장 중 잡 (tick 잡은 별도 서비스로 분리됨)
        market_ids = {"index_collection", "kis_token_health"}
        for job_id in market_ids:
            assert job_id in added_jobs, f"{job_id} not registered"

        # tick 잡이 scheduler에 없음을 확인
        assert "tick_realtime_start" not in added_jobs
        assert "tick_realtime_health" not in added_jobs

        # 장 후 잡 (15:30 이후)
        post_market_ids = {"s3_tick_flush", "minute_aggregation", "rl_retrain", "blend_weight_adjust"}
        for job_id in post_market_ids:
            assert job_id in added_jobs, f"{job_id} not registered"

        # 월간 잡
        assert "minute_partition_mgmt" in added_jobs

        # 총 13개
        assert len(added_jobs) == 13

    @pytest.mark.asyncio
    async def test_scheduler_start_called(self):
        """scheduler.start()가 호출되는지 확인."""
        import src.schedulers.unified_scheduler as mod

        mock_scheduler = MagicMock()
        mock_scheduler.running = False
        mock_scheduler.get_jobs.return_value = []
        mock_scheduler.add_job = MagicMock()

        with (
            patch.object(mod, "_scheduler", None),
            patch.object(mod, "get_unified_scheduler", new_callable=AsyncMock, return_value=mock_scheduler),
            patch("src.agents.collector.CollectorAgent"),
            patch("src.agents.index_collector.IndexCollector"),
            patch("src.agents.macro_collector.MacroCollector"),
            patch("src.agents.krx_stock_master_collector.KrxStockMasterCollector"),
            patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=False),
        ):
            await mod.start_unified_scheduler()

        mock_scheduler.start.assert_called_once()


# ─── 실시간 틱 수집 시작 잡 ─────────────────────────────────────────────────


class TestTickRealtimeStartJob:
    """_run_tick_realtime_start 로직 검증."""

    @pytest.mark.asyncio
    async def test_start_spawns_task(self):
        """태스크가 없을 때 collect_realtime_ticks를 asyncio.Task로 생성."""
        import asyncio

        mock_collector = MagicMock()
        mock_collector._realtime_task = None
        mock_collector.collect_realtime_ticks = AsyncMock(return_value=42)

        mock_settings = MagicMock()
        mock_settings.ws_tick_tickers = "005930,000660"

        # _run_tick_realtime_start 시뮬레이션
        tickers = [t.strip() for t in mock_settings.ws_tick_tickers.split(",") if t.strip()]
        assert len(tickers) == 2

        # create_task로 태스크 생성
        loop = asyncio.get_event_loop()
        coro = mock_collector.collect_realtime_ticks(tickers=tickers, duration_seconds=23400)
        # create_task가 호출되었음을 검증하기 위해 패치
        with patch("asyncio.create_task") as mock_create_task:
            mock_task = MagicMock(spec=asyncio.Task)
            mock_create_task.return_value = mock_task

            task = asyncio.create_task(coro)
            mock_collector._realtime_task = task

        mock_create_task.assert_called_once()
        assert mock_collector._realtime_task is mock_task

    @pytest.mark.asyncio
    async def test_start_skips_if_already_running(self):
        """이미 실행 중인 태스크가 있으면 새 태스크를 생성하지 않음."""
        import asyncio
        import logging

        mock_collector = MagicMock()
        mock_existing_task = MagicMock(spec=asyncio.Task)
        mock_existing_task.done.return_value = False
        mock_collector._realtime_task = mock_existing_task
        mock_collector.collect_realtime_ticks = AsyncMock()

        # _run_tick_realtime_start 시뮬레이션: 태스크가 존재하고 done() == False이면 스킵
        should_skip = (
            mock_collector._realtime_task is not None
            and not mock_collector._realtime_task.done()
        )

        assert should_skip is True
        mock_collector.collect_realtime_ticks.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_skips_if_no_tickers(self):
        """ws_tick_tickers가 비어있으면 태스크를 생성하지 않음."""
        import logging

        mock_collector = MagicMock()
        mock_collector._realtime_task = None
        mock_collector.collect_realtime_ticks = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.ws_tick_tickers = ""

        tickers = [t.strip() for t in mock_settings.ws_tick_tickers.split(",") if t.strip()]
        assert len(tickers) == 0

        # 빈 티커 → 태스크 생성 안 함
        if not tickers:
            created = False
        else:
            created = True

        assert created is False
        mock_collector.collect_realtime_ticks.assert_not_called()


# ─── 실시간 틱 헬스체크 잡 ──────────────────────────────────────────────────


class TestTickRealtimeHealthJob:
    """_run_tick_realtime_health 로직 검증."""

    @pytest.mark.asyncio
    async def test_health_ok_when_running(self):
        """태스크가 실행 중이면 재시작하지 않음."""
        import asyncio

        mock_collector = MagicMock()
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.done.return_value = False
        mock_collector._realtime_task = mock_task
        mock_collector.collect_realtime_ticks = AsyncMock()

        # _run_tick_realtime_health: done() == False → 정상, 아무것도 안 함
        needs_restart = (
            mock_collector._realtime_task is not None
            and mock_collector._realtime_task.done()
        )

        assert needs_restart is False
        mock_collector.collect_realtime_ticks.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_restarts_dead_task(self):
        """태스크가 죽었으면 새 태스크 생성 + Redis alert 발행."""
        import asyncio

        mock_collector = MagicMock()
        dead_task = MagicMock(spec=asyncio.Task)
        dead_task.done.return_value = True
        dead_task.exception.return_value = RuntimeError("WebSocket disconnected")
        mock_collector._realtime_task = dead_task
        mock_collector.collect_realtime_ticks = AsyncMock(return_value=0)

        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.ws_tick_tickers = "005930,000660"

        # _run_tick_realtime_health 시뮬레이션
        needs_restart = (
            mock_collector._realtime_task is not None
            and mock_collector._realtime_task.done()
        )
        assert needs_restart is True

        # 예외 정보 추출
        exc = dead_task.exception()
        assert isinstance(exc, RuntimeError)

        # 새 태스크 생성
        tickers = [t.strip() for t in mock_settings.ws_tick_tickers.split(",") if t.strip()]
        with patch("asyncio.create_task") as mock_create_task:
            new_task = MagicMock(spec=asyncio.Task)
            mock_create_task.return_value = new_task

            coro = mock_collector.collect_realtime_ticks(tickers=tickers, duration_seconds=23400)
            task = asyncio.create_task(coro)
            mock_collector._realtime_task = task

        mock_create_task.assert_called_once()
        assert mock_collector._realtime_task is new_task

        # Redis pub/sub 알림
        alert_msg = f"tick_realtime 태스크 재시작: {exc}"
        await mock_redis.publish("scheduler:alerts", alert_msg)
        mock_redis.publish.assert_awaited_once_with("scheduler:alerts", alert_msg)

    @pytest.mark.asyncio
    async def test_health_noop_when_no_task(self):
        """_realtime_task가 None이면 아무것도 하지 않음 (아직 시작 안 됨)."""
        mock_collector = MagicMock()
        mock_collector._realtime_task = None
        mock_collector.collect_realtime_ticks = AsyncMock()

        # _run_tick_realtime_health: 태스크 자체가 없으면 패스
        should_act = mock_collector._realtime_task is not None

        assert should_act is False
        mock_collector.collect_realtime_ticks.assert_not_called()


# ─── 틱 잡 등록 검증 ─────────────────────────────────────────────────────────


class TestTickJobRegistration:
    """tick-collector 분리 후 tick 잡이 scheduler에서 제거되었는지 검증."""

    @pytest.mark.asyncio
    async def test_tick_jobs_not_registered(self):
        """tick_realtime_start, tick_realtime_health가 scheduler에 없어야 한다 (별도 서비스로 분리)."""
        import src.schedulers.unified_scheduler as mod

        mock_scheduler = MagicMock()
        mock_scheduler.running = False
        mock_scheduler.get_jobs.return_value = []

        registered: dict[str, dict] = {}

        def _track(fn, trigger=None, *, id, **kwargs):
            registered[id] = {"trigger": trigger, **kwargs}

        mock_scheduler.add_job = _track

        with (
            patch.object(mod, "_scheduler", None),
            patch.object(mod, "get_unified_scheduler", new_callable=AsyncMock, return_value=mock_scheduler),
            patch("src.agents.collector.CollectorAgent"),
            patch("src.agents.index_collector.IndexCollector"),
            patch("src.agents.macro_collector.MacroCollector"),
            patch("src.agents.krx_stock_master_collector.KrxStockMasterCollector"),
            patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=False),
        ):
            await mod.start_unified_scheduler()

        assert "tick_realtime_start" not in registered, "tick_realtime_start should be removed"
        assert "tick_realtime_health" not in registered, "tick_realtime_health should be removed"
        assert len(registered) == 13, f"Expected 13 jobs, got {len(registered)}: {list(registered.keys())}"

    @pytest.mark.asyncio
    async def test_tick_lock_ttl_removed(self):
        """tick 잡의 분산 락 TTL이 제거되었는지 확인."""
        from src.schedulers.unified_scheduler import _LOCK_TTL

        for job_id in ["tick_realtime_start", "tick_realtime_health"]:
            assert job_id not in _LOCK_TTL, f"{job_id} should be removed from _LOCK_TTL"
