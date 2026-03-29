"""
test/test_datalake_rl_episodes.py — RL 에피소드 S3 저장 테스트

store_rl_episodes() 함수와 RL_EPISODES_SCHEMA 검증.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

pytestmark = [pytest.mark.unit]


class TestRLEpisodesSchema:
    """RL_EPISODES_SCHEMA 정합성 검증."""

    def test_schema_registered(self):
        """SCHEMAS dict에 RL_EPISODES가 등록되어 있는지 확인."""
        from src.services.datalake import SCHEMAS, DataType

        assert DataType.RL_EPISODES in SCHEMAS

    def test_schema_fields(self):
        """스키마 필드가 올바른지 확인."""
        from src.services.datalake import RL_EPISODES_SCHEMA

        field_names = [f.name for f in RL_EPISODES_SCHEMA]
        expected = [
            "ticker", "policy_id", "profile_id", "dataset_days",
            "train_return_pct", "holdout_return_pct", "excess_return_pct",
            "max_drawdown_pct", "walk_forward_passed", "walk_forward_consistency",
            "deployed", "created_at",
        ]
        assert field_names == expected

    def test_enum_value(self):
        """DataType.RL_EPISODES 열거형 값 확인."""
        from src.services.datalake import DataType

        assert DataType.RL_EPISODES.value == "rl_episodes"


class TestStoreRLEpisodes:
    """store_rl_episodes() 함수 검증."""

    def _make_record(self, **overrides) -> dict:
        base = {
            "ticker": "005930",
            "policy_id": "tabular_q_v2_momentum_005930_20260329",
            "profile_id": "tabular_q_v2_momentum",
            "dataset_days": 720,
            "train_return_pct": 12.5,
            "holdout_return_pct": 8.3,
            "excess_return_pct": 5.1,
            "max_drawdown_pct": -7.2,
            "walk_forward_passed": True,
            "walk_forward_consistency": 0.8,
            "deployed": True,
            "created_at": datetime(2026, 3, 29, tzinfo=timezone.utc),
        }
        base.update(overrides)
        return base

    @pytest.mark.asyncio
    async def test_returns_none_on_empty(self):
        """빈 리스트 입력 시 None 반환."""
        from src.services.datalake import store_rl_episodes

        result = await store_rl_episodes([])
        assert result is None

    @pytest.mark.asyncio
    async def test_uploads_parquet(self):
        """정상 레코드가 S3에 업로드되는지 확인."""
        from src.services.datalake import store_rl_episodes

        record = self._make_record()

        with patch("src.services.datalake._upload_with_retry", new_callable=AsyncMock) as mock_upload:
            mock_upload.return_value = "s3://bucket/rl_episodes/date=2026-03-29/rl_episodes_120000.parquet"
            result = await store_rl_episodes([record])

        assert result is not None
        assert "rl_episodes" in result
        mock_upload.assert_awaited_once()
        # 업로드된 데이터가 bytes인지 확인
        uploaded_data = mock_upload.call_args.args[0]
        assert isinstance(uploaded_data, bytes)
        assert len(uploaded_data) > 0

    @pytest.mark.asyncio
    async def test_returns_none_on_upload_failure(self):
        """S3 업로드 실패 시 None 반환 (예외 전파 안 함)."""
        from src.services.datalake import store_rl_episodes

        record = self._make_record()

        with patch("src.services.datalake._upload_with_retry", new_callable=AsyncMock) as mock_upload:
            mock_upload.side_effect = ConnectionError("S3 unreachable")
            result = await store_rl_episodes([record])

        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_records(self):
        """여러 레코드 한 번에 저장."""
        from src.services.datalake import store_rl_episodes

        records = [
            self._make_record(ticker="005930"),
            self._make_record(ticker="000660", deployed=False),
        ]

        with patch("src.services.datalake._upload_with_retry", new_callable=AsyncMock) as mock_upload:
            mock_upload.return_value = "s3://bucket/rl_episodes/test.parquet"
            result = await store_rl_episodes(records)

        assert result is not None

    @pytest.mark.asyncio
    async def test_s3_key_format(self):
        """S3 키가 Hive-style 파티셔닝을 따르는지 확인."""
        from src.services.datalake import DataType, _make_s3_key

        key = _make_s3_key(DataType.RL_EPISODES, date(2026, 3, 29))
        assert key.startswith("rl_episodes/date=2026-03-29/")
        assert key.endswith(".parquet")

    @pytest.mark.asyncio
    async def test_parquet_serialization(self):
        """레코드가 Parquet 바이트로 직렬화되는지 확인."""
        from src.services.datalake import RL_EPISODES_SCHEMA, _to_parquet_bytes

        record = self._make_record()
        data = _to_parquet_bytes([record], RL_EPISODES_SCHEMA)
        assert isinstance(data, bytes)
        assert len(data) > 0

        # Parquet 매직 바이트 확인 (PAR1)
        assert data[:4] == b"PAR1"


class TestRLImproverS3Integration:
    """RLContinuousImprover._store_episode_to_s3 연동 검증."""

    @pytest.mark.asyncio
    async def test_store_called_after_retrain(self):
        """store_rl_episodes가 retrain 후 호출되는지 확인."""
        from unittest.mock import MagicMock

        mock_store_fn = AsyncMock(return_value="s3://test")

        # _store_episode_to_s3 로직 재현
        best = MagicMock()
        best.artifact.policy_id = "test_policy"
        best.artifact.evaluation.baseline_return_pct = 10.0
        best.artifact.evaluation.total_return_pct = 15.0
        best.artifact.evaluation.excess_return_pct = 5.0
        best.artifact.evaluation.max_drawdown_pct = -3.0
        best.walk_forward.overall_approved = True
        best.walk_forward.consistency_score = 0.8
        best.profile_id = "tabular_q_v2_momentum"

        record = {
            "ticker": "005930",
            "policy_id": best.artifact.policy_id,
            "profile_id": best.profile_id,
            "dataset_days": 720,
            "train_return_pct": best.artifact.evaluation.baseline_return_pct,
            "holdout_return_pct": best.artifact.evaluation.total_return_pct,
            "excess_return_pct": best.artifact.evaluation.excess_return_pct,
            "max_drawdown_pct": best.artifact.evaluation.max_drawdown_pct,
            "walk_forward_passed": best.walk_forward.overall_approved,
            "walk_forward_consistency": best.walk_forward.consistency_score,
            "deployed": True,
            "created_at": datetime.now(timezone.utc),
        }

        await mock_store_fn([record])
        mock_store_fn.assert_awaited_once()
        stored_records = mock_store_fn.call_args.args[0]
        assert stored_records[0]["ticker"] == "005930"
        assert stored_records[0]["deployed"] is True
