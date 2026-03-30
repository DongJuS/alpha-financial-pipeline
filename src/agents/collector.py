"""
src/agents/collector.py — CollectorAgent

- FinanceDataReader 일봉 수집
- KIS WebSocket 실시간 틱 수집 (본연동)
- Redis 캐시/메시지 발행 + heartbeat 기록
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta
import json
import sys
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
import websockets
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.db.models import AgentHeartbeatRecord, MarketDataPoint
from src.db.queries import insert_heartbeat, upsert_market_data
from src.services.yahoo_finance import fetch_daily_bars
from src.utils.config import get_settings, has_kis_credentials, kis_app_key_for_scope, kis_app_secret_for_scope
from src.utils.logging import get_logger, setup_logging
from src.utils.market_data import compute_change_pct
from src.utils.ticker import from_raw as ticker_from_raw
from src.utils.redis_client import (
    KEY_LATEST_TICKS,
    KEY_REALTIME_SERIES,
    TOPIC_MARKET_DATA,
    TTL_REALTIME_SERIES,
    get_redis,
    kis_oauth_token_key,
    publish_message,
    set_heartbeat,
)

setup_logging()
logger = get_logger(__name__)

KST = ZoneInfo("Asia/Seoul")


TICK_BUFFER_MAX = 100       # 틱 버퍼 최대 건수
TICK_BUFFER_FLUSH_SEC = 1.0  # 타임아웃 flush 주기 (초)


class CollectorAgent:
    def __init__(self, agent_id: str = "collector_agent") -> None:
        self.agent_id = agent_id
        self.settings = get_settings()
        self._last_hb_db_at: Optional[datetime] = None
        # 실시간 틱 버퍼 (건별 INSERT 대신 배치 flush)
        self._tick_buffer: list[MarketDataPoint] = []
        self._tick_buffer_last_flush: float = 0.0

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

    @staticmethod
    def _yahoo_ticker(ticker: str, market: str) -> str:
        if "." in ticker:
            return ticker
        suffix = ".KS" if market == "KOSPI" else ".KQ"
        return f"{ticker}{suffix}"

    @staticmethod
    def _fetch_yahoo_daily_bars_via_yfinance(yahoo_ticker: str, interval: str, range_: str):
        import yfinance as yf

        data = yf.download(
            yahoo_ticker,
            period=range_,
            interval=interval,
            progress=False,
            auto_adjust=False,
            actions=False,
            threads=False,
        )
        if data is None or data.empty:
            raise ValueError(f"yfinance 데이터가 비어 있습니다: ticker={yahoo_ticker}, range={range_}, interval={interval}")
        if hasattr(data.columns, "levels"):
            try:
                data = data.xs(yahoo_ticker, axis=1, level="Ticker")
            except Exception:
                data.columns = [col[0] for col in data.columns]
        return data.reset_index()

    def _fetch_daily_bars(
        self,
        ticker: str,
        name: str,
        market: str,
        lookback_days: int,
    ) -> list[MarketDataPoint]:
        fdr = self._load_fdr()
        start_date = (datetime.now(KST) - timedelta(days=lookback_days)).date().isoformat()
        df = fdr.DataReader(ticker, start_date)
        if df is None or df.empty:
            return []

        mkt = market if market in {"KOSPI", "KOSDAQ"} else "KOSPI"
        instrument_id = ticker_from_raw(ticker, mkt)

        points: list[MarketDataPoint] = []
        previous_close: float | None = None
        for index, row in df.iterrows():
            trade_date = index.date() if hasattr(index, "date") else datetime.now(KST).date()
            close_value = float(row.get("Close", 0))
            if close_value <= 0:
                continue
            change_pct = compute_change_pct(close_value, previous_close)
            points.append(
                MarketDataPoint(
                    instrument_id=instrument_id,
                    name=name,
                    market=mkt,
                    traded_at=trade_date,
                    open=float(row.get("Open", 0)),
                    high=float(row.get("High", 0)),
                    low=float(row.get("Low", 0)),
                    close=close_value,
                    volume=int(row.get("Volume", 0)),
                    change_pct=change_pct,
                )
            )
            previous_close = close_value
        return points

    async def _flush_tick_buffer(self, force: bool = False) -> int:
        """틱 버퍼를 DB에 배치 flush합니다.

        버퍼가 TICK_BUFFER_MAX 이상이거나, 마지막 flush 이후
        TICK_BUFFER_FLUSH_SEC가 경과했거나, force=True이면 flush합니다.

        Returns:
            flush된 건수 (flush하지 않았으면 0)
        """
        now = asyncio.get_event_loop().time()
        elapsed = now - self._tick_buffer_last_flush
        should_flush = (
            force
            or len(self._tick_buffer) >= TICK_BUFFER_MAX
            or (self._tick_buffer and elapsed >= TICK_BUFFER_FLUSH_SEC)
        )
        if not should_flush or not self._tick_buffer:
            return 0

        batch = self._tick_buffer[:]
        self._tick_buffer.clear()
        self._tick_buffer_last_flush = now

        flushed = await upsert_market_data(batch)
        logger.debug("틱 버퍼 flush: %d건", flushed)

        # S3(MinIO)에 틱 데이터 저장
        try:
            from src.services.datalake import store_tick_data
            # MarketDataPoint → 틱 데이터 스키마로 변환
            tick_records = []
            for point in batch:
                tick_records.append({
                    "ticker": point.instrument_id,
                    "price": point.close,
                    "volume": point.volume,
                    "timestamp_kst": point.timestamp_kst,
                    "change_pct": point.change_pct,
                    "source": "kis_websocket",
                })
            await store_tick_data(tick_records)
            logger.debug("S3 틱 데이터 저장 완료: %d건", len(tick_records))
        except Exception as s3_err:
            logger.warning("S3 틱 데이터 저장 스킵: %s", s3_err)

        return flushed

    async def _cache_latest_tick(self, point: MarketDataPoint, source: str) -> None:
        redis = await get_redis()
        # Redis 키는 instrument_id (005930.KS) 기반
        cache_key = point.instrument_id
        payload = {
            "ticker": cache_key,
            "instrument_id": cache_key,
            "name": point.name,
            "current_price": point.close,
            "change_pct": point.change_pct,
            "volume": point.volume,
            "updated_at": point.timestamp_kst.isoformat(),
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

    async def _issue_ws_approval_key(self) -> str:
        """
        KIS WebSocket 접속용 approval_key 발급.
        """
        scope = self._account_scope()
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
        return approval_key

    async def _fetch_quote(self, ticker: str) -> Optional[dict]:
        """
        WebSocket 메시지 파싱 실패 시 REST 시세를 보정용으로 조회합니다.
        """
        scope = self._account_scope()
        app_key = kis_app_key_for_scope(self.settings, scope)
        app_secret = kis_app_secret_for_scope(self.settings, scope)
        token = await self._get_access_token()
        if not token or not app_key or not app_secret:
            return None

        headers = {
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "FHKST01010100",
            "custtype": "P",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
        }
        url = f"{self.settings.kis_base_url_for_scope(scope)}/uapi/domestic-stock/v1/quotations/inquire-price"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
            output = data.get("output") or {}
            price = int(output.get("stck_prpr") or 0)
            volume = int(output.get("acml_vol") or 0)
            name = output.get("hts_kor_isnm") or ticker
            return {"ticker": ticker, "name": name, "price": price, "volume": volume}
        except Exception as e:
            logger.debug("REST 시세 보정 실패 [%s]: %s", ticker, e)
            return None

    @staticmethod
    def _extract_price(fields: list[str]) -> Optional[int]:
        # H0STCNT0 기준 stck_prpr가 일반적으로 index 2에 위치
        if len(fields) > 2 and fields[2].isdigit():
            return int(fields[2])
        for value in fields:
            if value.isdigit():
                num = int(value)
                if 100 <= num <= 2_000_000:
                    return num
        return None

    @staticmethod
    def _extract_volume(fields: list[str]) -> Optional[int]:
        # H0STCNT0 기준 누적거래량 index가 대체로 13 근방이므로 우선 시도
        candidate_idx = [13, 12, 11, 18]
        for idx in candidate_idx:
            if idx < len(fields) and fields[idx].isdigit():
                return int(fields[idx])
        return None

    @staticmethod
    def _extract_ticker(fields: list[str], subscribed: set[str]) -> Optional[str]:
        if fields and fields[0] in subscribed:
            return fields[0]
        for value in fields:
            if value in subscribed:
                return value
        return None

    def _parse_ws_tick_packet(self, raw: str, subscribed: set[str]) -> Optional[dict]:
        """
        KIS 실시간 체결 패킷을 파싱합니다.
        예상 포맷: 0|TR_ID|COUNT|field1^field2^...
        """
        if not raw:
            return None

        # 구독 ACK/오류는 JSON으로 오는 경우가 많음
        if raw.startswith("{"):
            try:
                msg = json.loads(raw)
                header = msg.get("header") or {}
                body = msg.get("body") or {}
                if header.get("tr_id") or body.get("rt_cd"):
                    logger.info("KIS WS 제어메시지: %s", raw)
            except Exception:
                logger.debug("알 수 없는 JSON 패킷: %s", raw)
            return None

        if not raw.startswith("0|"):
            return None

        parts = raw.split("|", 3)
        if len(parts) < 4:
            return None

        tr_id = parts[1]
        payload = parts[3]
        fields = payload.split("^")
        ticker = self._extract_ticker(fields, subscribed)
        price = self._extract_price(fields)
        volume = self._extract_volume(fields)

        if not ticker:
            return None

        return {
            "tr_id": tr_id,
            "ticker": ticker,
            "price": price,
            "volume": volume,
            "raw": raw,
        }

    # ── Historical Data Bulk Collection ─────────────────────────────────────

    async def fetch_historical_ohlcv(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str = "daily",
        name: str = "",
        market: str = "KOSPI",
    ) -> list[MarketDataPoint]:
        """과거 OHLCV 데이터를 수집합니다.

        Args:
            ticker: 종목코드
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)
            interval: 'daily' 또는 'minute'
            name: 종목명 (없으면 ticker 사용)
            market: 시장 구분 (KOSPI / KOSDAQ)

        Returns:
            수집된 MarketDataPoint 리스트
        """
        if interval == "minute":
            return await self._fetch_historical_intraday(
                ticker, start_date, end_date, name or ticker, market,
            )
        return await self._fetch_historical_daily(
            ticker, start_date, end_date, name or ticker, market,
        )

    async def _fetch_historical_daily(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        name: str,
        market: str,
    ) -> list[MarketDataPoint]:
        """FinanceDataReader를 이용한 일봉 과거 데이터 수집."""
        fdr = self._load_fdr()

        mkt = market if market in {"KOSPI", "KOSDAQ"} else "KOSPI"
        instrument_id = ticker_from_raw(ticker, mkt)

        def _fetch():
            df = fdr.DataReader(ticker, start_date, end_date)
            if df is None or df.empty:
                return []
            points: list[MarketDataPoint] = []
            previous_close: float | None = None
            for index, row in df.iterrows():
                trade_date = index.date() if hasattr(index, "date") else datetime.now(KST).date()
                close_value = float(row.get("Close", 0))
                if close_value <= 0:
                    continue
                change_pct = compute_change_pct(close_value, previous_close)
                points.append(
                    MarketDataPoint(
                        instrument_id=instrument_id,
                        name=name,
                        market=mkt,
                        traded_at=trade_date,
                        open=float(row.get("Open", 0)),
                        high=float(row.get("High", 0)),
                        low=float(row.get("Low", 0)),
                        close=close_value,
                        volume=int(row.get("Volume", 0)),
                        change_pct=change_pct,
                    )
                )
                previous_close = close_value
            return points

        points = await asyncio.to_thread(_fetch)
        if points:
            from src.db.queries import upsert_market_data
            saved = await upsert_market_data(points)
            logger.info("Historical daily [%s] %s~%s: %d건 저장", ticker, start_date, end_date, saved)
            # Redis 캐시 갱신 — 벌크 시드 후 대시보드에 최신값이 표시되도록
            try:
                await self._cache_latest_tick(points[-1], source="historical_seed")
            except Exception as redis_err:
                logger.debug("Historical Redis 캐시 갱신 스킵: %s", redis_err)
        return points

    async def _fetch_historical_intraday(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        name: str,
        market: str,
    ) -> list[MarketDataPoint]:
        """KIS API를 이용한 분봉 과거 데이터 수집 (초당 1회 제한).

        NOTE: ohlcv_daily는 일봉 전용 테이블이므로, 분봉 데이터는 일별로
        집계(일봉 OHLCV)하여 저장합니다. 원본 분봉은 S3에만 보관됩니다.
        """
        scope = self._account_scope()
        app_key = kis_app_key_for_scope(self.settings, scope)
        app_secret = kis_app_secret_for_scope(self.settings, scope)
        token = await self._get_access_token()

        if not token or not app_key:
            logger.warning("KIS 인증 정보 미설정 — 분봉 수집 건너뜀 [%s]", ticker)
            return []

        headers = {
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "FHKST03010200",
            "custtype": "P",
        }

        mkt = market if market in {"KOSPI", "KOSDAQ"} else "KOSPI"
        instrument_id = ticker_from_raw(ticker, mkt)
        points: list[MarketDataPoint] = []
        base_url = self.settings.kis_base_url_for_scope(scope)
        url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"

        # 시작~종료 범위를 하루씩 순회
        from datetime import date as date_cls
        current = date_cls.fromisoformat(start_date)
        end = date_cls.fromisoformat(end_date)

        while current <= end:
            date_str = current.strftime("%Y%m%d")
            params = {
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": ticker,
                "FID_INPUT_HOUR_1": "153000",
                "FID_PW_DATA_INCU_YN": "Y",
            }
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url, headers=headers, params=params)
                    resp.raise_for_status()
                    data = resp.json()

                output2 = data.get("output2") or []
                # 일별 집계용 변수
                day_open: float | None = None
                day_high: float = 0
                day_low: float = float("inf")
                day_close: float = 0
                day_volume: int = 0

                for item in output2:
                    o = float(item.get("stck_oprc", 0))
                    h = float(item.get("stck_hgpr", 0))
                    lo = float(item.get("stck_lwpr", 0))
                    c = float(item.get("stck_prpr", 0))
                    v = int(item.get("cntg_vol", 0))

                    if day_open is None:
                        day_open = o
                    day_high = max(day_high, h)
                    if lo > 0:
                        day_low = min(day_low, lo)
                    day_close = c
                    day_volume += v

                if day_open is not None and day_close > 0:
                    points.append(
                        MarketDataPoint(
                            instrument_id=instrument_id,
                            name=name,
                            market=mkt,
                            traded_at=current,
                            open=day_open,
                            high=day_high,
                            low=day_low if day_low != float("inf") else day_open,
                            close=day_close,
                            volume=day_volume,
                            change_pct=None,
                        )
                    )
            except Exception as e:
                logger.warning("분봉 수집 실패 [%s/%s]: %s", ticker, date_str, e)

            # KIS API rate limit: 초당 1회
            await asyncio.sleep(1.0)
            current = current + timedelta(days=1)

        if points:
            from src.db.queries import upsert_market_data
            saved = await upsert_market_data(points)
            logger.info("Historical intraday [%s] %s~%s: %d건 저장 (일별 집계)", ticker, start_date, end_date, saved)

        return points

    async def check_data_exists(self, ticker: str, interval: str = "daily") -> int:
        """특정 종목의 기존 데이터 수를 확인합니다 (resume 지원용).

        ticker는 instrument_id(005930.KS) 또는 raw_code(005930) 모두 허용합니다.
        """
        from src.utils.db_client import fetchval
        count = await fetchval(
            """
            SELECT COUNT(*)
            FROM ohlcv_daily o
            JOIN instruments i ON o.instrument_id = i.instrument_id
            WHERE o.instrument_id = $1 OR i.raw_code = $1
            """,
            ticker,
        )
        return int(count or 0)

    async def collect_daily_bars(
        self,
        tickers: list[str] | None = None,
        lookback_days: int = 120,
    ) -> list[MarketDataPoint]:
        selected = await asyncio.to_thread(self._resolve_tickers, tickers)
        points: list[MarketDataPoint] = []
        latest_points: list[MarketDataPoint] = []

        for ticker, name, market in selected:
            try:
                bars = await asyncio.to_thread(
                    self._fetch_daily_bars,
                    ticker,
                    name,
                    market,
                    lookback_days,
                )
                if bars:
                    points.extend(bars)
                    latest_points.append(bars[-1])
            except Exception as e:
                logger.warning("일봉 수집 실패 [%s]: %s", ticker, e)

        saved = await upsert_market_data(points)

        # S3(MinIO) 저장
        try:
            from src.services.datalake import store_daily_bars as _store_daily_bars
            s3_records = [p.model_dump() for p in points]
            await _store_daily_bars(s3_records)
            logger.info("CollectorAgent S3 일봉 저장 완료: %d건", len(s3_records))
        except Exception as s3_err:
            logger.warning("CollectorAgent S3 저장 스킵: %s", s3_err)

        for point in latest_points:
            await self._cache_latest_tick(point, source="fdr_daily")

        await publish_message(
            TOPIC_MARKET_DATA,
            json.dumps(
                {
                    "type": "data_ready",
                    "agent_id": self.agent_id,
                    "count": saved,
                    "tickers": [p.instrument_id for p in latest_points[:20]],
                    "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                },
                ensure_ascii=False,
            ),
        )

        await self._beat(
            status="healthy",
            last_action=f"일봉 수집 완료 ({saved}건)",
            metrics={"collected_count": saved, "mode": "daily"},
            force_db=True,
        )

        logger.info("CollectorAgent 일봉 수집 완료: %d건", saved)
        return points

    async def collect_yahoo_daily_bars(
        self,
        tickers: list[str] | None = None,
        *,
        range_: str = "10y",
        interval: str = "1d",
    ) -> list[MarketDataPoint]:
        selected = await self.resolve_tickers(tickers)
        points: list[MarketDataPoint] = []

        for ticker, name, market in selected:
            yahoo_ticker = self._yahoo_ticker(ticker, market)
            try:
                bars = await fetch_daily_bars(yahoo_ticker, range_=range_, interval=interval)
            except Exception as exc:
                logger.warning("Yahoo chart API 수집 실패 [%s/%s]: %s", ticker, yahoo_ticker, exc)
                try:
                    history = await asyncio.to_thread(
                        self._fetch_yahoo_daily_bars_via_yfinance,
                        yahoo_ticker,
                        interval,
                        range_,
                    )
                    bars = []
                    for row in history.to_dict(orient="records"):
                        trade_date = row["Date"].date().isoformat() if hasattr(row["Date"], "date") else str(row["Date"])
                        bars.append(
                            {
                                "date": trade_date,
                                "open": float(row["Open"]),
                                "high": float(row["High"]),
                                "low": float(row["Low"]),
                                "close": float(row["Close"]),
                                "volume": int(row["Volume"]),
                            }
                        )
                except Exception as yf_exc:
                    logger.warning("Yahoo yfinance 수집도 실패 [%s/%s]: %s", ticker, yahoo_ticker, yf_exc)
                    continue

            mkt = market if market in {"KOSPI", "KOSDAQ"} else "KOSPI"
            instrument_id = ticker_from_raw(ticker, mkt)
            for bar in bars:
                try:
                    bar_date = bar.get("date") if isinstance(bar, dict) else bar.date
                    bar_open = bar.get("open") if isinstance(bar, dict) else bar.open
                    bar_high = bar.get("high") if isinstance(bar, dict) else bar.high
                    bar_low = bar.get("low") if isinstance(bar, dict) else bar.low
                    bar_close = bar.get("close") if isinstance(bar, dict) else bar.close
                    bar_volume = bar.get("volume") if isinstance(bar, dict) else bar.volume
                    trade_date = datetime.fromisoformat(str(bar_date)).date()
                except ValueError:
                    trade_date = datetime.now(KST).date()
                points.append(
                    MarketDataPoint(
                        instrument_id=instrument_id,
                        name=name,
                        market=mkt,
                        traded_at=trade_date,
                        open=float(bar_open),
                        high=float(bar_high),
                        low=float(bar_low),
                        close=float(bar_close),
                        volume=int(bar_volume),
                        change_pct=None,
                    )
                )

        saved = await upsert_market_data(points)

        # S3(MinIO) 저장
        try:
            from src.services.datalake import store_daily_bars as _store_daily_bars
            s3_records = [p.model_dump() for p in points]
            await _store_daily_bars(s3_records)
            logger.info("CollectorAgent S3 Yahoo 일봉 저장 완료: %d건", len(s3_records))
        except Exception as s3_err:
            logger.warning("CollectorAgent S3 저장 스킵: %s", s3_err)

        # 최신 data point들로 Redis 캐시 + Pub/Sub 발행
        if points:
            latest_points = []
            # instrument_id별로 최신 1건씩 추출
            seen_ids = set()
            for p in reversed(points):
                if p.instrument_id not in seen_ids:
                    latest_points.append(p)
                    seen_ids.add(p.instrument_id)
                    if len(latest_points) >= len(selected):
                        break

            for point in latest_points:
                await self._cache_latest_tick(point, source="yahoo_daily")

            await publish_message(
                TOPIC_MARKET_DATA,
                json.dumps(
                    {
                        "type": "data_ready",
                        "agent_id": self.agent_id,
                        "count": saved,
                        "tickers": [p.instrument_id for p in latest_points[:20]],
                        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                    },
                    ensure_ascii=False,
                ),
            )

        await self._beat(
            status="healthy",
            last_action=f"Yahoo 일봉 수집 완료 ({saved}건)",
            metrics={"collected_count": saved, "mode": "yahoo_daily"},
            force_db=True,
        )
        logger.info("CollectorAgent Yahoo 일봉 수집 완료: %d건", saved)
        return points

    async def collect_realtime_ticks(
        self,
        tickers: list[str],
        duration_seconds: Optional[int] = None,
        tr_id: str = "H0STCNT0",
        reconnect_max: int = 3,
        fallback_on_error: bool = True,
    ) -> int:
        if not tickers:
            raise ValueError("realtime 모드는 --tickers 지정이 필요합니다.")

        selected = await asyncio.to_thread(self._resolve_tickers, tickers)
        meta = {t: {"name": n, "market": m} for t, n, m in selected}
        subscribed = list(meta.keys())
        subscribed_set = set(subscribed)
        started = asyncio.get_running_loop().time()
        reconnects = 0
        received = 0

        if not self._has_kis_market_credentials():
            message = f"KIS {self._account_scope()} app key/app secret 미설정"
            if fallback_on_error:
                logger.warning("%s — 일봉 스냅샷 수집으로 폴백합니다.", message)
                await self.collect_daily_bars(tickers=subscribed, lookback_days=2)
                return 0
            raise RuntimeError(message)

        while True:
            try:
                approval_key = await self._issue_ws_approval_key()
                scope = self._account_scope()
                async with websockets.connect(
                    self.settings.kis_websocket_url_for_scope(scope),
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2**20,
                ) as ws:
                    logger.info("KIS WebSocket 연결 성공 [%s]: %s", scope, self.settings.kis_websocket_url_for_scope(scope))

                    for ticker in subscribed:
                        subscribe_payload = {
                            "header": {
                                "approval_key": approval_key,
                                "custtype": "P",
                                "tr_type": "1",
                                "content-type": "utf-8",
                            },
                            "body": {
                                "input": {
                                    "tr_id": tr_id,
                                    "tr_key": ticker,
                                }
                            },
                        }
                        await ws.send(json.dumps(subscribe_payload, ensure_ascii=False))
                        await asyncio.sleep(0.05)

                    reconnects = 0
                    while True:
                        if duration_seconds is not None:
                            elapsed = asyncio.get_running_loop().time() - started
                            if elapsed >= duration_seconds:
                                await self._flush_tick_buffer(force=True)
                                logger.info("KIS WebSocket 수집 종료 (duration=%ss)", duration_seconds)
                                await self._beat(
                                    status="healthy",
                                    last_action=f"실시간 수집 종료 ({received}건)",
                                    metrics={"received_ticks": received, "mode": "kis_ws"},
                                    force_db=True,
                                )
                                return received

                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            # 타임아웃 시 잔여 버퍼 flush
                            await self._flush_tick_buffer(force=True)
                            await self._beat(
                                status="healthy",
                                last_action=f"실시간 수집 대기중 ({received}건)",
                                metrics={"received_ticks": received, "mode": "kis_ws"},
                            )
                            continue

                        if not isinstance(raw, str):
                            continue

                        packet = self._parse_ws_tick_packet(raw, subscribed_set)
                        if not packet:
                            continue

                        ticker = packet["ticker"]
                        price = packet.get("price")
                        volume = packet.get("volume") or 0
                        name = meta.get(ticker, {}).get("name", ticker)
                        market = meta.get(ticker, {}).get("market", "KOSPI")

                        if not price:
                            quote = await self._fetch_quote(ticker)
                            if quote:
                                price = quote.get("price")
                                volume = quote.get("volume") or volume
                                name = quote.get("name") or name

                        if not price:
                            continue

                        now_kst = datetime.now(KST)
                        mkt = market if market in {"KOSPI", "KOSDAQ"} else "KOSPI"
                        inst_id = ticker_from_raw(ticker, mkt)
                        point = MarketDataPoint(
                            instrument_id=inst_id,
                            name=name,
                            market=mkt,
                            traded_at=now_kst.date(),
                            open=float(price),
                            high=float(price),
                            low=float(price),
                            close=float(price),
                            volume=int(volume),
                            change_pct=None,
                        )

                        # 버퍼에 추가 → 조건 충족 시 배치 flush
                        self._tick_buffer.append(point)
                        await self._flush_tick_buffer()

                        # Redis 캐시/Pub/Sub는 최신 1건만
                        await self._cache_latest_tick(point, source="kis_ws")
                        await publish_message(
                            TOPIC_MARKET_DATA,
                            json.dumps(
                                {
                                    "type": "tick",
                                    "agent_id": self.agent_id,
                                    "ticker": inst_id,
                                    "instrument_id": inst_id,
                                    "price": float(price),
                                    "volume": int(volume),
                                    "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                                },
                                ensure_ascii=False,
                            ),
                        )

                        received += 1
                        await self._beat(
                            status="healthy",
                            last_action=f"KIS 틱 수집중 ({received}건)",
                            metrics={"received_ticks": received, "mode": "kis_ws"},
                        )
            except Exception as e:
                reconnects += 1
                logger.warning("KIS WebSocket 오류 (%d/%d): %s", reconnects, reconnect_max, e)
                if reconnects > reconnect_max:
                    logger.error("KIS WebSocket 재연결 한도 초과")
                    break
                await asyncio.sleep(min(reconnects * 2, 10))

        if fallback_on_error:
            logger.warning("WebSocket 실패로 폴백: FDR 스냅샷 수집 모드")
            for _ in range(3):
                await self.collect_daily_bars(tickers=subscribed, lookback_days=2)
                await asyncio.sleep(10)
            return 0
        else:
            raise RuntimeError("KIS WebSocket 수집 실패")


async def _main_async(args: argparse.Namespace) -> None:
    agent = CollectorAgent()
    tickers = args.tickers.split(",") if args.tickers else None

    if args.realtime:
        await agent.collect_realtime_ticks(
            tickers=tickers or [],
            duration_seconds=args.duration_seconds,
            tr_id=args.tr_id,
            reconnect_max=args.reconnect_max,
            fallback_on_error=not args.no_fallback,
        )
    else:
        await agent.collect_daily_bars(tickers=tickers, lookback_days=args.lookback_days)


def main() -> None:
    parser = argparse.ArgumentParser(description="CollectorAgent")
    parser.add_argument("--tickers", default="", help="쉼표 구분 티커 목록 (예: 005930,000660)")
    parser.add_argument("--lookback-days", type=int, default=120, help="일봉 수집 lookback 기간")
    parser.add_argument("--realtime", action="store_true", help="KIS WebSocket 실시간 틱 수집 모드")
    parser.add_argument("--duration-seconds", type=int, default=None, help="실시간 수집 실행 시간(초)")
    parser.add_argument("--tr-id", default="H0STCNT0", help="KIS WebSocket 구독 TR ID")
    parser.add_argument("--reconnect-max", type=int, default=3, help="WebSocket 최대 재연결 횟수")
    parser.add_argument("--no-fallback", action="store_true", help="WebSocket 실패 시 폴백 수집 비활성화")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
