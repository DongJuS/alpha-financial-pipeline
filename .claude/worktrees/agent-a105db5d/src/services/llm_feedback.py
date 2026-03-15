"""
src/services/llm_feedback.py — LLM 예측 피드백 루프

S3 Data Lake에서 과거 예측 시그널 + 실제 결과를 읽어
LLM 프롬프트에 주입할 '과거 성과 컨텍스트'를 자동 생성합니다.

핵심 흐름:
    1. datalake_reader로 최근 N일 predictions + daily_bars 로드
    2. 예측 정확도, P&L, 과오류 패턴을 분석
    3. LLM 프롬프트에 주입할 구조화된 피드백 문자열 생성
    4. PredictorAgent가 매 실행 시 이 컨텍스트를 프롬프트에 포함

사용 예:
    context = await build_feedback_context("predictor_1", "A", lookback_days=14)
    prompt = f"{context}\n\n너는 한국주식 단기 예측 분석가다..."
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TickerFeedback:
    """종목별 피드백 요약."""
    ticker: str
    total: int = 0
    correct: int = 0
    incorrect: int = 0
    avg_pnl_pct: float = 0.0
    buy_accuracy: float = 0.0
    sell_accuracy: float = 0.0
    common_errors: list[str] = field(default_factory=list)


@dataclass
class StrategyFeedback:
    """전략/에이전트 단위 피드백 요약."""
    agent_id: str
    strategy: str
    period_start: str
    period_end: str
    total_predictions: int = 0
    evaluated_predictions: int = 0
    overall_accuracy: float = 0.0
    avg_pnl_pct: float = 0.0
    best_tickers: list[str] = field(default_factory=list)
    worst_tickers: list[str] = field(default_factory=list)
    signal_bias: dict[str, float] = field(default_factory=dict)
    error_patterns: list[str] = field(default_factory=list)
    ticker_details: list[TickerFeedback] = field(default_factory=list)


async def _load_prediction_outcomes(
    start: date,
    end: date,
    strategy: str | None = None,
) -> list[dict[str, Any]]:
    """S3에서 예측+결과 매칭 데이터를 로드합니다."""
    from src.services.datalake_reader import load_predictions_with_outcomes

    records = await load_predictions_with_outcomes(start, end)

    if strategy:
        records = [r for r in records if r.get("strategy") == strategy]

    return records


def _analyze_error_patterns(records: list[dict[str, Any]]) -> list[str]:
    """공통 오류 패턴을 식별합니다."""
    patterns: list[str] = []

    # 1. BUY 편향 체크
    buy_count = sum(1 for r in records if r.get("signal") == "BUY")
    sell_count = sum(1 for r in records if r.get("signal") == "SELL")
    total = len(records)
    if total > 0:
        buy_ratio = buy_count / total
        if buy_ratio > 0.7:
            patterns.append(f"BUY 편향 심각 ({buy_ratio:.0%}): 매수 시그널이 과도하게 많음")
        elif sell_count > 0 and buy_count / max(sell_count, 1) > 3:
            patterns.append(f"BUY/SELL 비율 불균형 ({buy_count}:{sell_count})")

    # 2. 과도한 자신감 체크
    high_conf_wrong = [
        r for r in records
        if r.get("was_correct") is False
        and (r.get("confidence") or 0) > 0.8
    ]
    if len(high_conf_wrong) > 3:
        patterns.append(
            f"높은 자신감(>80%) 예측이 {len(high_conf_wrong)}회 틀림 — 자신감 보정 필요"
        )

    # 3. 특정 종목 반복 실패
    ticker_fails: dict[str, int] = defaultdict(int)
    for r in records:
        if r.get("was_correct") is False:
            ticker_fails[r.get("ticker", "")] += 1

    repeat_failures = [(t, c) for t, c in ticker_fails.items() if c >= 3]
    for t, c in sorted(repeat_failures, key=lambda x: -x[1])[:3]:
        patterns.append(f"{t} 종목 반복 실패 ({c}회): 해당 종목 특성 재분석 필요")

    # 4. 연속 실패 체크
    sorted_recs = sorted(
        [r for r in records if r.get("was_correct") is not None],
        key=lambda r: r.get("pred_date", ""),
    )
    max_streak = 0
    streak = 0
    for r in sorted_recs:
        if r.get("was_correct") is False:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    if max_streak >= 5:
        patterns.append(f"연속 {max_streak}회 실패 구간 존재 — 시장 국면 전환 미감지 가능성")

    # 5. HOLD 남발 체크
    hold_count = sum(1 for r in records if r.get("signal") == "HOLD")
    if total > 0 and hold_count / total > 0.5:
        patterns.append(f"HOLD 비율 과다 ({hold_count / total:.0%}): 의사결정 회피 경향")

    return patterns


def _compute_signal_bias(records: list[dict[str, Any]]) -> dict[str, float]:
    """시그널별 발생 비율을 계산합니다."""
    total = len(records)
    if total == 0:
        return {}

    counts: dict[str, int] = defaultdict(int)
    for r in records:
        sig = str(r.get("signal", "HOLD")).upper()
        counts[sig] += 1

    return {sig: round(cnt / total, 3) for sig, cnt in sorted(counts.items())}


async def analyze_performance(
    start: date,
    end: date,
    strategy: str | None = None,
    agent_id: str | None = None,
) -> StrategyFeedback:
    """기간별 성과를 분석하여 StrategyFeedback을 반환합니다."""
    records = await _load_prediction_outcomes(start, end, strategy=strategy)

    if agent_id:
        records = [r for r in records if r.get("agent_id") == agent_id]

    evaluated = [r for r in records if r.get("was_correct") is not None]
    correct = [r for r in evaluated if r["was_correct"]]
    pnl_values = [r["pnl_pct"] for r in evaluated if r.get("pnl_pct") is not None]

    # 종목별 분석
    ticker_map: dict[str, list[dict]] = defaultdict(list)
    for r in evaluated:
        ticker_map[r.get("ticker", "")].append(r)

    ticker_details: list[TickerFeedback] = []
    for ticker, recs in ticker_map.items():
        t_correct = sum(1 for r in recs if r["was_correct"])
        t_incorrect = len(recs) - t_correct
        t_pnl = [r["pnl_pct"] for r in recs if r.get("pnl_pct") is not None]

        buy_recs = [r for r in recs if r.get("signal") == "BUY"]
        sell_recs = [r for r in recs if r.get("signal") == "SELL"]
        buy_acc = sum(1 for r in buy_recs if r["was_correct"]) / len(buy_recs) if buy_recs else 0.0
        sell_acc = sum(1 for r in sell_recs if r["was_correct"]) / len(sell_recs) if sell_recs else 0.0

        ticker_details.append(TickerFeedback(
            ticker=ticker,
            total=len(recs),
            correct=t_correct,
            incorrect=t_incorrect,
            avg_pnl_pct=round(sum(t_pnl) / len(t_pnl), 4) if t_pnl else 0.0,
            buy_accuracy=round(buy_acc, 4),
            sell_accuracy=round(sell_acc, 4),
        ))

    # 종목 정렬: 수익률 기준
    ticker_details.sort(key=lambda t: t.avg_pnl_pct, reverse=True)
    best = [t.ticker for t in ticker_details[:3] if t.avg_pnl_pct > 0]
    worst = [t.ticker for t in ticker_details[-3:] if t.avg_pnl_pct < 0]

    return StrategyFeedback(
        agent_id=agent_id or "all",
        strategy=strategy or "all",
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        total_predictions=len(records),
        evaluated_predictions=len(evaluated),
        overall_accuracy=round(len(correct) / len(evaluated), 4) if evaluated else 0.0,
        avg_pnl_pct=round(sum(pnl_values) / len(pnl_values), 4) if pnl_values else 0.0,
        best_tickers=best,
        worst_tickers=worst,
        signal_bias=_compute_signal_bias(records),
        error_patterns=_analyze_error_patterns(records),
        ticker_details=ticker_details,
    )


def format_feedback_for_prompt(feedback: StrategyFeedback) -> str:
    """StrategyFeedback을 LLM 프롬프트에 주입할 문자열로 변환합니다.

    이 문자열은 PredictorAgent._llm_signal()의 프롬프트 앞에 삽입됩니다.
    """
    lines: list[str] = []
    lines.append("=== 과거 성과 피드백 (자동 생성) ===")
    lines.append(f"분석 기간: {feedback.period_start} ~ {feedback.period_end}")
    lines.append(
        f"전체 정확도: {feedback.overall_accuracy:.1%} "
        f"({feedback.evaluated_predictions}건 평가, "
        f"평균 P&L: {feedback.avg_pnl_pct:+.2f}%)"
    )

    if feedback.signal_bias:
        bias_str = ", ".join(f"{k}: {v:.0%}" for k, v in feedback.signal_bias.items())
        lines.append(f"시그널 분포: {bias_str}")

    if feedback.best_tickers:
        lines.append(f"성과 우수 종목: {', '.join(feedback.best_tickers)}")
    if feedback.worst_tickers:
        lines.append(f"성과 부진 종목: {', '.join(feedback.worst_tickers)} — 해당 종목은 특히 신중하게 판단하라")

    if feedback.error_patterns:
        lines.append("\n[개선 지침]")
        for i, pattern in enumerate(feedback.error_patterns, 1):
            lines.append(f"  {i}. {pattern}")

    # 상위 종목 상세 (최대 5개)
    if feedback.ticker_details:
        lines.append("\n[종목별 정확도 (최근)]")
        for td in feedback.ticker_details[:5]:
            lines.append(
                f"  {td.ticker}: 정확도 {td.correct}/{td.total} "
                f"(BUY {td.buy_accuracy:.0%}, SELL {td.sell_accuracy:.0%}), "
                f"평균 P&L {td.avg_pnl_pct:+.2f}%"
            )

    lines.append("=== 피드백 끝 ===\n")
    return "\n".join(lines)


async def build_feedback_context(
    agent_id: str | None = None,
    strategy: str | None = None,
    lookback_days: int = 14,
) -> str:
    """PredictorAgent가 사용할 피드백 컨텍스트 문자열을 생성합니다.

    S3에서 최근 lookback_days 기간의 예측+결과를 분석하고,
    프롬프트에 주입할 형태로 반환합니다.

    데이터가 없거나 오류 시 빈 문자열을 반환합니다 (graceful degradation).
    """
    try:
        end = date.today() - timedelta(days=1)  # 어제까지 (오늘은 아직 미확정)
        start = end - timedelta(days=lookback_days)

        feedback = await analyze_performance(
            start=start,
            end=end,
            strategy=strategy,
            agent_id=agent_id,
        )

        if feedback.evaluated_predictions < 3:
            logger.info("피드백 데이터 부족 (%d건) — 프롬프트 주입 생략", feedback.evaluated_predictions)
            return ""

        context = format_feedback_for_prompt(feedback)
        logger.info(
            "LLM 피드백 컨텍스트 생성: %s/%s, 정확도 %.1f%%, %d건 평가",
            agent_id, strategy,
            feedback.overall_accuracy * 100,
            feedback.evaluated_predictions,
        )
        return context

    except Exception:
        logger.warning("LLM 피드백 컨텍스트 생성 실패 (비필수)", exc_info=True)
        return ""
