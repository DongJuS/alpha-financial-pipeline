"""
src/api/routers/phase10.py — Phase 10 Integration Status API

Endpoints for integration dashboard:
  GET  /integration/search-sources     — Recent search results with sources and sentiment
  GET  /integration/rl-evaluation      — RL policy evaluation metrics
  GET  /integration/active-policies    — Currently active RL policies with metadata
  GET  /integration/audit-status       — Integration audit checklist status
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, status
from pydantic import BaseModel

from src.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# ── Response Models ───────────────────────────────────────────────────────


class SearchSourceItem(BaseModel):
    """Recent research query with sources and sentiment."""

    query_id: str
    ticker: str
    query: str
    sentiment: str  # "bullish", "bearish", "neutral"
    source_count: int
    confidence: float  # 0.0-1.0
    sources: list[str]  # URLs or source names
    timestamp: str  # ISO 8601


class SearchSourcesResponse(BaseModel):
    """List of recent search sources."""

    items: list[SearchSourceItem]
    total_count: int
    last_updated: str


class RLEvaluationItem(BaseModel):
    """RL policy evaluation metrics."""

    policy_id: str
    ticker: str
    algorithm: str
    holdout_return_pct: float
    sharpe_ratio: Optional[float] = None
    win_rate: float  # 0.0-1.0
    status: str  # "approved", "pending", "rejected"
    timestamp: str  # ISO 8601


class RLEvaluationResponse(BaseModel):
    """RL policy evaluation results."""

    items: list[RLEvaluationItem]
    total_count: int
    last_updated: str


class ActivePolicyItem(BaseModel):
    """Currently active RL policy with metadata."""

    policy_id: str
    ticker: str
    algorithm: str
    strategy_id: str  # which strategy uses it
    mode: str  # "shadow", "paper", "live"
    last_inference_time: Optional[str] = None
    return_pct: float
    trades_count: int
    timestamp: str  # ISO 8601


class ActivePoliciesResponse(BaseModel):
    """List of active policies."""

    items: list[ActivePolicyItem]
    total_count: int
    last_updated: str


class AuditCheckItem(BaseModel):
    """Single audit checklist item."""

    category: str  # "search", "rl", "policy", "backtest"
    item_name: str
    status: str  # "pass", "fail", "pending"
    details: Optional[str] = None


class AuditStatusResponse(BaseModel):
    """Integration audit checklist status."""

    items: list[AuditCheckItem]
    overall_status: str  # "healthy", "warning", "critical"
    last_updated: str


# ── Helper Functions ──────────────────────────────────────────────────────


def _generate_mock_search_sources() -> list[SearchSourceItem]:
    """Generate mock search source data for demonstration."""
    return [
        SearchSourceItem(
            query_id="search_001",
            ticker="AAPL",
            query="Apple quarterly earnings outlook",
            sentiment="bullish",
            source_count=5,
            confidence=0.92,
            sources=[
                "https://bloomberg.com/apple-earnings",
                "https://seekingalpha.com/apple",
                "https://marketwatch.com/aapl",
            ],
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
        SearchSourceItem(
            query_id="search_002",
            ticker="MSFT",
            query="Microsoft AI integration progress",
            sentiment="bullish",
            source_count=4,
            confidence=0.88,
            sources=[
                "https://techcrunch.com/microsoft-ai",
                "https://reuters.com/microsoft",
            ],
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
        SearchSourceItem(
            query_id="search_003",
            ticker="TSLA",
            query="Tesla supply chain disruptions",
            sentiment="bearish",
            source_count=3,
            confidence=0.75,
            sources=[
                "https://reuters.com/tesla",
                "https://cnbc.com/tesla-supply",
            ],
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    ]


def _generate_mock_rl_evaluations() -> list[RLEvaluationItem]:
    """Generate mock RL policy evaluation data."""
    return [
        RLEvaluationItem(
            policy_id="rl_aapl_dqn_v1",
            ticker="AAPL",
            algorithm="DQN",
            holdout_return_pct=12.5,
            sharpe_ratio=1.85,
            win_rate=0.68,
            status="approved",
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
        RLEvaluationItem(
            policy_id="rl_msft_ppo_v2",
            ticker="MSFT",
            algorithm="PPO",
            holdout_return_pct=8.3,
            sharpe_ratio=1.42,
            win_rate=0.62,
            status="approved",
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
        RLEvaluationItem(
            policy_id="rl_tsla_a3c_v1",
            ticker="TSLA",
            algorithm="A3C",
            holdout_return_pct=-2.1,
            sharpe_ratio=0.5,
            win_rate=0.45,
            status="pending",
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    ]


def _generate_mock_active_policies() -> list[ActivePolicyItem]:
    """Generate mock active policy data."""
    return [
        ActivePolicyItem(
            policy_id="rl_aapl_dqn_v1",
            ticker="AAPL",
            algorithm="DQN",
            strategy_id="RL",
            mode="paper",
            last_inference_time=datetime.now(timezone.utc).isoformat(),
            return_pct=12.5,
            trades_count=128,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
        ActivePolicyItem(
            policy_id="rl_msft_ppo_v2",
            ticker="MSFT",
            algorithm="PPO",
            strategy_id="RL",
            mode="shadow",
            last_inference_time=datetime.now(timezone.utc).isoformat(),
            return_pct=8.3,
            trades_count=95,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    ]


def _generate_mock_audit_status() -> list[AuditCheckItem]:
    """Generate mock audit checklist data."""
    return [
        AuditCheckItem(
            category="search",
            item_name="Search pipeline active",
            status="pass",
            details="Processing 50+ queries/day",
        ),
        AuditCheckItem(
            category="rl",
            item_name="RL training jobs running",
            status="pass",
            details="2 jobs in progress",
        ),
        AuditCheckItem(
            category="policy",
            item_name="Active policies approved",
            status="pass",
            details="All 2 active policies approved",
        ),
        AuditCheckItem(
            category="backtest",
            item_name="Backtest pipeline status",
            status="warning",
            details="1 backtest stalled (investigating)",
        ),
    ]


# ── Endpoints ──────────────────────────────────────────────────────────


@router.get(
    "/search-sources",
    response_model=SearchSourcesResponse,
    status_code=status.HTTP_200_OK,
)
async def get_search_sources() -> SearchSourcesResponse:
    """
    Get recent search results with sources, sentiment, and confidence.

    Returns a list of recent research queries with their associated sources,
    sentiment analysis, and confidence scores.
    """
    items = _generate_mock_search_sources()
    return SearchSourcesResponse(
        items=items,
        total_count=len(items),
        last_updated=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/rl-evaluation",
    response_model=RLEvaluationResponse,
    status_code=status.HTTP_200_OK,
)
async def get_rl_evaluation() -> RLEvaluationResponse:
    """
    Get RL policy evaluation metrics (holdout return, sharpe, win rate).

    Returns evaluation results for policies in holdout testing,
    including metrics and approval status.
    """
    items = _generate_mock_rl_evaluations()
    return RLEvaluationResponse(
        items=items,
        total_count=len(items),
        last_updated=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/active-policies",
    response_model=ActivePoliciesResponse,
    status_code=status.HTTP_200_OK,
)
async def get_active_policies() -> ActivePoliciesResponse:
    """
    Get currently active RL policies with strategy mapping and inference metadata.

    Returns list of policies actively being used in trading strategies,
    with their deployment mode (shadow/paper/live) and recent performance.
    """
    items = _generate_mock_active_policies()
    return ActivePoliciesResponse(
        items=items,
        total_count=len(items),
        last_updated=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/audit-status",
    response_model=AuditStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_audit_status() -> AuditStatusResponse:
    """
    Get integration audit checklist status.

    Returns status of integration health checks across search, RL, policy,
    and backtest systems.
    """
    items = _generate_mock_audit_status()
    overall_status = "healthy"
    if any(item.status == "fail" for item in items):
        overall_status = "critical"
    elif any(item.status == "warning" for item in items):
        overall_status = "warning"

    return AuditStatusResponse(
        items=items,
        overall_status=overall_status,
        last_updated=datetime.now(timezone.utc).isoformat(),
    )
