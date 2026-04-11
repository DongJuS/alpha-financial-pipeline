"""src/agents/collector/_base.py — CollectorAgent 공통 베이스 클래스."""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
import sys
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.db.models import AgentHeartbeatRecord, MarketDataPoint
from src.db.queries import insert_heartbeat
from src.utils.config import get_settings, has_kis_credentials, kis_app_key_for_scope, kis_app_secret_for_scope
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import (
    KEY_LATEST_TICKS,
    KEY_REALTIME_SERIES,
    TTL_KIS_APPROVAL_KEY,
    TTL_REALTIME_SERIES,
    get_redis,
    kis_approval_key,
    kis_oauth_token_key,
    set_heartbeat,
)

setup_logging()
logger = get_logger(__name__)

KST = ZoneInfo("Asia/Seoul")


class _CollectorBase:
    def __init__(self, agent_id: str = "collector_agent") -> None:
        self.agent_id = agent_id
        self.settings = get_settings()
        self._last_hb_db_at: Optional[datetime] = None
        # 실시간 틱 버퍼 (건별 INSERT 대신 배치 flush)
        self._tick_buffer: list = []  # TickData 리스트 (순환참조 방지를 위해 타입 생략)
        self._tick_buffer_last_flush: float = 0.0
        self._tick_batch_size: int = self.settings.ws_tick_batch_size
        self._tick_flush_interval: float = self.settings.ws_tick_flush_interval
        self._last_tick_at: datetime | None = None  # 마지막 수신 틱 시각
        self._realtime_task: asyncio.Task | None = None  # 스케줄러 헬스체크용

    def _account_scope(self) -> str:
        return "paper" if self.settings.kis_is_paper_trading else "real"

    def _has_kis_market_credentials(self) -> bool:
        return has_kis_credentials(
            self.settings,
            self._account_scope(),
            require_account_number=False,
        )

    @staticmethod
    def _load_fdr():
        import FinanceDataReader as fdr

        return fdr

    async def _beat(self, status: str, last_action: str, metrics: dict, force_db: bool = False) -> None:
        hb_status = {"healthy": "ok", "degraded": "degraded", "error": "error"}.get(status, status)
        hb_kwargs: dict[str, str | int | float] = {"mode": metrics.get("mode", "idle")}
        if "last_data_at" in metrics:
            hb_kwargs["last_data_at"] = metrics["last_data_at"]
        if "error_count" in metrics:
            hb_kwargs["error_count"] = metrics["error_count"]
        await set_heartbeat(self.agent_id, status=hb_status, **hb_kwargs)
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

    def _resolve_tickers(self, requested: list[str] | None, limit: int = 20) -> list[tuple[str, str, str]]:
        fdr = self._load_fdr()
        listing = fdr.StockListing("KRX")

        selected: list[tuple[str, str, str]] = []
        for _, row in listing.iterrows():
            ticker = str(row.get("Code", "")).strip()
            name = str(row.get("Name", ticker)).strip()
            market = str(row.get("Market", "")).strip().upper()
            if market not in {"KOSPI", "KOSDAQ"}:
                continue
            if requested and ticker not in requested:
                continue
            selected.append((ticker, name, market))
            if len(selected) >= limit and not requested:
                break

        if requested:
            missing = [t for t in requested if t not in {x[0] for x in selected}]
            selected.extend((t, t, "KOSPI") for t in missing)
        return selected

    async def resolve_tickers(self, requested: list[str] | None, limit: int = 20) -> list[tuple[str, str, str]]:
        return await asyncio.to_thread(self._resolve_tickers, requested, limit)

    async def _cache_latest_tick(self, tick, source: str) -> None:
        """TickData 또는 MarketDataPoint를 Redis에 캐시합니다."""
        redis = await get_redis()
        inst_id = getattr(tick, 'instrument_id', '')
        cache_key = inst_id
        # TickData는 price 속성, MarketDataPoint는 close 속성
        current_price = getattr(tick, 'price', None) or getattr(tick, 'close', None)
        payload = {
            "ticker": cache_key,
            "instrument_id": cache_key,
            "name": getattr(tick, 'name', cache_key),
            "current_price": current_price,
            "change_pct": getattr(tick, 'change_pct', None),
            "volume": getattr(tick, 'volume', 0),
            "updated_at": (getattr(tick, 'timestamp_kst', None) or datetime.now(KST)).isoformat(),
            "source": source,
        }
        encoded = json.dumps(payload, ensure_ascii=False)
        series_key = KEY_REALTIME_SERIES.format(ticker=cache_key)

        # Redis pipeline: 4 round trips → 1 round trip
        pipe = redis.pipeline(transaction=False)
        pipe.set(KEY_LATEST_TICKS.format(ticker=cache_key), encoded, ex=60)
        pipe.lpush(series_key, encoded)
        pipe.ltrim(series_key, 0, 299)
        pipe.expire(series_key, TTL_REALTIME_SERIES)
        await pipe.execute()

    async def _get_access_token(self) -> Optional[str]:
        redis = await get_redis()
        scope = self._account_scope()
        raw = await redis.get(kis_oauth_token_key(scope))
        if not raw:
            return None
        try:
            return json.loads(raw).get("access_token")
        except Exception:
            return None

    async def _ensure_ws_approval_key(self) -> str:
        """
        KIS WebSocket 접속용 approval_key 반환.
        Redis 캐시 우선 조회 → 미스 시 KIS API 발급 → Redis 저장.
        """
        scope = self._account_scope()
        redis = await get_redis()
        cache_key = kis_approval_key(scope)
        cached = await redis.get(cache_key)
        if cached:
            return cached

        app_key = kis_app_key_for_scope(self.settings, scope)
        app_secret = kis_app_secret_for_scope(self.settings, scope)
        if not self._has_kis_market_credentials():
            raise RuntimeError(f"KIS {scope} app key/app secret 미설정")

        url = f"{self.settings.kis_base_url_for_scope(scope)}/oauth2/Approval"
        payload = {
            "grant_type": "client_credentials",
            "appkey": app_key,
            "secretkey": app_secret,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        approval_key = data.get("approval_key")
        if not approval_key:
            raise RuntimeError(f"KIS approval_key 발급 실패: {data}")

        await redis.set(cache_key, approval_key, ex=TTL_KIS_APPROVAL_KEY)
        return approval_key
