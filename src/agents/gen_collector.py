"""
src/agents/gen_collector.py — GenCollectorAgent

Gen REST API에서 랜덤 시세 데이터를 가져와
기존 수집→저장 파이프라인(PostgreSQL, Redis, S3)에 주입합니다.

기존 CollectorAgent의 저장 함수를 그대로 재사용하여
파이프라인 정합성을 검증합니다.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.db.models import AgentHeartbeatRecord, MarketDataPoint
from src.db.queries import insert_heartbeat, upsert_market_data
from src.utils.logging import get_logger, setup_logging

# S3/Parquet 저장은 optional — datalake 모듈이 없으면 스킵
try:
    from src.services.datalake import store_daily_bars as _store_daily_bars
except ImportError:
    _store_daily_bars = None
from src.utils.redis_client import (
    KEY_LATEST_TICKS,
    KEY_REALTIME_SERIES,
    TOPIC_MARKET_DATA,
    TTL_REALTIME_SERIES,
    get_redis,
    publish_message,
    set_heartbeat,
)

setup_logging()
logger = get_logger(__name__)

KST = ZoneInfo("Asia/Seoul")


class GenCollectorAgent:
    """Gen API에서 데이터를 가져와 기존 파이프라인에 저장하는 에이전트.

    수집 경로:
        Gen Server (/gen/*) → GenCollectorAgent
            → PostgreSQL (market_data 테이블)
            → Redis (latest_ticks, realtime_series, pub/sub)
            → S3/MinIO (Parquet)
    """

    def __init__(
        self,
        gen_api_url: str = "http://localhost:9999",
        agent_id: str = "gen_collector_agent",
    ) -> None:
        self.gen_api_url = gen_api_url.rstrip("/")
        self.agent_id = agent_id
        self._client = httpx.AsyncClient(base_url=self.gen_api_url, timeout=15.0)
        self._last_hb_db_at: Optional[datetime] = None

    async def close(self) -> None:
        await self._client.aclose()

    async def _beat(self, status: str, last_action: str, metrics: dict, force_db: bool = False) -> None:
        await set_heartbeat(self.agent_id)
        now = datetime.utcnow()
        if force_db or self._last_hb_db_at is None or (now - self._last_hb_db_at).total_seconds() >= 30:
            await insert_heartbeat(
                AgentHeartbeatRecord(
                    agent_id=self.agent_id,
                    status=status,
                    last_action=last_action,
                    metrics=metrics,
                )
            )
            self._last_hb_db_at = now

    async def _cache_latest_tick(self, point: MarketDataPoint, source: str) -> None:
        """Redis에 최신 틱 캐시 + 시계열 기록."""
        redis = await get_redis()
        payload = {
            "ticker": point.ticker,
            "name": point.name,
            "current_price": point.close,
            "change_pct": point.change_pct,
            "volume": point.volume,
            "updated_at": point.timestamp_kst.isoformat(),
            "source": source,
        }
        encoded = json.dumps(payload, ensure_ascii=False)
        series_key = KEY_REALTIME_SERIES.format(ticker=point.ticker)

        pipe = redis.pipeline(transaction=False)
        pipe.set(KEY_LATEST_TICKS.format(ticker=point.ticker), encoded, ex=60)
        pipe.lpush(series_key, encoded)
        pipe.ltrim(series_key, 0, 299)
        pipe.expire(series_key, TTL_REALTIME_SERIES)
        await pipe.execute()

    # ── 수집 메서드: 일봉 ─────────────────────────────────────────────────────

    async def collect_daily_bars(self, lookback_days: int = 120) -> list[MarketDataPoint]:
        """Gen API에서 전 종목 일봉을 가져와 DB/Redis/S3에 저장합니다."""
        resp = await self._client.get("/gen/tickers")
        resp.raise_for_status()
        tickers = resp.json()

        all_points: list[MarketDataPoint] = []
        latest_points: list[MarketDataPoint] = []

        for t in tickers:
            ticker = t["ticker"]
            name = t["name"]
            market = t["market"]

            try:
                ohlcv_resp = await self._client.get(
                    f"/gen/ohlcv/{ticker}",
                    params={"days": lookback_days},
                )
                ohlcv_resp.raise_for_status()
                bars = ohlcv_resp.json()

                if not bars:
                    continue

                points: list[MarketDataPoint] = []
                for bar in bars:
                    ts = datetime.fromisoformat(bar["date"] + "T15:30:00")
                    ts = ts.replace(tzinfo=KST)
                    points.append(
                        MarketDataPoint(
                            ticker=ticker,
                            name=name,
                            market=market,
                            timestamp_kst=ts,
                            interval="daily",
                            open=bar["open"],
                            high=bar["high"],
                            low=bar["low"],
                            close=bar["close"],
                            volume=bar["volume"],
                            change_pct=bar["change_pct"],
                        )
                    )

                all_points.extend(points)
                if points:
                    latest_points.append(points[-1])

            except Exception as e:
                logger.warning("Gen 일봉 수집 실패 [%s]: %s", ticker, e)

        saved = await upsert_market_data(all_points)
        logger.info("GenCollector 일봉 DB 저장: %d건", saved)

        if _store_daily_bars is not None:
            try:
                s3_records = [p.model_dump() for p in all_points]
                await _store_daily_bars(s3_records)
                logger.info("GenCollector 일봉 S3 저장: %d건", len(s3_records))
            except Exception as e:
                logger.warning("GenCollector S3 저장 스킵: %s", e)
        else:
            logger.info("GenCollector S3 저장 스킵 (datalake 모듈 미설치)")

        for point in latest_points:
            await self._cache_latest_tick(point, source="gen_daily")

        await publish_message(
            TOPIC_MARKET_DATA,
            json.dumps(
                {
                    "type": "data_ready",
                    "agent_id": self.agent_id,
                    "count": saved,
                    "tickers": [p.ticker for p in latest_points[:20]],
                    "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                },
                ensure_ascii=False,
            ),
        )

        await self._beat(
            status="healthy",
            last_action=f"Gen 일봉 수집 완료 ({saved}건)",
            metrics={"collected_count": saved, "mode": "gen_daily", "tickers": len(tickers)},
            force_db=True,
        )

        return all_points

    # ── 수집 메서드: 실시간 틱 ─────────────────────────────────────────────────

    async def collect_realtime_ticks(self, interval_sec: float = 1.0, max_cycles: Optional[int] = None) -> int:
        """Gen API에서 현재가 스냅샷을 주기적으로 가져와 DB/Redis에 저장합니다."""
        total_received = 0
        cycle = 0

        while max_cycles is None or cycle < max_cycles:
            try:
                resp = await self._client.get("/gen/quotes")
                resp.raise_for_status()
                quotes = resp.json()

                now_kst = datetime.now(KST)
                points: list[MarketDataPoint] = []

                for q in quotes:
                    point = MarketDataPoint(
                        ticker=q["ticker"],
                        name=q["name"],
                        market=q["market"],
                        timestamp_kst=now_kst,
                        interval="tick",
                        open=q["open"],
                        high=q["high"],
                        low=q["low"],
                        close=q["current_price"],
                        volume=q["volume"],
                        change_pct=q["change_pct"],
                    )
                    points.append(point)

                saved = await upsert_market_data(points)

                for point in points:
                    await self._cache_latest_tick(point, source="gen_tick")

                for point in points:
                    await publish_message(
                        TOPIC_MARKET_DATA,
                        json.dumps(
                            {
                                "type": "tick",
                                "agent_id": self.agent_id,
                                "ticker": point.ticker,
                                "price": point.close,
                                "volume": point.volume,
                                "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                            },
                            ensure_ascii=False,
                        ),
                    )

                total_received += len(points)
                cycle += 1

                await self._beat(
                    status="healthy",
                    last_action=f"Gen 틱 수집중 (cycle={cycle}, total={total_received}건)",
                    metrics={"received_ticks": total_received, "mode": "gen_tick", "cycle": cycle},
                )

                if cycle % 10 == 0:
                    logger.info("GenCollector 틱 수집 진행: cycle=%d, total=%d건", cycle, total_received)

            except Exception as e:
                logger.warning("Gen 틱 수집 오류 (cycle=%d): %s", cycle, e)

            await asyncio.sleep(interval_sec)

        logger.info("GenCollector 틱 수집 완료: %d건 (%d cycles)", total_received, cycle)
        return total_received

    # ── 수집 메서드: 지수/매크로 ───────────────────────────────────────────────

    async def collect_indices_and_macro(self) -> dict:
        """Gen API에서 지수/매크로 데이터를 가져와 Redis에 캐시합니다."""
        redis = await get_redis()
        result = {"indices": 0, "macro": 0}

        try:
            resp = await self._client.get("/gen/index")
            resp.raise_for_status()
            indices = resp.json()
            for idx in indices:
                key = f"gen:index:{idx['symbol']}"
                await redis.set(key, json.dumps(idx, ensure_ascii=False), ex=120)
            result["indices"] = len(indices)

            resp = await self._client.get("/gen/macro")
            resp.raise_for_status()
            macros = resp.json()
            for m in macros:
                key = f"gen:macro:{m['symbol']}"
                await redis.set(key, json.dumps(m, ensure_ascii=False), ex=300)
            result["macro"] = len(macros)

        except Exception as e:
            logger.warning("Gen 지수/매크로 수집 실패: %s", e)

        return result

    # ── 통합 수집 사이클 ──────────────────────────────────────────────────────

    async def run_full_cycle(self, lookback_days: int = 120) -> dict:
        """일봉 + 현재가 + 지수/매크로를 한 번에 수집합니다."""
        logger.info("=== GenCollector 통합 수집 사이클 시작 ===")

        daily_points = await self.collect_daily_bars(lookback_days=lookback_days)
        logger.info("일봉 수집 완료: %d건", len(daily_points))

        tick_count = await self.collect_realtime_ticks(interval_sec=1.0, max_cycles=1)
        logger.info("틱 수집 완료: %d건", tick_count)

        idx_macro = await self.collect_indices_and_macro()
        logger.info("지수/매크로 수집 완료: %s", idx_macro)

        result = {
            "daily_bars_count": len(daily_points),
            "tick_count": tick_count,
            "indices_count": idx_macro["indices"],
            "macro_count": idx_macro["macro"],
        }
        logger.info("=== GenCollector 통합 수집 사이클 완료: %s ===", result)
        return result


# ── CLI ───────────────────────────────────────────────────────────────────────

async def _main_async() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="GenCollectorAgent")
    parser.add_argument("--gen-url", default="http://localhost:9999", help="Gen API 서버 URL")
    parser.add_argument("--mode", choices=["daily", "tick", "full", "continuous"], default="full", help="수집 모드")
    parser.add_argument("--lookback-days", type=int, default=120, help="일봉 lookback 기간")
    parser.add_argument("--tick-interval", type=float, default=1.0, help="틱 수집 주기 (초)")
    parser.add_argument("--tick-cycles", type=int, default=None, help="틱 수집 최대 횟수")
    args = parser.parse_args()

    agent = GenCollectorAgent(gen_api_url=args.gen_url)
    try:
        if args.mode == "daily":
            await agent.collect_daily_bars(lookback_days=args.lookback_days)
        elif args.mode == "tick":
            await agent.collect_realtime_ticks(
                interval_sec=args.tick_interval,
                max_cycles=args.tick_cycles,
            )
        elif args.mode == "continuous":
            await agent.collect_daily_bars(lookback_days=args.lookback_days)
            logger.info("일봉 수집 완료, 틱 수집 무한 루프 시작...")
            await agent.collect_realtime_ticks(
                interval_sec=args.tick_interval,
                max_cycles=args.tick_cycles,
            )
        else:
            await agent.run_full_cycle(lookback_days=args.lookback_days)
    finally:
        await agent.close()


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
