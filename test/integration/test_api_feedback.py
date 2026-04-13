"""
test/integration/test_api_feedback.py — Feedback API 통합 테스트

FastAPI TestClient로 feedback 라우터를 격리 테스트한다.
DB/Redis 없이 mock으로 동작.

테스트 대상:
  - GET  /api/v1/feedback/accuracy         — 정확도 통계
  - GET  /api/v1/feedback/llm-context/{s}  — LLM 피드백 컨텍스트
  - POST /api/v1/feedback/backtest         — 백테스트 실행
  - POST /api/v1/feedback/backtest/compare — 전략 비교
  - POST /api/v1/feedback/rl/retrain/{t}   — 단일 종목 RL 재학습
  - POST /api/v1/feedback/rl/retrain-all   — 전체 RL 재학습
  - POST /api/v1/feedback/cycle            — 피드백 사이클 실행
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.routers.feedback as feedback_module
from src.agents.rl_continuous_improver import RetrainOutcome
from src.api.routers.feedback import router as feedback_router

API_PREFIX = "/api/v1/feedback"


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(feedback_router, prefix=API_PREFIX)
    return TestClient(app, raise_server_exceptions=False)


def _make_outcome(
    *,
    ticker: str = "005930.KS",
    success: bool = True,
) -> RetrainOutcome:
    return RetrainOutcome(
        ticker=ticker,
        success=success,
        new_policy_id=f"rl_{ticker}_test" if success else None,
        excess_return=12.3 if success else None,
        walk_forward_passed=success,
        deployed=success,
        selected_train_ratio=0.6 if success else None,
        bandit_snapshot={"ticker": ticker, "best_ratio": 0.6} if success else None,
    )


# ── GET /accuracy ───────────────────────────────────────────────────────


class TestAccuracyEndpoint:
    """GET /api/v1/feedback/accuracy"""

    def test_accuracy_returns_empty_stats_without_db(self) -> None:
        """DB 미연결 시 빈 통계를 반환한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/accuracy")
        assert resp.status_code == 200

        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 2  # strategy_a, strategy_b
        for stat in body:
            assert stat["total_predictions"] == 0
            assert stat["accuracy"] == 0.0
            assert "strategy" in stat
            assert "period_start" in stat
            assert "period_end" in stat

    def test_accuracy_with_strategy_filter(self) -> None:
        """strategy 필터를 적용하면 해당 전략만 반환한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/accuracy?strategy=strategy_a")
        assert resp.status_code == 200

        body = resp.json()
        assert len(body) == 1
        assert body[0]["strategy"] == "strategy_a"

    def test_accuracy_with_days_parameter(self) -> None:
        """days 파라미터를 전달할 수 있다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/accuracy?days=7")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_accuracy_days_validation_min(self) -> None:
        """days 파라미터가 1보다 작으면 422를 반환한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/accuracy?days=0")
        assert resp.status_code == 422

    def test_accuracy_days_validation_max(self) -> None:
        """days 파라미터가 365를 초과하면 422를 반환한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/accuracy?days=999")
        assert resp.status_code == 422

    @patch("src.utils.db_client.fetch", new_callable=AsyncMock)
    def test_accuracy_with_db_data(self, mock_fetch: AsyncMock) -> None:
        """DB에 데이터가 있으면 정확도를 계산한다."""
        mock_fetch.return_value = [
            {"total": 80, "correct": 48, "signal": "buy"},
            {"total": 20, "correct": 12, "signal": "sell"},
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/accuracy?strategy=strategy_a")
        assert resp.status_code == 200

        body = resp.json()
        assert len(body) == 1
        assert body[0]["total_predictions"] == 100
        assert body[0]["correct_predictions"] == 60
        assert body[0]["accuracy"] == 0.6
        assert body[0]["signal_distribution"] == {"buy": 80, "sell": 20}


# ── GET /llm-context/{strategy} ────────────────────────────────────────


class TestLLMContextEndpoint:
    """GET /api/v1/feedback/llm-context/{strategy}"""

    def test_llm_context_returns_default_without_cache(self) -> None:
        """Redis 미연결 시 기본 컨텍스트를 반환한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/llm-context/strategy_a")
        assert resp.status_code == 200

        body = resp.json()
        assert body["strategy"] == "strategy_a"
        assert body["cached"] is False
        assert body["error_patterns"] == []
        assert "generated_at" in body

    def test_llm_context_any_strategy_name_is_accepted(self) -> None:
        """임의의 전략 이름도 받아들인다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/llm-context/custom_strategy")
        assert resp.status_code == 200
        assert resp.json()["strategy"] == "custom_strategy"


# ── POST /backtest ──────────────────────────────────────────────────────


class TestBacktestEndpoint:
    """POST /api/v1/feedback/backtest"""

    def test_backtest_returns_stub_result(self) -> None:
        """백테스트 요청이 stub 결과를 반환한다."""
        client = _build_client()
        resp = client.post(
            f"{API_PREFIX}/backtest",
            json={"strategy": "strategy_a"},
        )
        assert resp.status_code == 200

        body = resp.json()
        assert body["strategy"] == "strategy_a"
        assert body["initial_capital"] == 10_000_000
        assert body["total_return"] == 0.0
        assert body["total_trades"] == 0

    def test_backtest_with_custom_capital(self) -> None:
        """초기 자본을 커스텀으로 설정할 수 있다."""
        client = _build_client()
        resp = client.post(
            f"{API_PREFIX}/backtest",
            json={"strategy": "strategy_b", "initial_capital": 5_000_000},
        )
        assert resp.status_code == 200
        assert resp.json()["initial_capital"] == 5_000_000

    def test_backtest_with_date_range(self) -> None:
        """날짜 범위를 지정할 수 있다."""
        client = _build_client()
        resp = client.post(
            f"{API_PREFIX}/backtest",
            json={
                "strategy": "strategy_a",
                "start_date": "2025-01-01",
                "end_date": "2025-06-30",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["period"]["start"] == "2025-01-01"
        assert body["period"]["end"] == "2025-06-30"

    def test_backtest_invalid_capital_returns_422(self) -> None:
        """initial_capital이 0 이하이면 422를 반환한다."""
        client = _build_client()
        resp = client.post(
            f"{API_PREFIX}/backtest",
            json={"strategy": "strategy_a", "initial_capital": -100},
        )
        assert resp.status_code == 422

    def test_backtest_missing_strategy_returns_422(self) -> None:
        """strategy 필드가 없으면 422를 반환한다."""
        client = _build_client()
        resp = client.post(f"{API_PREFIX}/backtest", json={})
        assert resp.status_code == 422


# ── POST /backtest/compare ──────────────────────────────────────────────


class TestBacktestCompareEndpoint:
    """POST /api/v1/feedback/backtest/compare"""

    def test_compare_default_strategies(self) -> None:
        """기본 전략(strategy_a, strategy_b) 비교를 반환한다."""
        client = _build_client()
        resp = client.post(f"{API_PREFIX}/backtest/compare")
        assert resp.status_code == 200

        body = resp.json()
        assert len(body["strategies"]) == 2
        assert body["best_strategy"] == "strategy_a"
        assert len(body["ranking"]) == 2

    def test_compare_custom_strategies(self) -> None:
        """커스텀 전략 목록으로 비교할 수 있다."""
        client = _build_client()
        resp = client.post(
            f"{API_PREFIX}/backtest/compare",
            json={"strategies": ["strategy_a", "strategy_b", "rl"]},
        )
        assert resp.status_code == 200

        body = resp.json()
        assert len(body["strategies"]) == 3
        assert body["ranking"][0]["rank"] == 1
        assert body["ranking"][2]["rank"] == 3


# ── POST /rl/retrain/{ticker} ──────────────────────────────────────────


class TestRLRetrainEndpoint:
    """POST /api/v1/feedback/rl/retrain/{ticker}"""

    def test_retrain_single_ticker_success(self) -> None:
        """단일 종목 재학습이 성공 결과를 반환한다."""
        outcome = _make_outcome()
        improver = AsyncMock()
        improver.retrain_ticker = AsyncMock(return_value=outcome)

        with patch.object(feedback_module, "_get_rl_improver", return_value=improver):
            client = _build_client()
            resp = client.post(f"{API_PREFIX}/rl/retrain/005930")

        assert resp.status_code == 200
        body = resp.json()
        assert body["ticker"] == "005930.KS"
        assert body["success"] is True
        assert body["deployed"] is True

    def test_retrain_single_ticker_failure(self) -> None:
        """재학습 실패 시 에러 정보를 포함한 결과를 반환한다."""
        outcome = _make_outcome(success=False)
        outcome.error = "insufficient data"
        improver = AsyncMock()
        improver.retrain_ticker = AsyncMock(return_value=outcome)

        with patch.object(feedback_module, "_get_rl_improver", return_value=improver):
            client = _build_client()
            resp = client.post(f"{API_PREFIX}/rl/retrain/999999")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["deployed"] is False


# ── POST /rl/retrain-all ────────────────────────────────────────────────


class TestRLRetrainAllEndpoint:
    """POST /api/v1/feedback/rl/retrain-all"""

    def test_retrain_all_returns_batch_response(self) -> None:
        """전체 재학습이 배치 응답을 반환한다."""
        outcomes = [
            _make_outcome(ticker="005930.KS"),
            _make_outcome(ticker="000660.KS", success=False),
        ]
        improver = AsyncMock()
        improver.retrain_all = AsyncMock(return_value=outcomes)

        with patch.object(feedback_module, "_get_rl_improver", return_value=improver):
            client = _build_client()
            resp = client.post(f"{API_PREFIX}/rl/retrain-all")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_tickers"] == 2
        assert body["successful"] == 1
        assert body["failed"] == 1


# ── POST /cycle ─────────────────────────────────────────────────────────


class TestFeedbackCycleEndpoint:
    """POST /api/v1/feedback/cycle"""

    def test_cycle_llm_only_scope(self) -> None:
        """llm_only 스코프에서는 rl_retrain이 None이다."""
        client = _build_client()
        resp = client.post(
            f"{API_PREFIX}/cycle",
            json={"scope": "llm_only"},
        )
        assert resp.status_code == 200

        body = resp.json()
        assert body["scope"] == "llm_only"
        assert body["llm_feedback"] is not None
        assert body["rl_retrain"] is None
        assert body["backtest"] is None

    def test_cycle_backtest_only_scope(self) -> None:
        """backtest_only 스코프에서는 llm_feedback과 rl_retrain이 None이다."""
        client = _build_client()
        resp = client.post(
            f"{API_PREFIX}/cycle",
            json={"scope": "backtest_only"},
        )
        assert resp.status_code == 200

        body = resp.json()
        assert body["scope"] == "backtest_only"
        assert body["llm_feedback"] is None
        assert body["rl_retrain"] is None
        assert body["backtest"] is not None

    def test_cycle_has_duration_seconds(self) -> None:
        """사이클 응답에 duration_seconds가 포함된다."""
        client = _build_client()
        resp = client.post(
            f"{API_PREFIX}/cycle",
            json={"scope": "llm_only"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "duration_seconds" in body
        assert isinstance(body["duration_seconds"], float)
        assert body["duration_seconds"] >= 0
