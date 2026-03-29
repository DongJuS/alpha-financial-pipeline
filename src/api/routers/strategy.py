"""
src/api/routers/strategy.py — Strategy A/B 시그널 및 토너먼트 라우터
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from src.agents.blending import blend_strategy_signals
from src.api.deps import get_current_user
from src.utils.db_client import fetch, fetchrow
from src.utils.config import get_settings

router = APIRouter()


class SignalItem(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_id": "predictor_1",
                "llm_model": "claude-opus-4-6",
                "ticker": "005930",
                "signal": "BUY",
                "confidence": 0.71,
                "target_price": 74000,
                "stop_loss": 69500,
                "reasoning_summary": "거래량 회복과 단기 추세 반전 가능성을 반영한 매수 의견",
            }
        }
    )

    agent_id: str
    llm_model: str
    ticker: str
    signal: str
    confidence: Optional[float] = None
    target_price: Optional[int] = None
    stop_loss: Optional[int] = None
    reasoning_summary: Optional[str] = None


class StrategyAResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "date": "2026-03-21",
                "winner_agent_id": "predictor_1",
                "signals": [
                    {
                        "agent_id": "predictor_1",
                        "llm_model": "claude-opus-4-6",
                        "ticker": "005930",
                        "signal": "BUY",
                        "confidence": 0.71,
                        "target_price": 74000,
                        "stop_loss": 69500,
                        "reasoning_summary": "거래량 회복과 단기 추세 반전 가능성을 반영한 매수 의견",
                    }
                ],
            }
        }
    )

    date: str
    winner_agent_id: Optional[str] = None
    signals: list[SignalItem]


class TournamentRankItem(BaseModel):
    agent_id: str
    llm_model: str
    persona: str
    rolling_accuracy: Optional[float] = None
    correct: int
    total: int
    is_current_winner: bool


class TournamentResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "period_days": 5,
                "rankings": [
                    {
                        "agent_id": "predictor_1",
                        "llm_model": "claude-opus-4-6",
                        "persona": "가치 투자형",
                        "rolling_accuracy": 0.6123,
                        "correct": 30,
                        "total": 49,
                        "is_current_winner": True,
                    }
                ],
            }
        }
    )

    period_days: int
    rankings: list[TournamentRankItem]


class StrategyBSignalItem(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_id": "consensus_synthesizer",
                "llm_model": "claude-opus-4-6",
                "ticker": "005930",
                "signal": "HOLD",
                "confidence": 0.58,
                "reasoning_summary": "합의 임계치 미달로 HOLD",
                "trading_date": "2026-03-21",
                "debate_transcript_id": 13584,
            }
        }
    )

    agent_id: str
    llm_model: str
    ticker: str
    signal: str
    confidence: Optional[float] = None
    reasoning_summary: Optional[str] = None
    trading_date: str
    debate_transcript_id: Optional[int] = None


class StrategyBResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "date": "2026-03-21",
                "signals": [
                    {
                        "agent_id": "consensus_synthesizer",
                        "llm_model": "claude-opus-4-6",
                        "ticker": "005930",
                        "signal": "HOLD",
                        "confidence": 0.58,
                        "reasoning_summary": "합의 임계치 미달로 HOLD",
                        "trading_date": "2026-03-21",
                        "debate_transcript_id": 13584,
                    }
                ],
            }
        }
    )

    date: str = Field(description="조회 기준 일자 또는 today")
    signals: list[StrategyBSignalItem]


class DebateResponse(BaseModel):
    id: int
    date: str
    ticker: str
    rounds: int
    consensus_reached: bool
    final_signal: Optional[str] = None
    confidence: Optional[float] = None
    proposer_content: Optional[str] = None
    challenger1_content: Optional[str] = None
    challenger2_content: Optional[str] = None
    synthesizer_content: Optional[str] = None
    no_consensus_reason: Optional[str] = None
    created_at: str


class DebateListItem(BaseModel):
    id: int
    date: str
    ticker: str
    rounds: int
    consensus_reached: bool
    final_signal: Optional[str] = None
    confidence: Optional[float] = None
    no_consensus_reason: Optional[str] = None
    created_at: str


class DebateListResponse(BaseModel):
    items: list[DebateListItem]


class CombinedSignalItem(BaseModel):
    ticker: str
    strategy_a_signal: Optional[str] = None
    strategy_b_signal: Optional[str] = None
    combined_signal: str
    combined_confidence: Optional[float] = None
    conflict: bool


class CombinedResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "blend_ratio": 0.5,
                "signals": [
                    {
                        "ticker": "005930",
                        "strategy_a_signal": "BUY",
                        "strategy_b_signal": "HOLD",
                        "combined_signal": "BUY",
                        "combined_confidence": 0.64,
                        "conflict": False,
                    }
                ],
            }
        }
    )

    blend_ratio: float
    signals: list[CombinedSignalItem]


@router.get(
    "/a/signals",
    response_model=StrategyAResponse,
    summary="Strategy A 최신 시그널",
    description="특정 거래일 또는 오늘 기준 Strategy A predictor 결과를 조회합니다. `winner_agent_id`는 같은 일자의 토너먼트 우승 predictor를 뜻합니다.",
)
async def get_strategy_a_signals(
    _: Annotated[dict, Depends(get_current_user)],
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
) -> StrategyAResponse:
    """Strategy A (Tournament) 최신 시그널을 반환합니다."""
    date_filter = date or "CURRENT_DATE"

    rows = await fetch(
        f"""
        SELECT p.agent_id, p.llm_model, p.ticker, p.signal,
               p.confidence::float, p.target_price, p.stop_loss, p.reasoning_summary,
               p.trading_date::text AS trading_date,
               s.is_current_winner
        FROM predictions p
        LEFT JOIN predictor_tournament_scores s
            ON p.agent_id = s.agent_id AND p.trading_date = s.trading_date
        WHERE p.strategy = 'A'
          AND p.trading_date = {'$1' if date else 'CURRENT_DATE'}::date
        ORDER BY p.agent_id
        """,
        *([date] if date else []),
    )

    winner = next((r["agent_id"] for r in rows if r["is_current_winner"]), None)

    return StrategyAResponse(
        date=date or "latest",
        winner_agent_id=winner,
        signals=[
            SignalItem(
                agent_id=r["agent_id"],
                llm_model=r["llm_model"],
                ticker=r["ticker"],
                signal=r["signal"],
                confidence=r["confidence"],
                target_price=r["target_price"],
                stop_loss=r["stop_loss"],
                reasoning_summary=r["reasoning_summary"],
            )
            for r in rows
        ],
    )


@router.get(
    "/a/tournament",
    response_model=TournamentResponse,
    summary="Strategy A 토너먼트 순위",
    description="가장 최근 집계일의 Strategy A predictor 순위표를 반환합니다. 각 predictor의 최근 롤링 정답률과 우승 여부를 확인할 수 있습니다.",
)
async def get_tournament(
    _: Annotated[dict, Depends(get_current_user)],
    days: int = Query(default=5, ge=1, le=30),
) -> TournamentResponse:
    """최근 N거래일 토너먼트 점수 및 순위를 반환합니다."""
    rows = await fetch(
        """
        SELECT agent_id, llm_model, persona,
               rolling_accuracy::float,
               correct, total, is_current_winner
        FROM predictor_tournament_scores
        WHERE trading_date = (
            SELECT MAX(trading_date) FROM predictor_tournament_scores
        )
        ORDER BY rolling_accuracy DESC NULLS LAST
        """
    )

    return TournamentResponse(
        period_days=days,
        rankings=[
            TournamentRankItem(
                agent_id=r["agent_id"],
                llm_model=r["llm_model"],
                persona=r["persona"],
                rolling_accuracy=r["rolling_accuracy"],
                correct=r["correct"],
                total=r["total"],
                is_current_winner=r["is_current_winner"],
            )
            for r in rows
        ],
    )


@router.get(
    "/b/signals",
    response_model=StrategyBResponse,
    summary="Strategy B 최신 시그널",
    description="특정 거래일 또는 오늘 기준 Strategy B 토론 결과를 조회합니다. 각 항목은 최종 Synthesizer 신호와 토론 transcript ID를 포함합니다.",
)
async def get_strategy_b_signals(
    _: Annotated[dict, Depends(get_current_user)],
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
) -> StrategyBResponse:
    """Strategy B (Consensus) 최신 합의 시그널을 반환합니다."""
    rows = await fetch(
        """
        SELECT p.agent_id, p.llm_model, p.ticker, p.signal,
               p.confidence::float, p.reasoning_summary,
               p.trading_date::text,
               p.debate_transcript_id
        FROM predictions p
        WHERE p.strategy = 'B'
          AND p.trading_date = COALESCE($1::date, CURRENT_DATE)
        ORDER BY p.ticker
        """,
        date,
    )

    return StrategyBResponse(
        date=date or "today",
        signals=[StrategyBSignalItem(**dict(r)) for r in rows],
    )


@router.get(
    "/b/debate/{debate_id}",
    response_model=DebateResponse,
    summary="Strategy B 토론 전문",
    description="단일 debate transcript를 원문 수준으로 조회합니다. 프론트 디버깅이나 Strategy B 판단 근거 확인에 사용합니다.",
)
async def get_debate_transcript(
    debate_id: int,
    _: Annotated[dict, Depends(get_current_user)],
) -> DebateResponse:
    """Strategy B 토론 전문을 조회합니다."""
    row = await fetchrow(
        """
        SELECT id, trading_date::text AS date, ticker, rounds,
               consensus_reached, final_signal, confidence::float AS confidence,
               proposer_content, challenger1_content,
               challenger2_content, synthesizer_content, no_consensus_reason,
               to_char(created_at AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS+09:00') AS created_at
        FROM debate_transcripts
        WHERE id = $1
        """,
        debate_id,
    )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"토론 ID {debate_id}를 찾을 수 없습니다.",
        )

    return DebateResponse(**dict(row))


@router.get(
    "/b/debates",
    response_model=DebateListResponse,
    summary="Strategy B 최근 토론 목록",
    description="최근 Strategy B 토론 이력을 날짜나 종목별로 조회합니다. 목록 화면과 운영 확인용 API입니다.",
)
async def list_debate_transcripts(
    _: Annotated[dict, Depends(get_current_user)],
    limit: int = Query(default=20, ge=1, le=100),
    ticker: Optional[str] = Query(default=None, description="티커 코드 (예: 005930)"),
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
) -> DebateListResponse:
    """Strategy B 최근 토론 이력을 조회합니다."""
    rows = await fetch(
        """
        SELECT
            id,
            trading_date::text AS date,
            ticker,
            rounds,
            consensus_reached,
            final_signal,
            confidence::float AS confidence,
            no_consensus_reason,
            to_char(created_at AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS+09:00') AS created_at
        FROM debate_transcripts
        WHERE ($1::text IS NULL OR ticker = $1)
          AND ($2::date IS NULL OR trading_date = $2::date)
        ORDER BY trading_date DESC, created_at DESC
        LIMIT $3
        """,
        ticker,
        date,
        limit,
    )

    return DebateListResponse(items=[DebateListItem(**dict(r)) for r in rows])


@router.get(
    "/combined",
    response_model=CombinedResponse,
    summary="A/B 블렌딩 시그널",
    description="Strategy A 우승 predictor와 Strategy B 토론 결과를 합성한 최종 시그널을 반환합니다. Redis에 5분간 캐시됩니다.",
)
async def get_combined_signals(
    _: Annotated[dict, Depends(get_current_user)],
) -> CombinedResponse:
    """두 전략이 블렌딩된 최종 시그널을 반환합니다. (Redis 5분 캐싱)"""
    from src.utils.redis_client import get_redis as _get_redis

    redis = await _get_redis()
    cache_key = "api:combined_signals:today"
    cached = await redis.get(cache_key)
    if cached:
        import json as _json
        data = _json.loads(cached)
        return CombinedResponse(**data)

    settings = get_settings()

    rows = await fetch(
        """
        WITH winner AS (
            SELECT agent_id
            FROM predictor_tournament_scores
            WHERE is_current_winner = TRUE
            ORDER BY trading_date DESC, updated_at DESC, id DESC
            LIMIT 1
        ),
        a AS (
            SELECT DISTINCT ON (p.ticker)
                p.ticker, p.signal AS signal_a, p.confidence AS conf_a
            FROM predictions p
            JOIN winner w ON p.agent_id = w.agent_id
            WHERE p.strategy = 'A' AND p.trading_date = CURRENT_DATE
            ORDER BY p.ticker, p.timestamp_utc DESC, p.id DESC
        ),
        b AS (
            SELECT DISTINCT ON (p.ticker)
                p.ticker, p.signal AS signal_b, p.confidence AS conf_b
            FROM predictions p
            WHERE p.strategy = 'B' AND p.trading_date = CURRENT_DATE
            ORDER BY p.ticker, p.timestamp_utc DESC, p.id DESC
        )
        SELECT
            COALESCE(a.ticker, b.ticker) AS ticker,
            a.signal_a, b.signal_b,
            COALESCE(a.conf_a, 0)::float AS conf_a,
            COALESCE(b.conf_b, 0)::float AS conf_b
        FROM a FULL OUTER JOIN b ON a.ticker = b.ticker
        ORDER BY COALESCE(a.ticker, b.ticker)
        """
    )

    ratio = settings.strategy_blend_ratio
    signals: list[CombinedSignalItem] = []

    for r in rows:
        blended = blend_strategy_signals(
            strategy_a_signal=r["signal_a"],
            strategy_a_confidence=r["conf_a"],
            strategy_b_signal=r["signal_b"],
            strategy_b_confidence=r["conf_b"],
            blend_ratio=ratio,
        )

        signals.append(
            CombinedSignalItem(
                ticker=r["ticker"],
                strategy_a_signal=r["signal_a"],
                strategy_b_signal=r["signal_b"],
                combined_signal=blended.combined_signal,
                combined_confidence=blended.combined_confidence,
                conflict=blended.conflict,
            )
        )

    result = CombinedResponse(blend_ratio=ratio, signals=signals)

    # Redis 캐싱 (5분 TTL)
    import json as _json
    await redis.set(cache_key, _json.dumps(result.model_dump(), default=str), ex=300)

    return result


# ── 전략 승격 API ──────────────────────────────────────────────────────────


class PromotionReadinessResponse(BaseModel):
    strategy_id: str
    from_mode: str
    to_mode: str
    ready: bool
    criteria: dict
    actual: dict
    failures: list[str]
    message: str


class PromotionRequest(BaseModel):
    from_mode: str
    to_mode: str
    force: bool = False


class PromotionResponse(BaseModel):
    success: bool
    strategy_id: str
    from_mode: str
    to_mode: str
    message: str


class StrategyStatusItem(BaseModel):
    strategy_id: str
    active_modes: list[str]
    promotion_readiness: dict


@router.get("/promotion-status")
async def get_promotion_status(
    _: Annotated[dict, Depends(get_current_user)],
) -> list[StrategyStatusItem]:
    """모든 전략의 현재 모드와 승격 준비 상태를 반환합니다."""
    from src.utils.strategy_promotion import StrategyPromoter

    promoter = StrategyPromoter()
    statuses = await promoter.get_all_strategy_status()
    return [StrategyStatusItem(**s) for s in statuses]


@router.get("/{strategy_id}/promotion-readiness", response_model=PromotionReadinessResponse)
async def get_promotion_readiness(
    strategy_id: str,
    _: Annotated[dict, Depends(get_current_user)],
    from_mode: str = Query(default="virtual"),
    to_mode: str = Query(default="paper"),
) -> PromotionReadinessResponse:
    """특정 전략의 승격 준비 상태를 확인합니다."""
    from src.utils.strategy_promotion import StrategyPromoter

    promoter = StrategyPromoter()
    check = await promoter.evaluate_promotion_readiness(
        strategy_id=strategy_id.upper(),
        from_mode=from_mode,
        to_mode=to_mode,
    )
    return PromotionReadinessResponse(
        strategy_id=check.strategy_id,
        from_mode=check.from_mode,
        to_mode=check.to_mode,
        ready=check.ready,
        criteria=check.criteria,
        actual=check.actual,
        failures=check.failures,
        message=check.message,
    )


@router.post("/{strategy_id}/promote", response_model=PromotionResponse)
async def promote_strategy(
    strategy_id: str,
    body: PromotionRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> PromotionResponse:
    """전략을 다음 모드로 승격합니다."""
    from src.utils.strategy_promotion import StrategyPromoter

    promoter = StrategyPromoter()
    result = await promoter.promote_strategy(
        strategy_id=strategy_id.upper(),
        from_mode=body.from_mode,
        to_mode=body.to_mode,
        force=body.force,
        approved_by=user.get("email", "api_user"),
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )

    return PromotionResponse(
        success=result.success,
        strategy_id=result.strategy_id,
        from_mode=result.from_mode,
        to_mode=result.to_mode,
        message=result.message,
    )
