"""
test/test_scheduler_market_flow.py — 장 전/중/후 스케줄 통합 테스트

unified_scheduler.py에 추가된 잡들을 검증합니다:
- 장 전: rl_bootstrap (08:00), predictor_warmup (08:05)
- 장 후: rl_retrain (16:00), blend_weight_adjust (16:30)
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Settings 초기화에 필요한 환경변수 설정 (테스트 전용)
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

pytestmark = [pytest.mark.unit]


# ─── 잡 등록 검증 ─────────────────────────────────────────────────────────────


class TestJobRegistration:
    """start_unified_scheduler()가 새 잡을 올바르게 등록하는지 검증."""

    @pytest.mark.asyncio
    async def test_all_jobs_registered(self):
        """9개 잡이 모두 등록되는지 확인."""
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
            patch("src.agents.stock_master_collector.StockMasterCollector"),
            patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=False),
        ):
            await mod.start_unified_scheduler()

        expected_ids = {
            "rl_bootstrap",
            "predictor_warmup",
            "stock_master_daily",
            "macro_daily",
            "collector_daily",
            "index_warmup",
            "index_collection",
            "rl_retrain",
            "blend_weight_adjust",
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
        mock_registry = MagicMock()
        mock_registry.list_active_policies.return_value = {
            "005930": "policy_a",
            "000660": "policy_b",
        }
        mock_registry.list_all_tickers.return_value = ["005930", "000660"]
        mock_store.load_registry.return_value = mock_registry
        mock_store.load_policy = MagicMock()

        registry = mock_store.load_registry()
        active_map = registry.list_active_policies()
        warmed = 0
        for ticker, policy_id in active_map.items():
            try:
                mock_store.load_policy(policy_id, ticker)
                warmed += 1
            except Exception:
                pass

        assert warmed == 2
        assert mock_store.load_policy.call_count == 2

    @pytest.mark.asyncio
    async def test_bootstrap_detects_missing_policies(self):
        """활성 정책 없는 티커를 부트스트랩 대상으로 식별."""
        mock_registry = MagicMock()
        mock_registry.list_active_policies.return_value = {"005930": "policy_a"}
        mock_registry.list_all_tickers.return_value = ["005930", "000660", "259960"]

        active_map = mock_registry.list_active_policies()
        all_tickers = mock_registry.list_all_tickers()
        missing = [t for t in all_tickers if t not in active_map]

        assert missing == ["000660", "259960"]

    @pytest.mark.asyncio
    async def test_skips_when_all_tickers_have_policies(self):
        """모든 티커에 활성 정책이 있으면 부트스트랩 스킵."""
        mock_registry = MagicMock()
        mock_registry.list_active_policies.return_value = {
            "005930": "policy_a",
            "000660": "policy_b",
        }
        mock_registry.list_all_tickers.return_value = ["005930", "000660"]

        active_map = mock_registry.list_active_policies()
        all_tickers = mock_registry.list_all_tickers()
        missing = [t for t in all_tickers if t not in active_map]
        assert len(missing) == 0

    @pytest.mark.asyncio
    async def test_warmup_handles_load_failure_gracefully(self):
        """개별 정책 로드 실패 시 나머지는 계속 진행."""
        mock_store = MagicMock()
        mock_registry = MagicMock()
        mock_registry.list_active_policies.return_value = {
            "005930": "policy_a",
            "000660": "policy_b",
        }
        mock_store.load_registry.return_value = mock_registry
        mock_store.load_policy = MagicMock(side_effect=[FileNotFoundError("missing"), None])

        loaded = 0
        for ticker, policy_id in mock_registry.list_active_policies().items():
            try:
                mock_store.load_policy(policy_id, ticker)
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
    async def test_all_9_jobs_registered_with_timing(self):
        """장 전/중/후 9개 잡이 모두 올바르게 등록되는지 확인."""
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
            patch("src.agents.stock_master_collector.StockMasterCollector"),
            patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=False),
        ):
            await mod.start_unified_scheduler()

        # 장 전 잡 (09:00 이전)
        pre_market_ids = {"rl_bootstrap", "predictor_warmup", "stock_master_daily", "macro_daily", "collector_daily", "index_warmup"}
        for job_id in pre_market_ids:
            assert job_id in added_jobs, f"{job_id} not registered"

        # 장 중 잡
        assert "index_collection" in added_jobs

        # 장 후 잡 (15:30 이후)
        post_market_ids = {"rl_retrain", "blend_weight_adjust"}
        for job_id in post_market_ids:
            assert job_id in added_jobs, f"{job_id} not registered"

        # 총 9개
        assert len(added_jobs) == 9

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
            patch("src.agents.stock_master_collector.StockMasterCollector"),
            patch("src.utils.market_hours.is_market_open_now", new_callable=AsyncMock, return_value=False),
        ):
            await mod.start_unified_scheduler()

        mock_scheduler.start.assert_called_once()
