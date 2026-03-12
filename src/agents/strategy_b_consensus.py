"""
src/agents/strategy_b_consensus.py — Strategy B Consensus/Debate Runner

- Proposer / Challenger / Synthesizer 구조
- 다라운드 토론 + 합의 임계치 기반 의사결정
- debate_transcripts 저장 + strategy B predictions 기록
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date, datetime
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.db.models import PredictionSignal
from src.db.queries import fetch_recent_ohlcv, insert_debate_transcript, insert_prediction
from src.llm.claude_client import ClaudeClient
from src.llm.gemini_client import GeminiClient
from src.llm.gpt_client import GPTClient
from src.utils.config import get_settings
from src.utils.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@dataclass
class DebateResult:
    signal: str
    confidence: float
    proposer: str
    challenger1: str
    challenger2: str
    synthesizer: str
    consensus_reached: bool
    no_consensus_reason: str | None = None


class StrategyBConsensus:
    def __init__(
        self,
        max_rounds: int | None = None,
        consensus_threshold: float | None = None,
    ) -> None:
        settings = get_settings()
        self.claude = ClaudeClient(model="claude-3-5-sonnet-latest")
        self.gpt = GPTClient(model="gpt-4o-mini")
        self.gemini = GeminiClient(model="gemini-1.5-pro")
        default_rounds = settings.strategy_b_max_rounds
        default_threshold = settings.strategy_b_consensus_threshold
        self.max_rounds = max(1, int(max_rounds if max_rounds is not None else default_rounds))
        threshold = float(
            consensus_threshold if consensus_threshold is not None else default_threshold
        )
        self.consensus_threshold = max(0.0, min(1.0, threshold))

    @staticmethod
    def _clamp_confidence(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _rule_signal(candles: list[dict]) -> tuple[str, float, str]:
        if not candles:
            return "HOLD", 0.5, "데이터 부족"
        closes = [int(c["close"]) for c in candles[:20]]
        latest = closes[0]
        avg5 = sum(closes[:5]) / min(5, len(closes))
        avg20 = sum(closes) / len(closes)
        if avg5 > avg20 * 1.01:
            return "BUY", 0.62, f"단기 평균({avg5:.1f})이 장기 평균({avg20:.1f}) 상회"
        if avg5 < avg20 * 0.99:
            return "SELL", 0.61, f"단기 평균({avg5:.1f})이 장기 평균({avg20:.1f}) 하회"
        return "HOLD", 0.55, f"평균 근접 구간(현재가 {latest})"

    async def _propose(
        self,
        ticker: str,
        candles: list[dict],
        round_no: int,
        prior_context: str | None = None,
    ) -> dict[str, Any]:
        fallback_signal, fallback_conf, fallback_reason = self._rule_signal(candles)
        if not self.claude.is_configured:
            return {
                "signal": fallback_signal,
                "confidence": self._clamp_confidence(fallback_conf),
                "argument": f"[round {round_no} fallback] {fallback_reason}",
            }

        compact = [
            {"c": int(c["close"]), "v": int(c["volume"]), "ts": str(c["timestamp_kst"])}
            for c in candles[:20]
        ]
        prior = f"\n이전 라운드 요약: {prior_context}\n" if prior_context else "\n"
        prompt = f"""
라운드: {round_no}
티커 {ticker}의 최근 데이터: {json.dumps(compact, ensure_ascii=False)}
{prior}
BUY/SELL/HOLD 중 하나를 선택하고 JSON으로 답해라:
{{
  "signal": "BUY|SELL|HOLD",
  "confidence": 0.0~1.0,
  "argument": "핵심 근거 한 문단"
}}
"""
        try:
            data = await self.claude.ask_json(prompt)
            signal = str(data.get("signal", "HOLD")).upper()
            if signal not in {"BUY", "SELL", "HOLD"}:
                signal = "HOLD"
            confidence = self._clamp_confidence(float(data.get("confidence", fallback_conf)))
            return {
                "signal": signal,
                "confidence": confidence,
                "argument": data.get("argument", fallback_reason),
            }
        except Exception as e:
            logger.warning("proposer 실패 [%s]: %s", ticker, e)
            return {
                "signal": fallback_signal,
                "confidence": self._clamp_confidence(fallback_conf),
                "argument": f"[round {round_no} fallback] {fallback_reason}",
            }

    async def _challenge(
        self,
        role: str,
        ticker: str,
        proposer: dict[str, Any],
        use_client: str,
        round_no: int,
    ) -> str:
        prompt = f"""
