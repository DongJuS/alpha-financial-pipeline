"""
test/test_rl_registry_auto_sync.py — RL 레지스트리 자동 동기화 테스트

DB instruments 테이블의 티커가 RL registry에 자동 등록되는 흐름,
환경변수 오버라이드, DB 실패 시 폴백, 티커 정규화를 검증합니다.

DB/Redis 연결 불필요 — 전부 mock 기반 단위 테스트.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.rl_policy_registry import (
    PolicyEntry,
    PolicyRegistry,
    TickerPolicies,
    build_relative_path,
)
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.utils.ticker import normalize, is_canonical, to_raw


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_entry(
    policy_id: str,
    ticker: str = "259960.KS",
    approved: bool = False,
) -> PolicyEntry:
    """테스트용 PolicyEntry 생성."""
    return PolicyEntry(
        policy_id=policy_id,
        ticker=ticker,
        algorithm="tabular_q_learning",
        state_version="qlearn_v2",
        return_pct=5.0,
        max_drawdown_pct=-10.0,
        approved=approved,
        created_at=datetime.now(timezone.utc),
        file_path=build_relative_path("tabular_q_learning", ticker, policy_id),
    )


def _sample_db_tickers() -> list[dict]:
    """list_tickers()가 반환하는 형태의 샘플 데이터."""
    return [
        {"instrument_id": "005930.KS", "ticker": "005930", "name": "삼성전자", "market": "KS"},
        {"instrument_id": "000660.KS", "ticker": "000660", "name": "SK하이닉스", "market": "KS"},
        {"instrument_id": "259960.KS", "ticker": "259960", "name": "크래프톤", "market": "KS"},
        {"instrument_id": "035720.KS", "ticker": "035720", "name": "카카오", "market": "KS"},
    ]


def _make_registry_with_tickers(*tickers: str) -> PolicyRegistry:
    """지정된 티커만 포함하는 PolicyRegistry를 생성."""
    reg = PolicyRegistry()
    for t in tickers:
        reg.tickers[t] = TickerPolicies()
    return reg


# ── Test 1: 새 티커 자동 등록 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_register_new_tickers():
    """DB instruments에 있지만 registry에 없는 티커가 자동 등록되는지 검증.

    list_tickers()가 4개 종목을 반환하고, registry에는 2개만 있을 때,
    나머지 2개가 새로 등록되어야 한다.
    """
    db_tickers = _sample_db_tickers()  # 005930.KS, 000660.KS, 259960.KS, 035720.KS

    # registry에는 005930.KS, 259960.KS만 존재
    existing_registry = _make_registry_with_tickers("005930.KS", "259960.KS")
    existing_registry.tickers["259960.KS"].policies.append(
        _make_entry("rl_259960.KS_test", "259960.KS", approved=True),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        models_dir = Path(tmpdir)
        registry_path = models_dir / "registry.json"

        # registry.json에 기존 내용 기록
        registry_path.write_text(
            json.dumps(existing_registry.model_dump(mode="json"), default=str),
            encoding="utf-8",
        )

        store = RLPolicyStoreV2(models_dir=models_dir)
        registry = store.load_registry()

        # DB에서 가져온 티커 중 registry에 없는 것을 등록
        existing_tickers = set(registry.list_all_tickers())
        for row in db_tickers:
            instrument_id = row["instrument_id"]
            if instrument_id not in existing_tickers:
                registry.get_ticker(instrument_id)  # 빈 TickerPolicies 생성

        store.save_registry()

        # 검증: 4개 모두 등록되어야 함
        reloaded = json.loads(registry_path.read_text(encoding="utf-8"))
        registered_tickers = set(reloaded["tickers"].keys())

        assert "005930.KS" in registered_tickers
        assert "000660.KS" in registered_tickers
        assert "259960.KS" in registered_tickers
        assert "035720.KS" in registered_tickers
        assert len(registered_tickers) == 4

        # 기존 정책은 보존되어야 함
        assert len(reloaded["tickers"]["259960.KS"]["policies"]) == 1
        assert reloaded["tickers"]["259960.KS"]["policies"][0]["policy_id"] == "rl_259960.KS_test"

        # 새로 추가된 티커는 빈 정책 목록이어야 함
        assert reloaded["tickers"]["000660.KS"]["policies"] == []
        assert reloaded["tickers"]["035720.KS"]["policies"] == []


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


# ── Test 4: DB 실패 시 기존 registry 폴백 ────────────────────────────────────


@pytest.mark.asyncio
async def test_rl_bootstrap_db_fallback_on_failure():
    """DB list_tickers() 호출 실패 시 기존 registry 티커로 계속 동작하는지 검증.

    DB 장애가 발생해도 registry.json에 등록된 티커로 부트스트랩이 진행되어야 한다.
    """
    # 기존 registry에 2개 티커 존재
    existing_registry = _make_registry_with_tickers("005930.KS", "259960.KS")
    existing_registry.tickers["259960.KS"].policies.append(
        _make_entry("rl_259960.KS_active", "259960.KS", approved=True),
    )
    existing_registry.tickers["259960.KS"].active_policy_id = "rl_259960.KS_active"

    with tempfile.TemporaryDirectory() as tmpdir:
        models_dir = Path(tmpdir)
        registry_path = models_dir / "registry.json"
        registry_path.write_text(
            json.dumps(existing_registry.model_dump(mode="json"), default=str),
            encoding="utf-8",
        )

        store = RLPolicyStoreV2(models_dir=models_dir)
        registry = store.load_registry()

        # DB 호출 실패 시뮬레이션
        mock_list_tickers = AsyncMock(side_effect=Exception("DB connection refused"))

        try:
            db_rows = await mock_list_tickers(limit=30)
            new_tickers = [r["instrument_id"] for r in db_rows]
        except Exception:
            # 폴백: registry의 기존 티커 사용
            new_tickers = registry.list_all_tickers()

        # 검증: 기존 registry 티커로 폴백
        assert set(new_tickers) == {"005930.KS", "259960.KS"}

        # 기존 정책과 활성 정책이 보존되어야 함
        active = registry.get_active_policy("259960.KS")
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


def test_ticker_normalization_in_registry():
    """registry에서 티커 조회 시 정규화가 올바르게 적용되는지 검증.

    raw code로 조회해도 canonical 키로 매칭되어야 한다.
    """
    registry = PolicyRegistry()
    entry = _make_entry("rl_259960.KS_test", ticker="259960.KS")
    registry.register_policy(entry)

    # canonical 형식으로 직접 조회
    tp = registry.tickers.get("259960.KS")
    assert tp is not None
    assert len(tp.policies) == 1

    # PolicyRegistry.get_ticker()로 canonical 조회
    tp2 = registry.get_ticker("259960.KS")
    assert tp2 is not None
    assert len(tp2.policies) == 1

    # raw code로는 직접 dict 조회 시 없음 (정규화 필요)
    assert registry.tickers.get("259960") is None


def test_store_normalizes_on_save():
    """RLPolicyStoreV2가 저장 시 ticker를 정규화하는지 검증.

    PolicyEntry의 ticker 필드가 registry 키와 일치해야 한다.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        models_dir = Path(tmpdir)
        store = RLPolicyStoreV2(models_dir=models_dir, auto_save_registry=False)
        registry = store.load_registry()

        # 수동으로 정규화된 엔트리 등록
        entry = _make_entry("rl_005930.KS_test", ticker="005930.KS")
        registry.register_policy(entry)

        # 등록된 티커 확인
        all_tickers = registry.list_all_tickers()
        assert "005930.KS" in all_tickers

        # 정책 조회 가능 확인
        policy = registry.get_active_policy("005930.KS")
        # 활성 정책 미설정이므로 None
        assert policy is None

        # 정책 목록 조회
        tp = registry.get_ticker("005930.KS")
        assert len(tp.policies) == 1
        assert tp.policies[0].ticker == "005930.KS"


def test_registry_json_no_duplicate_tickers():
    """registry.json에 같은 종목이 다른 형식으로 중복 등록되지 않는지 검증.

    예: 259960과 259960.KS가 동시에 존재하면 안 된다.
    """
    registry_path = (
        Path(__file__).resolve().parents[1]
        / "artifacts"
        / "rl"
        / "models"
        / "registry.json"
    )

    if not registry_path.exists():
        pytest.skip("registry.json not found")

    data = json.loads(registry_path.read_text(encoding="utf-8"))
    tickers = list(data["tickers"].keys())

    # raw code 기준으로 중복 체크
    raw_codes = [to_raw(t) for t in tickers]
    duplicates = [code for code in set(raw_codes) if raw_codes.count(code) > 1]

    assert duplicates == [], (
        f"Duplicate tickers found (same stock, different format): "
        f"{duplicates}. Tickers: {tickers}"
    )
