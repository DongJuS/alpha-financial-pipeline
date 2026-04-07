"""/feedback 라우터의 RL 경로 단위 테스트.

FastAPI TestClient로 라우터만 격리 테스트한다. main app을 import하지 않아
startup/shutdown 이벤트나 외부 의존성 부팅을 피한다.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.routers.feedback as feedback_module
from src.agents.rl_continuous_improver import RetrainOutcome
from src.api.routers.feedback import router as feedback_router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(feedback_router, prefix="/feedback")
    return app


def _make_outcome(
    *,
    ticker: str = "005930.KS",
    success: bool = True,
    ratio: float | None = 0.6,
    best_ratio: float | None = 0.6,
) -> RetrainOutcome:
    return RetrainOutcome(
        ticker=ticker,
        success=success,
        new_policy_id=f"rl_{ticker}_test",
        excess_return=12.3,
        walk_forward_passed=True,
        deployed=True,
        selected_train_ratio=ratio,
        bandit_snapshot={
            "ticker": ticker,
            "profile_id": "tabular_q_v2_momentum",
            "best_ratio": best_ratio,
            "arms": {},
        },
    )


class FeedbackRouterRLRetrainTest(unittest.TestCase):
    def test_retrain_ticker_returns_selected_ratio(self) -> None:
        outcome = _make_outcome()
        improver = AsyncMock()
        improver.retrain_ticker = AsyncMock(return_value=outcome)

        with patch.object(feedback_module, "_get_rl_improver", return_value=improver):
            client = TestClient(_build_app())
            resp = client.post("/feedback/rl/retrain/005930")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["ticker"], "005930.KS")
        self.assertTrue(body["success"])
        self.assertAlmostEqual(body["selected_train_ratio"], 0.6)
        self.assertEqual(body["bandit_snapshot"]["best_ratio"], 0.6)
        improver.retrain_ticker.assert_awaited_once_with("005930")

    def test_retrain_all_aggregates_outcomes(self) -> None:
        outcomes = [
            _make_outcome(ticker="005930.KS", success=True, ratio=0.6),
            _make_outcome(ticker="000660.KS", success=False, ratio=None, best_ratio=None),
        ]
        outcomes[1].new_policy_id = None
        outcomes[1].deployed = False
        outcomes[1].walk_forward_passed = False
        outcomes[1].error = "training failed"

        improver = AsyncMock()
        improver.retrain_all = AsyncMock(return_value=outcomes)

        with patch.object(feedback_module, "_get_rl_improver", return_value=improver):
            client = TestClient(_build_app())
            resp = client.post("/feedback/rl/retrain-all")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total_tickers"], 2)
        self.assertEqual(body["successful"], 1)
        self.assertEqual(body["failed"], 1)
        self.assertEqual(len(body["results"]), 2)
        self.assertAlmostEqual(body["results"][0]["selected_train_ratio"], 0.6)
        self.assertIsNone(body["results"][1]["selected_train_ratio"])

    def test_retrain_ticker_propagates_improver_error_as_500(self) -> None:
        improver = AsyncMock()
        improver.retrain_ticker = AsyncMock(side_effect=RuntimeError("explode"))

        with patch.object(feedback_module, "_get_rl_improver", return_value=improver):
            client = TestClient(_build_app())
            with self.assertRaises(RuntimeError):
                # FastAPI TestClient는 내부 예외를 re-raise (기본 설정)
                client.post("/feedback/rl/retrain/005930")


class FeedbackRouterCycleTest(unittest.TestCase):
    def test_cycle_rl_only_runs_only_retrain(self) -> None:
        outcomes = [_make_outcome()]
        improver = AsyncMock()
        improver.retrain_all = AsyncMock(return_value=outcomes)

        with patch.object(feedback_module, "_get_rl_improver", return_value=improver):
            client = TestClient(_build_app())
            resp = client.post("/feedback/cycle", json={"scope": "rl_only"})

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["scope"], "rl_only")
        self.assertIsNotNone(body["rl_retrain"])
        self.assertEqual(body["rl_retrain"]["tickers_retrained"], 1)
        self.assertEqual(body["rl_retrain"]["successful"], 1)
        # rl_only 스코프에서는 llm/backtest 섹션이 비어 있어야 한다
        self.assertIsNone(body["llm_feedback"])
        self.assertIsNone(body["backtest"])

    def test_cycle_full_includes_all_sections(self) -> None:
        outcomes = [_make_outcome()]
        improver = AsyncMock()
        improver.retrain_all = AsyncMock(return_value=outcomes)

        with patch.object(feedback_module, "_get_rl_improver", return_value=improver):
            client = TestClient(_build_app())
            resp = client.post("/feedback/cycle", json={"scope": "full"})

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["scope"], "full")
        self.assertIsNotNone(body["llm_feedback"])
        self.assertIsNotNone(body["rl_retrain"])
        self.assertIsNotNone(body["backtest"])

    def test_cycle_passes_payload_overrides_to_improver(self) -> None:
        outcomes = [_make_outcome()]
        improver = AsyncMock()
        improver.retrain_all = AsyncMock(return_value=outcomes)

        with patch.object(feedback_module, "_get_rl_improver", return_value=improver):
            client = TestClient(_build_app())
            resp = client.post(
                "/feedback/cycle",
                json={
                    "scope": "rl_only",
                    "tickers": ["005930"],
                    "profiles": ["tabular_q_v2_momentum"],
                    "dataset_days": 90,
                },
            )

        self.assertEqual(resp.status_code, 200)
        improver.retrain_all.assert_awaited_once_with(
            tickers=["005930"],
            profile_ids=["tabular_q_v2_momentum"],
            dataset_days=90,
        )


if __name__ == "__main__":
    unittest.main()
