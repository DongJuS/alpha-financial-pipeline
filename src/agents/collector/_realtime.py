"""src/agents/collector/_realtime.py — WebSocket 실시간 틱 수집 Mixin.

CollectorAgent 에 mix-in 되어, KIS WebSocket 실시간 체결 데이터를
수집·파싱·버퍼링·flush 하는 로직을 제공합니다.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from zoneinfo import ZoneInfo

import httpx
import websockets

from src.db.models import MarketDataPoint
from src.db.queries import insert_collector_error, insert_tick_batch, upsert_market_data
from src.constants import MAX_TICKERS_PER_WS
from src.utils.config import kis_app_key_for_scope, kis_app_secret_for_scope
from src.utils.logging import get_logger
from src.utils.redis_client import TOPIC_MARKET_DATA, publish_message
from src.utils.ticker import from_raw as ticker_from_raw

from src.agents.collector.models import TickData

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")


class _RealtimeMixin:
    """WebSocket 실시간 틱 수집 기능을 제공하는 Mixin.

    ``_CollectorBase`` 를 상속한 클래스에 mix-in 하여 사용합니다.
    ``self`` 로 접근 가능한 속성/메서드:
      - agent_id, settings
      - _beat(), _cache_latest_tick(), _ensure_ws_approval_key()
      - _has_kis_market_credentials(), _account_scope()
      - _tick_buffer, _tick_batch_size, _tick_flush_interval,
        _tick_buffer_last_flush
    """

    # ------------------------------------------------------------------
    # Tick buffer flush
    # ------------------------------------------------------------------

    async def _flush_tick_buffer(self, force: bool = False) -> int:
        """틱 버퍼를 tick_data 테이블에 배치 flush합니다."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._tick_buffer_last_flush
        should_flush = (
            force
            or len(self._tick_buffer) >= self._tick_batch_size
            or (self._tick_buffer and elapsed >= self._tick_flush_interval)
        )
        if not should_flush or not self._tick_buffer:
            return 0

        batch = self._tick_buffer[:]
        self._tick_buffer.clear()
        self._tick_buffer_last_flush = now

        # tick_data 테이블에 INSERT (ohlcv_daily 대신)
        # S3 저장은 장 종료 후 크론(15:40 KST)에서 flush_ticks_to_s3()로 일괄 처리
        flushed = await insert_tick_batch(batch)
        logger.debug("틱 버퍼 flush: %d건", flushed)

        return flushed

    # ------------------------------------------------------------------
    # Gap backfill (KIS REST 분봉)
    # ------------------------------------------------------------------

    async def _backfill_gap(
        self,
        tickers: list[str],
        meta: dict,
        gap_start: datetime,
    ) -> int:
        """KIS REST 분봉 API로 gap 구간을 backfill합니다.

        API: FHKST03010100 (국내주식 분봉조회)
        동시성: Semaphore(15) — KIS 초당 20회 제한 대비 여유
        """
        scope = self._account_scope()
        token = await self._get_access_token()
        if not token:
            logger.warning("backfill 스킵: KIS 토큰 없음")
            return 0

        app_key = kis_app_key_for_scope(self.settings, scope)
        app_secret = kis_app_secret_for_scope(self.settings, scope)
        if not app_key or not app_secret:
            return 0

        sem = asyncio.Semaphore(15)
        filled = 0

        async def _fill_one(ticker: str) -> int:
            async with sem:
                mkt = meta.get(ticker, {}).get("market", "KOSPI")
                inst_id = ticker_from_raw(ticker, mkt)
                headers = {
                    "authorization": f"Bearer {token}",
                    "appkey": app_key,
                    "appsecret": app_secret,
                    "tr_id": "FHKST03010100",
                    "custtype": "P",
                }
                params = {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": ticker,
                    "FID_INPUT_HOUR_1": gap_start.strftime("%H%M%S"),
                    "FID_PW_DATA_INCU_YN": "Y",
                }
                url = f"{self.settings.kis_base_url_for_scope(scope)}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.get(url, headers=headers, params=params)
                        resp.raise_for_status()
                        data = resp.json()

                    from src.agents.collector.models import TickData as _TD
                    from src.db.queries import insert_tick_batch as _insert

                    ticks = []
                    for item in (data.get("output2") or []):
                        price = int(item.get("stck_prpr") or 0)
                        vol = int(item.get("cntg_vol") or 0)
                        time_str = item.get("stck_cntg_hour", "")
                        if not price or not time_str:
                            continue
                        ts = datetime.combine(
                            gap_start.date(),
                            datetime.strptime(time_str, "%H%M%S").time(),
                            tzinfo=KST,
                        )
                        ticks.append(_TD(
                            instrument_id=inst_id,
                            price=float(price),
                            volume=vol,
                            timestamp_kst=ts,
                            source="kis_rest_backfill",
                        ))
                    if ticks:
                        await _insert(ticks)
                    return len(ticks)
                except Exception as e:
                    logger.debug("backfill 실패 [%s]: %s", ticker, e)
                    return 0

        results = await asyncio.gather(
            *[_fill_one(t) for t in tickers],
            return_exceptions=True,
        )
        filled = sum(r for r in results if isinstance(r, int))
        logger.info("gap backfill 완료: %d틱 복구 (%d종목)", filled, len(tickers))
        return filled

    # ------------------------------------------------------------------
    # REST 시세 보정
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Packet parsing helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # WebSocket collect loop (single connection)
    # ------------------------------------------------------------------

    async def _ws_collect_loop(
        self,
        subscribed: list[str],
        meta: dict[str, dict[str, str]],
        *,
        tr_id: str = "H0STCNT0",
        reconnect_max: int = 3,
        duration_seconds: Optional[int] = None,
        started: Optional[float] = None,
    ) -> int:
        """단일 WebSocket 연결로 subscribed 종목의 틱을 수집합니다.

        collect_realtime_ticks에서 분리된 내부 루프.
        다중 연결 분할 시 이 메서드를 청크별로 병렬 호출합니다.

        Returns:
            수신 틱 수 (>=0). 재연결 한도 초과 시 -1.
        """
        subscribed_set = set(subscribed)
        if started is None:
            started = asyncio.get_running_loop().time()
        reconnects = 0
        received = 0

        while True:
            try:
                approval_key = await self._ensure_ws_approval_key()
                scope = self._account_scope()
                async with websockets.connect(
                    self.settings.kis_websocket_url_for_scope(scope),
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2**20,
                ) as ws:
                    logger.info(
                        "KIS WebSocket 연결 성공 [%s] (%d종목): %s",
                        scope, len(subscribed),
                        self.settings.kis_websocket_url_for_scope(scope),
                    )

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
                                    metrics={"received_ticks": received, "mode": "websocket"},
                                    force_db=True,
                                )
                                return received

                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            await self._flush_tick_buffer(force=True)
                            await self._beat(
                                status="healthy",
                                last_action=f"실시간 수집 대기중 ({received}건)",
                                metrics={"received_ticks": received, "mode": "websocket"},
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

                        # TickData 생성 (실시간 전용 경량 모델)
                        tick = TickData(
                            instrument_id=inst_id,
                            price=float(price),
                            volume=int(volume),
                            timestamp_kst=now_kst,
                            name=name,
                            market=mkt,
                            change_pct=None,
                            source="kis_ws",
                        )

                        # 틱 버퍼에 TickData 직접 추가 (MarketDataPoint 변환 제거)
                        self._tick_buffer.append(tick)
                        await self._flush_tick_buffer()
                        self._last_tick_at = tick.timestamp_kst

                        await self._cache_latest_tick(tick, source="kis_ws")
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
                            metrics={
                                "received_ticks": received,
                                "mode": "websocket",
                                "last_data_at": int(time.time()),
                            },
                        )
            except Exception as e:
                reconnects += 1
                logger.warning("KIS WebSocket 오류 (%d/%d): %s", reconnects, reconnect_max, e)
                await self._beat(
                    status="error" if reconnects > reconnect_max else "degraded",
                    last_action=f"WebSocket 오류 ({reconnects}/{reconnect_max}): {type(e).__name__}",
                    metrics={
                        "received_ticks": received,
                        "mode": "websocket",
                        "error_count": reconnects,
                    },
                    force_db=True,
                )
                try:
                    await insert_collector_error(
                        source="kis_websocket",
                        ticker=",".join(subscribed[:5]),
                        error_type=type(e).__name__,
                        message=str(e)[:1000],
                    )
                except Exception:
                    pass
                if reconnects > reconnect_max:
                    logger.error("KIS WebSocket 재연결 한도 초과")
                    break

                # WebSocket 재연결 직후 gap 감지 + backfill
                gap_seconds = 0
                if self._last_tick_at:
                    gap_seconds = (datetime.now(KST) - self._last_tick_at).total_seconds()

                if gap_seconds >= 60:
                    logger.warning("틱 gap 감지: %.0f초 (backfill 시작)", gap_seconds)
                    try:
                        await self._backfill_gap(subscribed, meta, self._last_tick_at)
                    except Exception as bf_err:
                        logger.warning("gap backfill 실패: %s", bf_err)

                if gap_seconds >= 1800:  # 30분
                    try:
                        from src.utils.redis_client import publish_message as _pub
                        import json as _json
                        await _pub(
                            "alpha:alerts",
                            _json.dumps({
                                "type": "gap_warning",
                                "agent_id": self.agent_id,
                                "gap_seconds": int(gap_seconds),
                                "message": f"WebSocket 틱 수집 {int(gap_seconds // 60)}분 중단",
                            }, ensure_ascii=False),
                        )
                        logger.error("30분+ 틱 gap → Telegram 경고 발행")
                    except Exception:
                        pass

                await asyncio.sleep(min(reconnects * 2, 30) + random.uniform(0, 1))

        return -1  # 재연결 한도 초과로 실패

    # ------------------------------------------------------------------
    # Public coordinator
    # ------------------------------------------------------------------

    async def collect_realtime_ticks(
        self,
        tickers: list[str],
        duration_seconds: Optional[int] = None,
        tr_id: str = "H0STCNT0",
        reconnect_max: int = 3,
        fallback_on_error: bool = True,
    ) -> int:
        """KIS WebSocket 실시간 틱 수집 코디네이터.

        tickers를 받아 _ws_collect_loop에 위임합니다.
        MAX_TICKERS_PER_WS 단위로 청크 분할 후
        asyncio.gather로 _ws_collect_loop를 병렬 호출합니다.
        """
        if not tickers:
            raise ValueError("realtime 모드는 --tickers 지정이 필요합니다.")

        selected = await asyncio.to_thread(self._resolve_tickers, tickers)
        meta = {t: {"name": n, "market": m} for t, n, m in selected}
        subscribed = list(meta.keys())

        if not self._has_kis_market_credentials():
            message = f"KIS {self._account_scope()} app key/app secret 미설정"
            if fallback_on_error:
                logger.warning("%s — 일봉 스냅샷 수집으로 폴백합니다.", message)
                await self.collect_daily_bars(tickers=subscribed, lookback_days=2)
                return 0
            raise RuntimeError(message)

        started = asyncio.get_running_loop().time()

        # MAX_TICKERS_PER_WS 단위로 청크 분할 → 병렬 WebSocket 연결
        chunks = [
            subscribed[i : i + MAX_TICKERS_PER_WS]
            for i in range(0, len(subscribed), MAX_TICKERS_PER_WS)
        ]

        if len(chunks) <= 1:
            received = await self._ws_collect_loop(
                subscribed,
                meta,
                tr_id=tr_id,
                reconnect_max=reconnect_max,
                duration_seconds=duration_seconds,
                started=started,
            )
        else:
            results = await asyncio.gather(
                *[
                    self._ws_collect_loop(
                        chunk,
                        meta,
                        tr_id=tr_id,
                        reconnect_max=reconnect_max,
                        duration_seconds=duration_seconds,
                        started=started,
                    )
                    for chunk in chunks
                ],
                return_exceptions=True,
            )
            received = sum(r for r in results if isinstance(r, int) and r >= 0)
            failures = sum(
                1
                for r in results
                if (isinstance(r, int) and r < 0) or isinstance(r, Exception)
            )
            if failures == len(chunks):
                received = -1  # all chunks failed

        if received < 0:
            if fallback_on_error:
                logger.warning("WebSocket 실패로 폴백: FDR 스냅샷 수집 모드")
                await self._beat(
                    status="degraded",
                    last_action="WebSocket 실패 → FDR 폴백",
                    metrics={"received_ticks": 0, "mode": "fdr"},
                    force_db=True,
                )
                for _ in range(3):
                    await self.collect_daily_bars(tickers=subscribed, lookback_days=2)
                    await asyncio.sleep(10)
                return 0
            else:
                raise RuntimeError("KIS WebSocket 수집 실패")

        return received