라운드: {round_no}
역할: {role}
티커: {ticker}
Proposer 주장: {json.dumps(proposer, ensure_ascii=False)}
반론을 2~3문장으로 작성해라.
"""

        provider_order = [use_client] + [p for p in ("gpt", "gemini", "claude") if p != use_client]
        for provider in provider_order:
            try:
                if provider == "gpt" and self.gpt.is_configured:
                    return await self.gpt.ask(prompt)
                if provider == "gemini" and self.gemini.is_configured:
                    return await self.gemini.ask(prompt)
                if provider == "claude" and self.claude.is_configured:
                    return await self.claude.ask(prompt)
            except Exception as e:
                logger.warning("%s challenger 실패 [%s]: %s", provider, ticker, e)

        return (
            f"[round {round_no} fallback-{role}] proposer 신호({proposer['signal']})는 "
            "변동성 및 리스크 요인을 추가 검토해야 함."
        )

    async def _synthesize(
        self,
        ticker: str,
        proposer: dict[str, Any],
        challenger1: str,
        challenger2: str,
        round_no: int,
    ) -> DebateResult:
        fallback_signal = proposer["signal"]
        fallback_conf = self._clamp_confidence(float(proposer.get("confidence", 0.55)))
        fallback_consensus = fallback_conf >= self.consensus_threshold

        if self.claude.is_configured:
            prompt = f"""
라운드: {round_no}
티커: {ticker}
proposer: {json.dumps(proposer, ensure_ascii=False)}
challenger1: {challenger1}
challenger2: {challenger2}

아래 임계치 기준을 반드시 적용해 최종 결론을 JSON으로 출력:
- consensus_threshold: {self.consensus_threshold:.2f}
- confidence가 임계치보다 낮으면 consensus_reached=false

