"""
src/agents/predictor.py — PredictorAgent MVP (Claude 단일 인스턴스 + 규칙 폴백)
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.db.models import AgentHeartbeatRecord, PredictionSignal
from src.db.queries import (
    fetch_recent_ohlcv,
    insert_heartbeat,
    insert_prediction,
    list_tickers,
    upsert_tournament_score,
)
from src.llm.claude_client import ClaudeClient
from src.llm.gemini_client import GeminiClient
from src.llm.gpt_client import GPTClient
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import TOPIC_SIGNALS, publish_message, set_heartbeat

setup_logging()
logger = get_logger(__name__)


class PredictorAgent:
    def __init__(
        self,
        agent_id: str = "predictor_1",
        strategy: str = "A",
        llm_model: str = "claude-3-5-sonnet-latest",
        persona: str = "MVP Claude 단일 인스턴스",
    ) -> None:
        self.agent_id = agent_id
        self.strategy = strategy
        self.llm_model = llm_model
        self.persona = persona
        self.claude = ClaudeClient(model=llm_model if "claude" in llm_model.lower() else "claude-3-5-sonnet-latest")
        self.gpt = GPTClient(model=llm_model if "gpt" in llm_model.lower() else "gpt-4o-mini")
        self.gemini = GeminiClient(model=llm_model if "gemini" in llm_model.lower() else "gemini-1.5-pro")

    @staticmethod
    def _rule_based_signal(candles: list[dict]) -> dict[str, Any]:
        if not candles:
            return {
                "signal": "HOLD",
                "confidence": 0.50,
                "reasoning_summary": "가격 이력 부족으로 HOLD",
                "target_price": None,
                "stop_loss": None,
            }

        closes = [int(c["close"]) for c in candles]
        latest = closes[0]
        short = sum(closes[:5]) / min(len(closes), 5)
        long = sum(closes[:20]) / min(len(closes), 20)

        if short > long * 1.01:
            signal = "BUY"
            confidence = 0.63
        elif short < long * 0.99:
            signal = "SELL"
            confidence = 0.61
        else:
            signal = "HOLD"
            confidence = 0.55

        return {
            "signal": signal,
            "confidence": confidence,
            "reasoning_summary": f"단기/장기 평균 비교 기반 규칙 신호 (short={short:.1f}, long={long:.1f})",
            "target_price": int(latest * 1.02) if signal == "BUY" else None,
            "stop_loss": int(latest * 0.97) if signal == "BUY" else None,
        }

    def _provider_name(self) -> str:
        model = self.llm_model.lower()
        if "gpt" in model:
            return "gpt"
        if "gemini" in model:
            return "gemini"
        return "claude"

    async def _llm_signal(self, ticker: str, candles: list[dict]) -> dict[str, Any]:
        fallback = self._rule_based_signal(candles)
        provider = self._provider_name()
        compact = [
            {
                "ts": str(c["timestamp_kst"]),
                "o": int(c["open"]),
                "h": int(c["high"]),
                "l": int(c["low"]),
                "c": int(c["close"]),
                "v": int(c["volume"]),
            }
            for c in candles[:20]
        ]
        prompt = f"""
너는 한국주식 단기 예측 분석가다.
티커: {ticker}
최근 데이터(최신순): {json.dumps(compact, ensure_ascii=False)}

아래 JSON 형식으로만 답해라:
{{
  "signal": "BUY|SELL|HOLD",
  "confidence": 0.0~1.0,
  "target_price": 정수 또는 null,
  "stop_loss": 정수 또는 null,
  "reasoning_summary": "한 줄 요약"
}}
"""
        try:
            if provider == "gpt" and self.gpt.is_configured:
                raw = await self.gpt.ask_json(prompt)
            elif provider == "gemini" and self.gemini.is_configured:
                raw = await self.gemini.ask_json(prompt)
            elif provider == "claude" and self.claude.is_configured:
                raw = await self.claude.ask_json(prompt)
            else:
                return fallback

            signal = str(raw.get("signal", "HOLD")).upper()
            if signal not in {"BUY", "SELL", "HOLD"}:
                signal = "HOLD"
            confidence = raw.get("confidence", fallback["confidence"])
            return {
                "signal": signal,
                "confidence": float(confidence) if confidence is not None else fallback["confidence"],
                "target_price": raw.get("target_price"),
                "stop_loss": raw.get("stop_loss"),
                "reasoning_summary": raw.get("reasoning_summary") or fallback["reasoning_summary"],
            }
        except Exception as e:
            logger.warning("%s 신호 생성 실패 [%s]: %s", provider, ticker, e)
            return fallback

    async def run_once(self, tickers: list[str] | None = None, limit: int = 10) -> list[PredictionSignal]:
        if tickers is None:
            ticker_rows = await list_tickers(limit=limit)
            tickers = [r["ticker"] for r in ticker_rows]

        results: list[PredictionSignal] = []
        for ticker in tickers:
            candles = await fetch_recent_ohlcv(ticker, days=30)
            llm_output = await self._llm_signal(ticker=ticker, candles=candles)

            signal = PredictionSignal(
                agent_id=self.agent_id,
                llm_model=self.llm_model,
                strategy=self.strategy,
                ticker=ticker,
                signal=llm_output["signal"],
                confidence=llm_output.get("confidence"),
                target_price=llm_output.get("target_price"),
                stop_loss=llm_output.get("stop_loss"),
                reasoning_summary=llm_output.get("reasoning_summary"),
                trading_date=date.today(),
            )
            await insert_prediction(signal)
            results.append(signal)

        if self.strategy == "A":
            await upsert_tournament_score(
                agent_id=self.agent_id,
                llm_model=self.llm_model,
                persona=self.persona,
                trading_date=date.today(),
                correct=0,
                total=0,
                is_winner=True,
            )

        await publish_message(
            TOPIC_SIGNALS,
            json.dumps(
                {
                    "type": "signals_ready",
                    "agent_id": self.agent_id,
                    "strategy": self.strategy,
                    "count": len(results),
                    "tickers": [s.ticker for s in results],
                    "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                },
                ensure_ascii=False,
            ),
        )

        await set_heartbeat(self.agent_id)
        await insert_heartbeat(
            AgentHeartbeatRecord(
                agent_id=self.agent_id,
                status="healthy",
                last_action=f"예측 완료 ({len(results)}종목)",
                metrics={"predictions": len(results), "strategy": self.strategy},
            )
        )
        logger.info("PredictorAgent 실행 완료: %d종목", len(results))
        return results


async def _main_async(args: argparse.Namespace) -> None:
    agent = PredictorAgent(
        agent_id=args.agent_id,
        strategy=args.strategy,
        llm_model=args.model,
    )
    tickers = args.tickers.split(",") if args.tickers else None
    await agent.run_once(tickers=tickers, limit=args.limit)


def main() -> None:
    parser = argparse.ArgumentParser(description="PredictorAgent MVP")
    parser.add_argument("--agent-id", default="predictor_1")
    parser.add_argument("--strategy", default="A", choices=["A", "B"])
    parser.add_argument("--model", default="claude-3-5-sonnet-latest")
    parser.add_argument("--tickers", default="", help="쉼표 구분 티커 목록")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
