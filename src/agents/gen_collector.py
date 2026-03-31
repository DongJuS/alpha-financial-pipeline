"""
src/agents/gen_collector.py — GenCollectorAgent

Gen REST API에서 랜덤 시세 데이터를 가져와
수집→저장 파이프라인(PostgreSQL, Redis, S3)에 주입합니다.

마이그레이션 기간 동안 ohlcv_daily(신규)와 market_data(레거시) 양쪽에 듀얼 라이트합니다.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.db.models import AgentHeartbeatRecord, MarketDataPoint
from src.db.queries import insert_heartbeat
from src.utils.db_client import executemany
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
    """Gen API에서 데이터를 가져와 파이프라인에 저장하는 에이전트.

    수집 경로:
        Gen Server (/gen/*) → GenCollectorAgent
            → PostgreSQL (ohlcv_daily 신규 + market_data 레거시 듀얼라이트)
            → Redis (latest_ticks, realtime_series, pub/sub)
            → S3/MinIO (Parquet)
    """

    def __init__(
        self,
        gen_api_url: str = os.environ.get("GEN_API_URL", "http://localhost:9999"),
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
        raw_code = point.ticker  # instrument_id에서 raw_code 추출 (@property)
        payload = {
            "ticker": raw_code,
            "instrument_id": point.instrument_id,
            "name": point.name,
            "current_price": point.close,
            "change_pct": point.change_pct,
            "volume": point.volume,
            "updated_at": str(point.traded_at),
            "source": source,
        }
        encoded = json.dumps(payload, ensure_ascii=False)
        series_key = KEY_REALTIME_SERIES.format(ticker=raw_code)

        pipe = redis.pipeline(transaction=False)
        pipe.set(KEY_LATEST_TICKS.format(ticker=raw_code), encoded, ex=60)
        pipe.lpush(series_key, encoded)
        pipe.ltrim(series_key, 0, 299)
        pipe.expire(series_key, TTL_REALTIME_SERIES)
        await pipe.execute()

    # ── 수집 메서드: 일봉 ─────────────────────────────────────────────────────

    @staticmethod
    def _make_instrument_id(raw_code: str, market: str) -> str:
        """raw_code + market → instrument_id (예: 005930.KS)."""
        suffix = "KS" if market.upper() == "KOSPI" else "KQ"
        return f"{raw_code}.{suffix}"

    async def collect_daily_bars(self, lookback_days: int = 120) -> list[MarketDataPoint]:
        """Gen API에서 전 종목 일봉을 가져와 DB/Redis/S3에 저장합니다."""
        resp = await self._client.get("/gen/tickers")
        resp.raise_for_status()
        tickers = resp.json()

        all_points: list[MarketDataPoint] = []
        latest_points: list[MarketDataPoint] = []

        for t in tickers:
            raw_code = t["ticker"]
            name = t["name"]
            market = t["market"]
            instrument_id = self._make_instrument_id(raw_code, market)

            try:
                ohlcv_resp = await self._client.get(
                    f"/gen/ohlcv/{raw_code}",
                    params={"days": lookback_days},
                )
                ohlcv_resp.raise_for_status()
                bars = ohlcv_resp.json()

                if not bars:
                    continue

                points: list[MarketDataPoint] = []
                for bar in bars:
                    traded_at = date.fromisoformat(bar["date"])
                    points.append(
                        MarketDataPoint(
                            instrument_id=instrument_id,
                            name=name,
                            market=market,
                            traded_at=traded_at,
                            open=float(bar["open"]),
                            high=float(bar["high"]),
                            low=float(bar["low"]),
                            close=float(bar["close"]),
                            volume=int(bar["volume"]),
                            change_pct=bar["change_pct"],
                        )
                    )

                all_points.extend(points)
                if points:
                    latest_points.append(points[-1])

            except Exception as e:
                logger.warning("Gen 일봉 수집 실패 [%s]: %s", raw_code, e)

        # Gen 데이터는 ohlcv_daily(실제 시세)를 덮어쓰지 않음.
        # 레거시 market_data에만 저장 (Gen 테스트용)
        try:
            await self._dual_write_legacy(all_points)
            logger.info("GenCollector 일봉 market_data 저장: %d건", len(all_points))
        except Exception as e:
            logger.warning("GenCollector market_data 저장 실패: %s", e)
        saved = len(all_points)

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
        """Gen API에서 현재가 스냅샷을 주기적으로 가져와 DB/Redis에 저장합니다.

        ohlcv_daily는 일봉 전용이므로 실시간 틱은 당일 날짜로 upsert합니다.
        레거시 market_data에도 듀얼라이트합니다.
        """
        total_received = 0
        cycle = 0

        while max_cycles is None or cycle < max_cycles:
            try:
                resp = await self._client.get("/gen/quotes")
                resp.raise_for_status()
                quotes = resp.json()

                today = datetime.now(KST).date()
                points: list[MarketDataPoint] = []

                for q in quotes:
                    raw_code = q["ticker"]
                    market = q["market"]
                    instrument_id = self._make_instrument_id(raw_code, market)
                    point = MarketDataPoint(
                        instrument_id=instrument_id,
                        name=q["name"],
                        market=market,
                        traded_at=today,
                        open=float(q["open"]),
                        high=float(q["high"]),
                        low=float(q["low"]),
                        close=float(q["current_price"]),
                        volume=int(q["volume"]),
                        change_pct=q["change_pct"],
                    )
                    points.append(point)

                # Gen 틱 데이터는 ohlcv_daily(실제 시세)를 덮어쓰지 않음.
                # 레거시 market_data에만 저장
                try:
                    await self._dual_write_legacy_tick(points)
                except Exception as e:
                    logger.debug("레거시 tick 저장 실패 (무시): %s", e)

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

    # ── 레거시 market_data 듀얼라이트 ──────────────────────────────────────────

    async def _dual_write_legacy(self, points: list[MarketDataPoint]) -> int:
        """마이그레이션 기간: 레거시 market_data 테이블에도 기록합니다."""
        if not points:
            return 0
        query = """
            INSERT INTO market_data (
                ticker, name, market, timestamp_kst, interval,
                open, high, low, close, volume, change_pct
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10, $11
            )
            ON CONFLICT (ticker, timestamp_kst, interval)
            DO UPDATE SET
                name = EXCLUDED.name,
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                change_pct = EXCLUDED.change_pct
        """
        rows: list[tuple[Any, ...]] = []
        for p in points:
            ts = datetime(
                p.traded_at.year, p.traded_at.month, p.traded_at.day,
                15, 30, 0, tzinfo=KST,
            )
            rows.append((
                p.ticker, p.name, p.market, ts, "daily",
                int(p.open), int(p.high), int(p.low), int(p.close),
                p.volume, p.change_pct,
            ))
        await executemany(query, rows)
        logger.info("GenCollector 레거시 market_data 듀얼라이트: %d건", len(rows))
        return len(rows)

    async def _dual_write_legacy_tick(self, points: list[MarketDataPoint]) -> int:
        """마이그레이션 기간: 실시간 틱을 레거시 market_data에 기록합니다."""
        if not points:
            return 0
        query = """
            INSERT INTO market_data (
                ticker, name, market, timestamp_kst, interval,
                open, high, low, close, volume, change_pct
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10, $11
            )
            ON CONFLICT (ticker, timestamp_kst, interval)
            DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                change_pct = EXCLUDED.change_pct
        """
        now_kst = datetime.now(KST)
        rows: list[tuple[Any, ...]] = []
        for p in points:
            rows.append((
                p.ticker, p.name, p.market, now_kst, "tick",
                int(p.open), int(p.high), int(p.low), int(p.close),
                p.volume, p.change_pct,
            ))
        await executemany(query, rows)
        return len(rows)

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
    parser.add_argument("--gen-url", default=os.environ.get("GEN_API_URL", "http://localhost:9999"), help="Gen API 서버 URL")
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