{{
  "final_signal": "BUY|SELL|HOLD",
  "confidence": 0.0~1.0,
  "consensus_reached": true/false,
  "summary": "종합 근거",
  "no_consensus_reason": "string | null"
}}
"""
            try:
                data = await self.claude.ask_json(prompt)
                signal = str(data.get("final_signal", fallback_signal)).upper()
                if signal not in {"BUY", "SELL", "HOLD"}:
                    signal = "HOLD"
                conf = self._clamp_confidence(float(data.get("confidence", fallback_conf)))
                llm_consensus = bool(data.get("consensus_reached", fallback_consensus))
                consensus = llm_consensus and conf >= self.consensus_threshold
                summary = data.get("summary", "종합 판단")
                no_reason = data.get("no_consensus_reason")
                if not consensus:
                    no_reason = no_reason or (
                        "confidence_below_threshold"
                        if conf < self.consensus_threshold
                        else "consensus_not_reached"
                    )
                return DebateResult(
                    signal=signal,
                    confidence=conf,
                    proposer=proposer["argument"],
                    challenger1=challenger1,
                    challenger2=challenger2,
                    synthesizer=summary,
                    consensus_reached=consensus,
                    no_consensus_reason=None if consensus else no_reason,
                )
            except Exception as e:
                logger.warning("synthesizer 실패 [%s]: %s", ticker, e)

        signal = fallback_signal if fallback_consensus else "HOLD"
        summary = "fallback 합의 결과"
        no_reason = None
        if not fallback_consensus:
            no_reason = (
                "confidence_below_threshold"
                if fallback_conf < self.consensus_threshold
                else "fallback_no_consensus"
            )
        return DebateResult(
            signal=signal,
            confidence=fallback_conf,
            proposer=proposer["argument"],
            challenger1=challenger1,
            challenger2=challenger2,
            synthesizer=summary,
            consensus_reached=fallback_consensus,
            no_consensus_reason=no_reason,
        )

    async def run_for_ticker(self, ticker: str) -> PredictionSignal:
        started = datetime.utcnow()
        candles = await fetch_recent_ohlcv(ticker=ticker, days=30)
        prior_context: str | None = None
        round_payloads: list[dict[str, Any]] = []
        synthesis: DebateResult | None = None

        for round_no in range(1, self.max_rounds + 1):
            proposer = await self._propose(
                ticker=ticker,
                candles=candles,
                round_no=round_no,
                prior_context=prior_context,
            )
            challenger1 = await self._challenge(
                "Challenger1",
                ticker,
                proposer,
                use_client="gpt",
                round_no=round_no,
            )
            challenger2 = await self._challenge(
                "Challenger2",
                ticker,
                proposer,
                use_client="gemini",
                round_no=round_no,
            )
            synthesis = await self._synthesize(
                ticker=ticker,
                proposer=proposer,
                challenger1=challenger1,
                challenger2=challenger2,
                round_no=round_no,
            )
            round_payloads.append(
                {
                    "round": round_no,
                    "proposer": proposer["argument"],
                    "challenger1": challenger1,
                    "challenger2": challenger2,
                    "synthesizer": synthesis.synthesizer,
                    "signal": synthesis.signal,
                    "confidence": synthesis.confidence,
                    "consensus_reached": synthesis.consensus_reached,
                    "no_consensus_reason": synthesis.no_consensus_reason,
                }
            )
            if synthesis.consensus_reached:
                break
            prior_context = (
                f"round={round_no}, signal={synthesis.signal}, conf={synthesis.confidence:.3f}, "
                f"consensus={synthesis.consensus_reached}, "
                f"reason={synthesis.no_consensus_reason or 'n/a'}, "
                f"synthesis={synthesis.synthesizer}"
            )

        if synthesis is None:
            synthesis = DebateResult(
                signal="HOLD",
                confidence=0.0,
                proposer="데이터 부족",
                challenger1="데이터 부족",
                challenger2="데이터 부족",
                synthesizer="합의 결과 없음",
                consensus_reached=False,
                no_consensus_reason="empty_round_execution",
            )
            round_payloads.append(
                {
                    "round": 1,
                    "proposer": synthesis.proposer,
                    "challenger1": synthesis.challenger1,
                    "challenger2": synthesis.challenger2,
                    "synthesizer": synthesis.synthesizer,
                    "signal": synthesis.signal,
                    "confidence": synthesis.confidence,
                    "consensus_reached": synthesis.consensus_reached,
                    "no_consensus_reason": synthesis.no_consensus_reason,
                }
            )

        actual_rounds = len(round_payloads)
        final_signal = synthesis.signal if synthesis.consensus_reached else "HOLD"
        final_no_consensus_reason = synthesis.no_consensus_reason
        if not synthesis.consensus_reached and not final_no_consensus_reason:
            final_no_consensus_reason = "max_rounds_exhausted"

        proposer_text = "\n\n".join(
            [f"[Round {p['round']}] {p['proposer']}" for p in round_payloads]
        )
        challenger1_text = "\n\n".join(
            [f"[Round {p['round']}] {p['challenger1']}" for p in round_payloads]
        )
        challenger2_text = "\n\n".join(
            [f"[Round {p['round']}] {p['challenger2']}" for p in round_payloads]
        )
        synthesizer_text = "\n\n".join(
            [
                (
                    f"[Round {p['round']}] signal={p['signal']} "
                    f"conf={float(p['confidence']):.3f} "
                    f"consensus={p['consensus_reached']} "
                    f"reason={p['no_consensus_reason'] or 'n/a'}\n"
                    f"{p['synthesizer']}"
                )
                for p in round_payloads
            ]
        )
        synthesizer_text += (
            f"\n\n[Policy] max_rounds={self.max_rounds}, "
            f"consensus_threshold={self.consensus_threshold:.2f}"
        )

        duration = int((datetime.utcnow() - started).total_seconds())
        transcript_id = await insert_debate_transcript(
            trading_date=date.today(),
            ticker=ticker,
            rounds=actual_rounds,
            consensus_reached=synthesis.consensus_reached,
            final_signal=final_signal,
            confidence=synthesis.confidence,
            proposer_content=proposer_text,
            challenger1_content=challenger1_text,
            challenger2_content=challenger2_text,
            synthesizer_content=synthesizer_text,
            no_consensus_reason=final_no_consensus_reason,
            duration_seconds=duration,
        )

        signal = PredictionSignal(
            agent_id="consensus_synthesizer",
            llm_model="claude-3-5-sonnet-latest",
            strategy="B",
            ticker=ticker,
            signal=final_signal,
            confidence=synthesis.confidence,
            target_price=None,
            stop_loss=None,
            reasoning_summary=(
                f"(rounds={actual_rounds}/{self.max_rounds}, "
                f"threshold={self.consensus_threshold:.2f}, "
                f"consensus={synthesis.consensus_reached}) {synthesis.synthesizer}"
            ),
            debate_transcript_id=transcript_id,
            trading_date=date.today(),
        )
        await insert_prediction(signal)
        return signal

    async def run(self, tickers: list[str]) -> list[PredictionSignal]:
        tasks = [self.run_for_ticker(t) for t in tickers]
        return await asyncio.gather(*tasks)


async def _main_async(args: argparse.Namespace) -> None:
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    runner = StrategyBConsensus(
        max_rounds=args.max_rounds,
        consensus_threshold=args.consensus_threshold,
    )
    results = await runner.run(tickers)
    print([r.model_dump() for r in results])


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy B Consensus Runner")
    parser.add_argument("--tickers", required=True, help="쉼표 구분 티커 목록")
    parser.add_argument("--max-rounds", type=int, default=None, help="최대 토론 라운드 수(기본: 설정값)")
    parser.add_argument(
        "--consensus-threshold",
        type=float,
        default=None,
        help="합의 confidence 임계치(0.0~1.0, 기본: 설정값)",
    )
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
