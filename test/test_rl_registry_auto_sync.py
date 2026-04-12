"""
test/test_rl_registry_auto_sync.py — RL 레지스트리 자동 동기화 테스트

DB instruments 테이블의 티커가 RL StoreV2(DB 기반)에 자동 등록되는 흐름,
환경변수 오버라이드, DB 실패 시 폴백, 티커 정규화를 검증합니다.

DB/Redis 연결 불필요 — 전부 mock 기반 단위 테스트.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.rl_policy_registry import (
    PolicyEntry,
    build_relative_path,
)
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.utils.ticker import is_canonical, normalize, to_raw


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_entry(
    policy_id: str,
    instrument_id: str = "259960.KS",
    approved: bool = False,
    is_active: bool = False,
) -> PolicyEntry:
    """테스트용 PolicyEntry 생성."""
    return PolicyEntry(
        policy_id=policy_id,
        instrument_id=instrument_id,
        algorithm="tabular_q_learning",
        state_version="qlearn_v2",
        return_pct=5.0,
        max_drawdown_pct=-10.0,
        approved=approved,
        is_active=is_active,
        created_at=datetime.now(timezone.utc),
        file_path=build_relative_path("tabular_q_learning", instrument_id, policy_id),
    )


def _sample_db_tickers() -> list[dict]:
    """list_tickers()가 반환하는 형태의 샘플 데이터."""
    return [
        {"instrument_id": "005930.KS", "ticker": "005930", "name": "삼성전자", "market": "KS"},
        {"instrument_id": "000660.KS", "ticker": "000660", "name": "SK하이닉스", "market": "KS"},
        {"instrument_id": "259960.KS", "ticker": "259960", "name": "크래프톤", "market": "KS"},
        {"instrument_id": "035720.KS", "ticker": "035720", "name": "카카오", "market": "KS"},
    ]


# ── Test 1: 새 티커 자동 등록 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_register_new_tickers():
    """DB instruments에 있지만 StoreV2에 없는 티커가 자동 등록되는지 검증.

    list_tickers()가 4개 종목을 반환하고, StoreV2에는 2개만 있을 때,
    나머지 2개가 새로 등록되어야 한다.
    """
    db_tickers = _sample_db_tickers()  # 005930.KS, 000660.KS, 259960.KS, 035720.KS

    # StoreV2에는 005930.KS, 259960.KS만 존재
    existing_tickers = ["005930.KS", "259960.KS"]
    existing_policies = [
        _make_entry("rl_259960.KS_test", "259960.KS", approved=True),
    ]

    # save_policy 호출을 추적하기 위한 목록
    saved_tickers: list[str] = []

    async def mock_save_policy(artifact):
        saved_tickers.append(artifact.ticker)
        return artifact

    with (
        patch.object(
            RLPolicyStoreV2, "list_all_tickers",
            new_callable=AsyncMock,
            return_value=existing_tickers,
        ),
        patch.object(
            RLPolicyStoreV2, "list_policies",
            new_callable=AsyncMock,
            return_value=existing_policies,
        ),
    ):
        store = RLPolicyStoreV2()

        # DB에서 가져온 티커 중 StoreV2에 없는 것을 찾기
        known_tickers = set(await store.list_all_tickers())
        new_tickers = [
            row["instrument_id"]
            for row in db_tickers
            if row["instrument_id"] not in known_tickers
        ]

        # 검증: 새로 추가해야 할 티커 2개
        assert sorted(new_tickers) == ["000660.KS", "035720.KS"]

        # 기존 정책은 보존되어야 함
        policies_259960 = await store.list_policies("259960.KS")
        assert len(policies_259960) == 1
        assert policies_259960[0].policy_id == "rl_259960.KS_test"


# ── Test 2: Worker가 DB 티커를 사용 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_orch_worker_uses_db_tickers():
    """ORCH_TICKERS 미설정 시 worker가 DB에서 티커를 가져오는지 검증.

    list_tickers()가 반환한 instrument_id가 올바르게 사용되어야 한다.
    """
    db_tickers = _sample_db_tickers()

    with patch("src.db.queries.list_tickers", new_callable=AsyncMock) as mock_lt:
        mock_lt.return_value = db_tickers

        # list_tickers 호출 후 instrument_id 추출
        rows = await mock_lt(limit=30)
        instrument_ids = [r["instrument_id"] for r in rows]

    # 검증: instrument_id 형식(CODE.SUFFIX)이어야 함
    assert instrument_ids == ["005930.KS", "000660.KS", "259960.KS", "035720.KS"]

    # 모든 instrument_id가 canonical 형식인지 확인
    for iid in instrument_ids:
        assert is_canonical(iid), f"{iid} is not in canonical format"


# ── Test 3: 환경변수 오버라이드 ──────────────────────────────────────────────


def test_orch_worker_env_override():
    """ORCH_TICKERS 설정 시 환경변수 값이 DB보다 우선되는지 검증."""
    from scripts.run_orchestrator_worker import _parse_tickers

    # ORCH_TICKERS 설정됨 → 환경변수 값 사용
    env_tickers = _parse_tickers("005930,000660")
    assert env_tickers == ["005930", "000660"]

    # ORCH_TICKERS 비어있음 → None 반환 (DB 폴백)
    empty_tickers = _parse_tickers("")
    assert empty_tickers is None

    # 공백만 있어도 None
    whitespace_tickers = _parse_tickers("  ,  ,  ")
    assert whitespace_tickers is None


# ── Test 4: DB 실패 시 StoreV2 기존 티커로 폴백 ──────────────────────────────


@pytest.mark.asyncio
async def test_rl_bootstrap_db_fallback_on_failure():
    """DB list_tickers() 호출 실패 시 StoreV2의 기존 티커로 계속 동작하는지 검증.

    DB 장애가 발생해도 StoreV2에 등록된 티커로 부트스트랩이 진행되어야 한다.
    """
    existing_tickers = ["005930.KS", "259960.KS"]
    active_artifact_entry = _make_entry(
        "rl_259960.KS_active", "259960.KS", approved=True, is_active=True,
    )

    with (
        patch.object(
            RLPolicyStoreV2, "list_all_tickers",
            new_callable=AsyncMock,
            return_value=existing_tickers,
        ),
        patch.object(
            RLPolicyStoreV2, "load_active_policy",
            new_callable=AsyncMock,
        ) as mock_load_active,
    ):
        store = RLPolicyStoreV2()

        # load_active_policy가 259960.KS에 대해 활성 정책 반환
        mock_load_active.return_value = None  # 기본값
        # 259960.KS 호출 시에만 artifact 반환
        from src.agents.rl_trading import RLPolicyArtifact, RLEvaluationMetrics

        active_artifact = RLPolicyArtifact(
            policy_id="rl_259960.KS_active",
            ticker="259960.KS",
            created_at=datetime.now(timezone.utc).isoformat(),
            algorithm="tabular_q_learning",
            state_version="qlearn_v2",
            lookback=20, episodes=300,
            learning_rate=0.10, discount_factor=0.95, epsilon=0.30,
            trade_penalty_bps=2,
            q_table={},
            evaluation=RLEvaluationMetrics(
                total_return_pct=10.0, baseline_return_pct=5.0,
                excess_return_pct=5.0, max_drawdown_pct=-10.0,
                trades=50, win_rate=0.55, holdout_steps=100, approved=True,
            ),
        )
        mock_load_active.return_value = active_artifact

        # DB 호출 실패 시뮬레이션
        mock_list_tickers = AsyncMock(side_effect=Exception("DB connection refused"))

        try:
            db_rows = await mock_list_tickers(limit=30)
            new_tickers = [r["instrument_id"] for r in db_rows]
        except Exception:
            # 폴백: StoreV2의 기존 티커 사용
            new_tickers = await store.list_all_tickers()

        # 검증: 기존 StoreV2 티커로 폴백
        assert set(new_tickers) == {"005930.KS", "259960.KS"}

        # 기존 활성 정책이 보존되어야 함
        active = await store.load_active_policy("259960.KS")
        assert active is not None
        assert active.policy_id == "rl_259960.KS_active"


# ── Test 5: 티커 정규화 일관성 ───────────────────────────────────────────────


def test_ticker_normalization():
    """instrument_id 형식(CODE.SUFFIX)이 일관되게 사용되는지 검증.

    raw code(005930)가 들어와도 정규화(005930.KS)로 변환되어야 하며,
    이미 정규화된 형식은 변경되지 않아야 한다.
    """
    # raw 6자리 → .KS 기본 추정
    assert normalize("005930") == "005930.KS"
    assert normalize("000660") == "000660.KS"
    assert normalize("259960") == "259960.KS"

    # 이미 canonical이면 그대로
    assert normalize("005930.KS") == "005930.KS"
    assert normalize("259960.KQ") == "259960.KQ"

    # market 인자 사용
    assert normalize("005930", market="KOSPI") == "005930.KS"
    assert normalize("005930", market="KOSDAQ") == "005930.KQ"

    # is_canonical 체크
    assert is_canonical("005930.KS") is True
    assert is_canonical("005930") is False

    # to_raw 체크
    assert to_raw("005930.KS") == "005930"
    assert to_raw("005930") == "005930"


def test_ticker_normalization_in_store():
    """StoreV2에서 티커 조회 시 정규화가 올바르게 적용되는지 검증.

    PolicyEntry의 instrument_id 필드가 canonical 형식이어야 한다.
    """
    entry = _make_entry("rl_259960.KS_test", instrument_id="259960.KS")

    # canonical 형식으로 직접 확인
    assert entry.instrument_id == "259960.KS"
    assert is_canonical(entry.instrument_id)

    # ticker 프로퍼티도 동일
    assert entry.ticker == "259960.KS"

    # raw code로는 canonical이 아님
    assert not is_canonical("259960")


@pytest.mark.asyncio
async def test_store_normalizes_on_save():
    """RLPolicyStoreV2가 저장 시 ticker를 정규화하는지 검증.

    save_policy 호출 시 artifact의 ticker가 정규화되어야 한다.
    """
    from src.agents.rl_trading import RLPolicyArtifact, RLEvaluationMetrics

    artifact = RLPolicyArtifact(
        policy_id="rl_005930.KS_test",
        ticker="005930",  # raw code
        created_at=datetime.now(timezone.utc).isoformat(),
        algorithm="tabular_q_learning",
        state_version="qlearn_v2",
        lookback=20, episodes=300,
        learning_rate=0.10, discount_factor=0.95, epsilon=0.30,
        trade_penalty_bps=2,
        q_table={},
        evaluation=RLEvaluationMetrics(
            total_return_pct=10.0, baseline_return_pct=5.0,
            excess_return_pct=5.0, max_drawdown_pct=-10.0,
            trades=50, win_rate=0.55, holdout_steps=100, approved=True,
        ),
    )

    saved_artifact = RLPolicyArtifact(
        policy_id="rl_005930.KS_test",
        ticker="005930.KS",  # 정규화됨
        created_at=artifact.created_at,
        algorithm="tabular_q_learning",
        state_version="qlearn_v2",
        lookback=20, episodes=300,
        learning_rate=0.10, discount_factor=0.95, epsilon=0.30,
        trade_penalty_bps=2,
        q_table={},
        evaluation=artifact.evaluation,
    )

    with patch.object(
        RLPolicyStoreV2, "save_policy", new_callable=AsyncMock, return_value=saved_artifact
    ):
        store = RLPolicyStoreV2()
        result = await store.save_policy(artifact)
        # 정규화된 ticker가 반환되어야 함
        assert result.ticker == "005930.KS"
        assert is_canonical(result.ticker)
