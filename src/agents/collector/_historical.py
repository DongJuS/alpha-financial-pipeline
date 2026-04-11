"""
src/agents/collector/_historical.py — Historical 벌크 수집 Mixin

CollectorAgent에 mix-in되어 과거 데이터 벌크 수집 기능을 제공합니다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

from src.db.models import MarketDataPoint
from src.db.queries import insert_collector_error
from src.utils.config import kis_app_key_for_scope, kis_app_secret_for_scope
from src.utils.logging import get_logger
from src.utils.market_data import compute_change_pct
from src.utils.ticker import from_raw as ticker_from_raw

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")


class _HistoricalMixin:
    """과거 OHLCV 벌크 수집 메서드를 제공하는 Mixin.

    CollectorAgent(_CollectorBase, ..., _HistoricalMixin, ...) 형태로 합성됩니다.
    self 에서 사용하는 속성/메서드:
        - self.agent_id
        - self.settings
        - self._beat()
        - self._cache_latest_tick()
        - self._load_fdr()
        - self._resolve_tickers()
        - self._account_scope()
        - self._get_access_token()
    """

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
                try:
                    await insert_collector_error(
                        source="kis_intraday",
                        ticker=ticker,
                        error_type=type(e).__name__,
                        message=str(e)[:1000],
                    )
                except Exception:
                    pass

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
            WHERE o.instrument_id = $1 OR i.ticker = $1
            """,
            ticker,
        )
        return int(count or 0)
