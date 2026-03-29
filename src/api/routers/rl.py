"""
src/api/routers/rl.py — RL Trading Lane REST API

정책 레지스트리 조회, 실험 결과 조회, 학습 트리거, 정책 활성화 API.
api_spec.md 기반 엔드포인트:
  GET  /rl/policies          — 등록된 정책 목록
  GET  /rl/policies/active   — 활성 정책 목록
  GET  /rl/policies/{ticker} — 종목별 정책 상세
  POST /rl/policies/{policy_id}/activate — 정책 강제 활성화
  GET  /rl/evaluations       — 평가 결과 목록
  GET  /rl/experiments       — 실험 실행 목록
  GET  /rl/experiments/{run_id} — 실험 상세
  POST /rl/training-jobs     — 학습 작업 생성
  GET  /rl/training-jobs/{job_id} — 학습 작업 상태
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.agents.rl_experiment_manager import RLExperimentManager
from src.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# ── 싱글턴 인스턴스 ───────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACTS = ROOT / "artifacts" / "rl"

_store: RLPolicyStoreV2 | None = None
_exp_mgr: RLExperimentManager | None = None


def _get_store() -> RLPolicyStoreV2:
    global _store
    if _store is None:
        _store = RLPolicyStoreV2(models_dir=DEFAULT_ARTIFACTS / "models")
    return _store


def _get_exp_mgr() -> RLExperimentManager:
    global _exp_mgr
    if _exp_mgr is None:
        _exp_mgr = RLExperimentManager(artifacts_dir=DEFAULT_ARTIFACTS)
    return _exp_mgr


# ── Response Models ───────────────────────────────────────────────────────


class PolicySummary(BaseModel):
    policy_id: str
    ticker: str
    algorithm: str
    state_version: str
    return_pct: float
    max_drawdown_pct: float
    trades: int
    win_rate: float
    approved: bool
    created_at: str
    is_active: bool = False


class PolicyDetail(PolicySummary):
    baseline_return_pct: float = 0.0
    excess_return_pct: float = 0.0
    holdout_steps: int = 0
    lookback: int = 0
    episodes: int = 0
    learning_rate: float = 0.0
    discount_factor: float = 0.0
    epsilon: float = 0.0
    trade_penalty_bps: int = 0
    file_path: Optional[str] = None


class ActivePolicyResponse(BaseModel):
    ticker: str
    policy_id: str
    return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    approved: bool = True


class ExperimentSummary(BaseModel):
    run_id: str
    ticker: str
    profile_id: str
    algorithm: str
    approved: bool
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    created_at: str
    policy_id: Optional[str] = None


class TrainingJobRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1, max_length=20)
    policy_family: str = Field(default="tabular_q_v2", description="알고리즘 프로파일 ID")
    dataset_interval: Literal["daily", "tick"] = "daily"
    dataset_days: int = Field(default=120, ge=30, le=365)


class TrainingJobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    tickers: list[str]
    created_at: str


class ListResponse(BaseModel):
    data: list[Any]
    meta: dict[str, Any]


# ── 정책 엔드포인트 ───────────────────────────────────────────────────────


@router.get("/policies", summary="등록된 정책 목록")
async def list_policies(
    ticker: Optional[str] = Query(None, description="종목 필터"),
    approved_only: bool = Query(False, description="승인된 정책만"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> ListResponse:
    try:
        store = _get_store()
        registry = store.load_registry()
    except Exception as e:
        logger.warning("RL 정책 레지스트리 로드 실패: %s", e)
        return ListResponse(data=[], meta={"total": 0, "page": page, "per_page": per_page})

    policies: list[dict] = []
    active_map = registry.list_active_policies()

    tickers = [ticker] if ticker else registry.list_all_tickers()

    for t in tickers:
        ticker_policies = registry.get_ticker(t)
        if not ticker_policies:
            continue
        for entry in ticker_policies.policies:
            if approved_only and not entry.approved:
                continue
            policies.append(
                PolicySummary(
                    policy_id=entry.policy_id,
                    ticker=entry.ticker,
                    algorithm=entry.algorithm,
                    state_version=entry.state_version,
                    return_pct=entry.return_pct,
                    max_drawdown_pct=entry.max_drawdown_pct,
                    trades=entry.trades,
                    win_rate=entry.win_rate,
                    approved=entry.approved,
                    created_at=entry.created_at.isoformat() if isinstance(entry.created_at, datetime) else str(entry.created_at),
                    is_active=(active_map.get(t) == entry.policy_id),
                ).model_dump()
            )

    # 페이지네이션
    total = len(policies)
    start = (page - 1) * per_page
    end = start + per_page
    page_data = policies[start:end]

    return ListResponse(
        data=page_data,
        meta={"total": total, "page": page, "per_page": per_page},
    )


@router.get("/policies/active", summary="활성 정책 목록")
async def list_active_policies() -> ListResponse:
    try:
        store = _get_store()
        registry = store.load_registry()
    except Exception as e:
        logger.warning("RL 정책 레지스트리 로드 실패: %s", e)
        return ListResponse(data=[], meta={"total": 0, "page": 1, "per_page": 0})
    active_map = registry.list_active_policies()

    result: list[dict] = []
    for t, pid in active_map.items():
        if pid is None:
            continue
        tp = registry.get_ticker(t)
        entry = tp.get_policy(pid) if tp else None
        result.append(
            ActivePolicyResponse(
                ticker=t,
                policy_id=pid,
                return_pct=entry.return_pct if entry else 0.0,
                max_drawdown_pct=entry.max_drawdown_pct if entry else 0.0,
                approved=entry.approved if entry else True,
            ).model_dump()
        )

    return ListResponse(
        data=result,
        meta={"total": len(result), "page": 1, "per_page": len(result)},
    )


@router.get("/policies/{ticker}", summary="종목별 정책 상세")
async def get_ticker_policies(ticker: str) -> ListResponse:
    try:
        store = _get_store()
        registry = store.load_registry()
    except Exception as e:
        logger.warning("RL 정책 레지스트리 로드 실패: %s", e)
        return ListResponse(data=[], meta={"total": 0, "page": 1, "per_page": 0})
    tp = registry.get_ticker(ticker)

    if not tp:
        raise HTTPException(status_code=404, detail=f"종목 {ticker}에 등록된 정책 없음")

    active_pid = tp.active_policy_id
    result: list[dict] = []
    for entry in tp.policies:
        result.append(
            PolicyDetail(
                policy_id=entry.policy_id,
                ticker=entry.ticker,
                algorithm=entry.algorithm,
                state_version=entry.state_version,
                return_pct=entry.return_pct,
                baseline_return_pct=entry.baseline_return_pct,
                excess_return_pct=entry.excess_return_pct,
                max_drawdown_pct=entry.max_drawdown_pct,
                trades=entry.trades,
                win_rate=entry.win_rate,
                holdout_steps=entry.holdout_steps,
                approved=entry.approved,
                created_at=entry.created_at.isoformat() if isinstance(entry.created_at, datetime) else str(entry.created_at),
                is_active=(entry.policy_id == active_pid),
                lookback=entry.lookback,
                episodes=entry.episodes,
                learning_rate=entry.learning_rate,
                discount_factor=entry.discount_factor,
                epsilon=entry.epsilon,
                trade_penalty_bps=entry.trade_penalty_bps,
                file_path=entry.file_path,
            ).model_dump()
        )

    return ListResponse(
        data=result,
        meta={"total": len(result), "page": 1, "per_page": len(result)},
    )


@router.post(
    "/policies/{policy_id}/activate",
    summary="정책 강제 활성화",
    status_code=status.HTTP_200_OK,
)
async def activate_policy(policy_id: str, ticker: str = Query(...)) -> dict:
    store = _get_store()
    try:
        artifact = store.load_policy(policy_id, ticker)
        if artifact is None:
            raise HTTPException(status_code=404, detail=f"정책 {policy_id} 없음")
        store.force_activate_policy(ticker, policy_id)
        logger.info("정책 강제 활성화: %s (ticker=%s)", policy_id, ticker)
        return {"status": "activated", "policy_id": policy_id, "ticker": ticker}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"정책 파일 {policy_id} 없음")
    except Exception as e:
        logger.error("정책 활성화 실패: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── 실험 엔드포인트 ───────────────────────────────────────────────────────


@router.get("/experiments", summary="실험 실행 목록")
async def list_experiments(
    ticker: Optional[str] = Query(None),
    profile_id: Optional[str] = Query(None),
    approved_only: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> ListResponse:
    try:
        mgr = _get_exp_mgr()
        runs = mgr.list_runs(
            ticker=ticker,
            profile_id=profile_id,
            approved_only=approved_only,
        )
    except Exception as e:
        logger.warning("RL 실험 목록 로드 실패: %s", e)
        return ListResponse(data=[], meta={"total": 0, "page": page, "per_page": per_page})

    result: list[dict] = []
    for run in runs:
        result.append(
            ExperimentSummary(
                run_id=run.run_id,
                ticker=run.dataset_meta.ticker if run.dataset_meta else "",
                profile_id=run.config.profile_id if run.config else "",
                algorithm=run.config.algorithm if run.config else "",
                approved=run.approved,
                total_return_pct=run.metrics.total_return_pct if run.metrics else 0.0,
                max_drawdown_pct=run.metrics.max_drawdown_pct if run.metrics else 0.0,
                created_at=run.created_at,
                policy_id=run.policy_id,
            ).model_dump()
        )

    total = len(result)
    start = (page - 1) * per_page
    end = start + per_page

    return ListResponse(
        data=result[start:end],
        meta={"total": total, "page": page, "per_page": per_page},
    )


@router.get("/experiments/{run_id}", summary="실험 상세")
async def get_experiment(run_id: str) -> dict:
    mgr = _get_exp_mgr()
    run = mgr.load_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"실험 {run_id} 없음")
    return run.model_dump() if hasattr(run, "model_dump") else run.__dict__


# ── 평가 엔드포인트 ───────────────────────────────────────────────────────


@router.get("/evaluations", summary="평가 결과 목록")
async def list_evaluations(
    policy_id: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    eval_status: Optional[Literal["approved", "hold", "rejected"]] = Query(
        None, alias="status"
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> ListResponse:
    try:
        store = _get_store()
        registry = store.load_registry()
    except Exception as e:
        logger.warning("RL 정책 레지스트리 로드 실패: %s", e)
        return ListResponse(
            data=[],
            meta={"total": 0, "page": page, "per_page": per_page},
        )

    evaluations: list[dict] = []
    tickers = [ticker] if ticker else registry.list_all_tickers()

    for t in tickers:
        tp = registry.get_ticker(t)
        if not tp:
            continue
        for entry in tp.policies:
            if policy_id and entry.policy_id != policy_id:
                continue

            # 상태 필터
            if eval_status == "approved" and not entry.approved:
                continue
            if eval_status == "rejected" and entry.approved:
                continue

            evaluations.append(
                {
                    "policy_id": entry.policy_id,
                    "ticker": entry.ticker,
                    "algorithm": entry.algorithm,
                    "return_pct": entry.return_pct,
                    "baseline_return_pct": entry.baseline_return_pct,
                    "excess_return_pct": entry.excess_return_pct,
                    "max_drawdown_pct": entry.max_drawdown_pct,
                    "trades": entry.trades,
                    "win_rate": entry.win_rate,
                    "holdout_steps": entry.holdout_steps,
                    "approved": entry.approved,
                    "created_at": entry.created_at,
                }
            )

    total = len(evaluations)
    start = (page - 1) * per_page
    end = start + per_page

    return ListResponse(
        data=evaluations[start:end],
        meta={"total": total, "page": page, "per_page": per_page},
    )


# ── 학습 작업 엔드포인트 ──────────────────────────────────────────────────

# 인메모리 작업 큐 (프로덕션에서는 Redis/Celery로 대체)
_training_jobs: dict[str, dict] = {}


@router.post(
    "/training-jobs",
    summary="RL 학습 작업 생성",
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_training_job(req: TrainingJobRequest) -> TrainingJobResponse:
    job_id = f"rl-job-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    job = {
        "job_id": job_id,
        "status": "queued",
        "tickers": req.tickers,
        "policy_family": req.policy_family,
        "dataset_interval": req.dataset_interval,
        "dataset_days": req.dataset_days,
        "created_at": now,
        "completed_at": None,
        "results": None,
    }
    _training_jobs[job_id] = job

    logger.info(
        "RL 학습 작업 생성: job_id=%s, tickers=%s, family=%s",
        job_id,
        req.tickers,
        req.policy_family,
    )

    return TrainingJobResponse(
        job_id=job_id,
        status="queued",
        tickers=req.tickers,
        created_at=now,
    )


@router.get("/training-jobs", summary="학습 작업 전체 목록 조회")
async def list_training_jobs() -> dict:
    """인메모리에 저장된 학습 작업 목록을 반환합니다."""
    jobs = sorted(_training_jobs.values(), key=lambda j: j.get("created_at", ""), reverse=True)
    return {"data": jobs, "total": len(jobs)}


@router.get("/training-jobs/{job_id}", summary="학습 작업 상태 조회")
async def get_training_job(job_id: str) -> dict:
    job = _training_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"학습 작업 {job_id} 없음")
    return job


# ── Walk-Forward 평가 엔드포인트 ──────────────────────────────────────────


class WalkForwardRequestModel(BaseModel):
    ticker: str = Field(..., description="종목 코드")
    n_folds: int = Field(default=5, ge=2, le=10)
    expanding_window: bool = True
    trainer_version: Literal["v1", "v2"] = "v2"
    dataset_days: int = Field(default=120, ge=60, le=365)


@router.post("/walk-forward", summary="Walk-Forward 평가 실행")
async def run_walk_forward(req: WalkForwardRequestModel) -> dict:
    """Walk-forward validation으로 정책 일관성 평가."""
    from src.agents.rl_walk_forward import WalkForwardEvaluator

    try:
        from src.agents.rl_trading import RLDatasetBuilder

        builder = RLDatasetBuilder()
        dataset = await builder.build_dataset(req.ticker, days=req.dataset_days)

        if req.trainer_version == "v2":
            from src.agents.rl_trading_v2 import TabularQTrainerV2 as Trainer
        else:
            from src.agents.rl_trading import TabularQTrainer as Trainer

        trainer = Trainer()
        evaluator = WalkForwardEvaluator(
            n_folds=req.n_folds,
            expanding_window=req.expanding_window,
        )
        result = evaluator.evaluate(dataset.closes, trainer)
        return result.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Walk-Forward 평가 실패: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Shadow Inference 엔드포인트 ────────────────────────────────────────


_shadow_engine: ShadowInferenceEngine | None = None  # type: ignore[name-defined]  # noqa: F821


def _get_shadow_engine() -> ShadowInferenceEngine:  # type: ignore[name-defined]  # noqa: F821
    global _shadow_engine
    if _shadow_engine is None:
        from src.agents.rl_shadow_inference import ShadowInferenceEngine

        _shadow_engine = ShadowInferenceEngine(policy_store=_get_store())
    return _shadow_engine


class ShadowSignalRequest(BaseModel):
    policy_id: str = Field(..., description="정책 ID")
    ticker: str = Field(..., description="종목 코드")
    signal: Literal["BUY", "SELL", "HOLD"] = Field(..., description="시그널")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    close_price: float = Field(..., gt=0, description="현재 종가")
    reasoning_summary: str = ""


@router.post("/shadow/signals", summary="Shadow 시그널 기록", status_code=status.HTTP_201_CREATED)
async def create_shadow_signal(req: ShadowSignalRequest) -> dict:
    """Shadow 모드 시그널을 기록합니다. 블렌딩에 참여하지 않습니다."""
    engine = _get_shadow_engine()
    signal = engine.create_shadow_signal(
        policy_id=req.policy_id,
        ticker=req.ticker,
        signal=req.signal,
        confidence=req.confidence,
        close_price=req.close_price,
        reasoning_summary=req.reasoning_summary,
    )
    return signal.model_dump(mode="json")


@router.get("/shadow/policies", summary="Shadow 정책 목록")
async def list_shadow_policies() -> ListResponse:
    """현재 shadow 모드 중인 정책 목록을 반환합니다."""
    engine = _get_shadow_engine()
    policies = engine.list_shadow_policies()
    return ListResponse(
        data=policies,
        meta={"total": len(policies), "page": 1, "per_page": len(policies)},
    )


@router.get("/shadow/performance/{policy_id}", summary="Shadow 성과 조회")
async def get_shadow_performance(
    policy_id: str,
    ticker: Optional[str] = Query(None),
) -> dict:
    """특정 정책의 shadow 기간 누적 성과를 반환합니다."""
    engine = _get_shadow_engine()
    perf = engine.get_shadow_performance(policy_id, ticker)
    return perf.model_dump(mode="json")


@router.get("/shadow/records/{policy_id}", summary="Shadow 기록 조회")
async def get_shadow_records(
    policy_id: str,
    ticker: Optional[str] = Query(None),
) -> ListResponse:
    """특정 정책의 shadow 기록을 반환합니다."""
    engine = _get_shadow_engine()
    records = engine.get_shadow_records(policy_id, ticker)
    return ListResponse(
        data=records,
        meta={"total": len(records), "page": 1, "per_page": len(records)},
    )


# ── Promotion Gate 엔드포인트 ─────────────────────────────────────────


class ShadowToPaperRequest(BaseModel):
    policy_id: str
    ticker: str
    walk_forward_approved: Optional[bool] = None
    walk_forward_consistency: Optional[float] = None


class PaperToRealRequest(BaseModel):
    policy_id: str
    ticker: str
    paper_days: int = 0
    paper_trades: int = 0
    paper_return_pct: float = 0.0
    paper_max_drawdown_pct: float = 0.0
    paper_sharpe_ratio: float = 0.0
    walk_forward_approved: Optional[bool] = None


@router.post("/promotion/shadow-to-paper", summary="Shadow→Paper 승격 평가")
async def evaluate_shadow_to_paper(req: ShadowToPaperRequest) -> dict:
    """Shadow → Paper 승격 조건을 평가합니다."""
    engine = _get_shadow_engine()
    result = engine.evaluate_shadow_to_paper(
        policy_id=req.policy_id,
        ticker=req.ticker,
        walk_forward_approved=req.walk_forward_approved,
        walk_forward_consistency=req.walk_forward_consistency,
    )
    return result.model_dump(mode="json")


@router.post("/promotion/paper-to-real", summary="Paper→Real 승격 평가")
async def evaluate_paper_to_real(req: PaperToRealRequest) -> dict:
    """Paper → Real 승격 조건을 평가합니다."""
    engine = _get_shadow_engine()
    result = engine.evaluate_paper_to_real(
        policy_id=req.policy_id,
        ticker=req.ticker,
        paper_days=req.paper_days,
        paper_trades=req.paper_trades,
        paper_return_pct=req.paper_return_pct,
        paper_max_drawdown_pct=req.paper_max_drawdown_pct,
        paper_sharpe_ratio=req.paper_sharpe_ratio,
        walk_forward_approved=req.walk_forward_approved,
    )
    return result.model_dump(mode="json")


@router.get("/promotion/policy-mode/{policy_id}", summary="정책 운용 모드 조회")
async def get_policy_mode(
    policy_id: str,
    ticker: str = Query(..., description="종목 코드"),
) -> dict:
    """정책의 현재 운용 모드를 반환합니다."""
    engine = _get_shadow_engine()
    mode = engine.get_policy_mode(policy_id, ticker)
    return {"policy_id": policy_id, "ticker": ticker, "mode": mode}
