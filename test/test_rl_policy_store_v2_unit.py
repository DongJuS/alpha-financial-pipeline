"""
test/test_rl_policy_store_v2_unit.py — RLPolicyStoreV2 단위 테스트

DB 의존성을 mock으로 격리하고, 파일 I/O + 아티팩트 로딩 + 승격 게이트 로직을 검증합니다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.rl_policy_registry import (
    PolicyEntry,
    algorithm_dir_name,
    build_relative_path,
)
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.agents.rl_trading import RLEvaluationMetrics, RLPolicyArtifact


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_artifact(
    policy_id: str = "test_policy",
    ticker: str = "005930.KS",
    algorithm: str = "tabular_q_learning",
    approved: bool = True,
    total_return: float = 10.0,
    drawdown: float = -10.0,
    model_path: str | None = None,
) -> RLPolicyArtifact:
    return RLPolicyArtifact(
        policy_id=policy_id,
        ticker=ticker,
        created_at=datetime.now(timezone.utc).isoformat(),
        algorithm=algorithm,
        state_version="v2",
        lookback=20,
        episodes=10,
        learning_rate=0.001,
        discount_factor=0.95,
        epsilon=0.05,
        trade_penalty_bps=2,
        evaluation=RLEvaluationMetrics(
            total_return_pct=total_return,
            baseline_return_pct=5.0,
            excess_return_pct=total_return - 5.0,
            max_drawdown_pct=drawdown,
            trades=20,
            win_rate=0.6,
            holdout_steps=40,
            approved=approved,
        ),
        q_table={"s1": {"BUY": 1.0}} if algorithm == "tabular_q_learning" else None,
        model_path=model_path,
    )


def _make_policy_entry(
    policy_id: str = "test_policy",
    ticker: str = "005930.KS",
    approved: bool = True,
    return_pct: float = 10.0,
    drawdown: float = -10.0,
    file_path: str = "tabular/005930.KS/test_policy.json",
) -> PolicyEntry:
    return PolicyEntry(
        policy_id=policy_id,
        instrument_id=ticker,
        algorithm="tabular_q_learning",
        state_version="v2",
        return_pct=return_pct,
        baseline_return_pct=5.0,
        excess_return_pct=return_pct - 5.0,
        max_drawdown_pct=drawdown,
        trades=20,
        win_rate=0.6,
        holdout_steps=40,
        approved=approved,
        is_active=False,
        created_at=datetime.now(timezone.utc),
        file_path=file_path,
    )


# ── algorithm_dir_name / build_relative_path Tests ───────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestRegistryUtils:
    """유틸 함수 테스트."""

    def test_algorithm_dir_tabular(self):
        assert algorithm_dir_name("tabular_q_learning") == "tabular"

    def test_algorithm_dir_dqn(self):
        assert algorithm_dir_name("dqn") == "dqn"

    def test_algorithm_dir_ppo(self):
        assert algorithm_dir_name("ppo") == "ppo"

    def test_algorithm_dir_a2c(self):
        assert algorithm_dir_name("a2c") == "a2c"

    def test_algorithm_dir_unknown(self):
        assert algorithm_dir_name("unknown_algo") == "unknown"

    def test_build_relative_path(self):
        path = build_relative_path("dqn", "005930.KS", "policy_001")
        assert "dqn" in path
        assert "005930.KS" in path
        assert "policy_001" in path


# ── _load_artifact_from_entry Tests ──────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestLoadArtifactFromEntry:
    """파일에서 아티팩트 로딩 테스트."""

    def test_load_success(self, tmp_path):
        artifact = _make_artifact()
        payload = artifact.to_dict()

        models_dir = tmp_path / "models"
        file_rel = "tabular/005930.KS/test_policy.json"
        file_path = models_dir / file_rel
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

        store = RLPolicyStoreV2(models_dir=models_dir)
        entry = _make_policy_entry(file_path=file_rel)
        loaded = store._load_artifact_from_entry(entry)

        assert loaded is not None
        assert loaded.policy_id == "test_policy"

    def test_load_missing_file_returns_none(self, tmp_path):
        store = RLPolicyStoreV2(models_dir=tmp_path / "models")
        entry = _make_policy_entry(file_path="nonexistent/path.json")
        loaded = store._load_artifact_from_entry(entry)
        assert loaded is None

    def test_load_malformed_json_returns_none(self, tmp_path):
        models_dir = tmp_path / "models"
        file_rel = "tabular/005930.KS/bad.json"
        file_path = models_dir / file_rel
        file_path.parent.mkdir(parents=True)
        file_path.write_text("{ invalid json !!!")

        store = RLPolicyStoreV2(models_dir=models_dir)
        entry = _make_policy_entry(file_path=file_rel)
        loaded = store._load_artifact_from_entry(entry)
        assert loaded is None

    def test_load_sb3_artifact_with_model_path(self, tmp_path):
        """SB3 아티팩트: model_path 존재, q_table 없음."""
        artifact = _make_artifact(
            algorithm="dqn",
            model_path="/tmp/dqn_model.zip",
        )
        payload = artifact.to_dict()

        models_dir = tmp_path / "models"
        file_rel = "dqn/005930.KS/test_policy.json"
        file_path = models_dir / file_rel
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

        store = RLPolicyStoreV2(models_dir=models_dir)
        entry = _make_policy_entry(file_path=file_rel)
        loaded = store._load_artifact_from_entry(entry)

        assert loaded is not None
        assert loaded.model_path == "/tmp/dqn_model.zip"
        assert loaded.q_table is None


# ── _delete_policy_file_by_path Tests ────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestDeletePolicyFile:
    """정책 파일 삭제 테스트."""

    def test_delete_existing_file(self, tmp_path):
        models_dir = tmp_path / "models"
        file_rel = "tabular/TEST/policy.json"
        file_path = models_dir / file_rel
        file_path.parent.mkdir(parents=True)
        file_path.write_text("{}")

        store = RLPolicyStoreV2(models_dir=models_dir)
        store._delete_policy_file_by_path(file_rel)
        assert not file_path.exists()

    def test_delete_nonexistent_file_no_error(self, tmp_path):
        store = RLPolicyStoreV2(models_dir=tmp_path / "models")
        store._delete_policy_file_by_path("nonexistent.json")


# ── save_policy File I/O Tests ───────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestSavePolicyFileIO:
    """save_policy 파일 I/O 부분 테스트 (DB 부분은 mock)."""

    @pytest.mark.asyncio
    async def test_save_creates_json_file(self, tmp_path):
        models_dir = tmp_path / "models"
        store = RLPolicyStoreV2(models_dir=models_dir)
        artifact = _make_artifact()

        with patch("src.agents.rl_policy_store_v2.execute", new_callable=AsyncMock):
            saved = await store.save_policy(artifact)

        # JSON 파일이 생성되어야 함
        file_path = Path(saved.artifact_path)
        assert file_path.exists()
        payload = json.loads(file_path.read_text())
        assert payload["policy_id"] == "test_policy"

    @pytest.mark.asyncio
    async def test_save_creates_directory_structure(self, tmp_path):
        models_dir = tmp_path / "models"
        store = RLPolicyStoreV2(models_dir=models_dir)
        artifact = _make_artifact(algorithm="dqn", ticker="000660.KS")

        with patch("src.agents.rl_policy_store_v2.execute", new_callable=AsyncMock):
            await store.save_policy(artifact)

        # dqn/000660.KS/ 디렉토리가 생성되어야 함
        expected_dir = models_dir / "dqn" / "000660.KS"
        assert expected_dir.exists()

    @pytest.mark.asyncio
    async def test_save_normalizes_ticker(self, tmp_path):
        store = RLPolicyStoreV2(models_dir=tmp_path / "models")
        artifact = _make_artifact(ticker="005930")  # raw ticker

        with patch("src.agents.rl_policy_store_v2.execute", new_callable=AsyncMock):
            saved = await store.save_policy(artifact)

        # normalize 적용 확인 (005930 → 005930.KS)
        assert saved.ticker == "005930.KS"

    @pytest.mark.asyncio
    async def test_save_foreign_key_error_logged_and_raised(self, tmp_path):
        store = RLPolicyStoreV2(models_dir=tmp_path / "models")
        artifact = _make_artifact()

        fk_error = Exception("ForeignKeyViolation: insert or update violates")
        with patch("src.agents.rl_policy_store_v2.execute", new_callable=AsyncMock, side_effect=fk_error):
            with pytest.raises(Exception, match="ForeignKeyViolation"):
                await store.save_policy(artifact)


# ── activate_policy Gate Tests ───────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestActivatePolicyGates:
    """activate_policy 승격 게이트 테스트."""

    @pytest.mark.asyncio
    async def test_gate_not_approved_rejects(self, tmp_path):
        store = RLPolicyStoreV2(models_dir=tmp_path)
        artifact = _make_artifact(approved=False)

        # 후보가 DB에 존재하지만 미승인
        mock_row = {
            "policy_id": "test_policy",
            "instrument_id": "005930.KS",
            "algorithm": "tabular_q_learning",
            "state_version": "v2",
            "return_pct": 10.0,
            "baseline_return_pct": 5.0,
            "excess_return_pct": 5.0,
            "max_drawdown_pct": -10.0,
            "trades": 20,
            "win_rate": 0.6,
            "holdout_steps": 40,
            "approved": False,
            "is_active": False,
            "created_at": datetime.now(timezone.utc),
            "file_path": "tabular/005930.KS/test.json",
            "hyperparams": None,
        }
        with patch("src.agents.rl_policy_store_v2.fetchrow", new_callable=AsyncMock, return_value=mock_row):
            result = await store.activate_policy(artifact)
        assert result is False

    @pytest.mark.asyncio
    async def test_gate_bad_drawdown_rejects(self, tmp_path):
        store = RLPolicyStoreV2(models_dir=tmp_path)
        artifact = _make_artifact(drawdown=-60.0)

        mock_row = {
            "policy_id": "test_policy",
            "instrument_id": "005930.KS",
            "algorithm": "tabular_q_learning",
            "state_version": "v2",
            "return_pct": 10.0,
            "baseline_return_pct": 5.0,
            "excess_return_pct": 5.0,
            "max_drawdown_pct": -60.0,  # < DEFAULT_MAX_DRAWDOWN_LIMIT_PCT (-50)
            "trades": 20,
            "win_rate": 0.6,
            "holdout_steps": 40,
            "approved": True,
            "is_active": False,
            "created_at": datetime.now(timezone.utc),
            "file_path": "tabular/005930.KS/test.json",
            "hyperparams": None,
        }
        with patch("src.agents.rl_policy_store_v2.fetchrow", new_callable=AsyncMock, return_value=mock_row):
            result = await store.activate_policy(artifact)
        assert result is False

    @pytest.mark.asyncio
    async def test_gate_candidate_not_in_db_rejects(self, tmp_path):
        store = RLPolicyStoreV2(models_dir=tmp_path)
        artifact = _make_artifact()

        with patch("src.agents.rl_policy_store_v2.fetchrow", new_callable=AsyncMock, return_value=None):
            result = await store.activate_policy(artifact)
        assert result is False

    @pytest.mark.asyncio
    async def test_gate_worse_than_active_rejects(self, tmp_path):
        store = RLPolicyStoreV2(models_dir=tmp_path)
        artifact = _make_artifact(total_return=8.0)

        candidate_row = {
            "policy_id": "test_policy",
            "instrument_id": "005930.KS",
            "algorithm": "tabular_q_learning",
            "state_version": "v2",
            "return_pct": 8.0,
            "baseline_return_pct": 5.0,
            "excess_return_pct": 3.0,
            "max_drawdown_pct": -10.0,
            "trades": 20,
            "win_rate": 0.6,
            "holdout_steps": 40,
            "approved": True,
            "is_active": False,
            "created_at": datetime.now(timezone.utc),
            "file_path": "tabular/005930.KS/test.json",
            "hyperparams": None,
        }
        active_row = dict(candidate_row)
        active_row["return_pct"] = 12.0  # 현재 활성이 더 좋음
        active_row["is_active"] = True

        with patch(
            "src.agents.rl_policy_store_v2.fetchrow",
            new_callable=AsyncMock,
            side_effect=[candidate_row, active_row],
        ):
            result = await store.activate_policy(artifact)
        assert result is False

    @pytest.mark.asyncio
    async def test_gate_better_than_active_accepts(self, tmp_path):
        store = RLPolicyStoreV2(models_dir=tmp_path)
        artifact = _make_artifact(total_return=15.0)

        candidate_row = {
            "policy_id": "test_policy",
            "instrument_id": "005930.KS",
            "algorithm": "tabular_q_learning",
            "state_version": "v2",
            "return_pct": 15.0,
            "baseline_return_pct": 5.0,
            "excess_return_pct": 10.0,
            "max_drawdown_pct": -10.0,
            "trades": 20,
            "win_rate": 0.6,
            "holdout_steps": 40,
            "approved": True,
            "is_active": False,
            "created_at": datetime.now(timezone.utc),
            "file_path": "tabular/005930.KS/test.json",
            "hyperparams": None,
        }
        active_row = dict(candidate_row)
        active_row["return_pct"] = 10.0
        active_row["is_active"] = True

        with patch(
            "src.agents.rl_policy_store_v2.fetchrow",
            new_callable=AsyncMock,
            side_effect=[candidate_row, active_row],
        ):
            with patch.object(store, "_swap_active", new_callable=AsyncMock):
                result = await store.activate_policy(artifact)
        assert result is True

    @pytest.mark.asyncio
    async def test_gate_no_active_policy_accepts(self, tmp_path):
        store = RLPolicyStoreV2(models_dir=tmp_path)
        artifact = _make_artifact(total_return=10.0)

        candidate_row = {
            "policy_id": "test_policy",
            "instrument_id": "005930.KS",
            "algorithm": "tabular_q_learning",
            "state_version": "v2",
            "return_pct": 10.0,
            "baseline_return_pct": 5.0,
            "excess_return_pct": 5.0,
            "max_drawdown_pct": -10.0,
            "trades": 20,
            "win_rate": 0.6,
            "holdout_steps": 40,
            "approved": True,
            "is_active": False,
            "created_at": datetime.now(timezone.utc),
            "file_path": "tabular/005930.KS/test.json",
            "hyperparams": None,
        }

        with patch(
            "src.agents.rl_policy_store_v2.fetchrow",
            new_callable=AsyncMock,
            side_effect=[candidate_row, None],  # 현재 활성 없음
        ):
            with patch.object(store, "_swap_active", new_callable=AsyncMock):
                result = await store.activate_policy(artifact)
        assert result is True


# ── force_activate_policy Tests ──────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestForceActivatePolicy:
    """force_activate_policy 테스트."""

    @pytest.mark.asyncio
    async def test_force_activate_success(self, tmp_path):
        store = RLPolicyStoreV2(models_dir=tmp_path)
        with patch(
            "src.agents.rl_policy_store_v2.fetchrow",
            new_callable=AsyncMock,
            return_value={"exists": True},
        ):
            with patch.object(store, "_swap_active", new_callable=AsyncMock):
                result = await store.force_activate_policy("005930.KS", "policy_x")
        assert result is True

    @pytest.mark.asyncio
    async def test_force_activate_not_found(self, tmp_path):
        store = RLPolicyStoreV2(models_dir=tmp_path)
        with patch(
            "src.agents.rl_policy_store_v2.fetchrow",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await store.force_activate_policy("005930.KS", "nonexistent")
        assert result is False


# ── PolicyEntry Tests ────────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestPolicyEntry:
    """PolicyEntry DTO 테스트."""

    def test_from_db_row(self):
        row = {
            "policy_id": "p1",
            "instrument_id": "005930.KS",
            "algorithm": "dqn",
            "state_version": "sb3_dqn",
            "return_pct": 12.5,
            "baseline_return_pct": 5.0,
            "excess_return_pct": 7.5,
            "max_drawdown_pct": -8.0,
            "trades": 30,
            "win_rate": 0.65,
            "holdout_steps": 50,
            "approved": True,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
            "file_path": "dqn/005930.KS/p1.json",
            "hyperparams": {"lookback": 20, "learning_rate": 0.0005},
        }
        entry = PolicyEntry.from_db_row(row)
        assert entry.policy_id == "p1"
        assert entry.algorithm == "dqn"
        assert entry.lookback == 20
        assert entry.learning_rate == 0.0005

    def test_from_db_row_string_hyperparams(self):
        row = {
            "policy_id": "p2",
            "instrument_id": "000660.KS",
            "algorithm": "ppo",
            "state_version": "sb3_ppo",
            "return_pct": 8.0,
            "baseline_return_pct": 3.0,
            "excess_return_pct": 5.0,
            "max_drawdown_pct": -12.0,
            "trades": 15,
            "win_rate": 0.55,
            "holdout_steps": 30,
            "approved": True,
            "is_active": False,
            "created_at": datetime.now(timezone.utc),
            "file_path": "ppo/000660.KS/p2.json",
            "hyperparams": '{"lookback": 20}',  # JSON 문자열
        }
        entry = PolicyEntry.from_db_row(row)
        assert entry.lookback == 20

    def test_ticker_alias(self):
        entry = _make_policy_entry(ticker="005930.KS")
        assert entry.ticker == "005930.KS"
        assert entry.instrument_id == "005930.KS"

    def test_default_hyperparams(self):
        _make_policy_entry()
        # hyperparams=None이면 기본값 사용
        entry_no_hp = PolicyEntry(
            policy_id="x",
            instrument_id="Y",
            created_at=datetime.now(timezone.utc),
            file_path="x.json",
        )
        assert entry_no_hp.lookback == 6
        assert entry_no_hp.epsilon == 0.15
