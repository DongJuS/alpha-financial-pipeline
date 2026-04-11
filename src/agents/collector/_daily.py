"""
src/agents/collector/_daily.py — FDR / Yahoo 일봉 수집 Mixin

CollectorAgent에 mix-in되어 일봉(daily bar) 수집 기능을 제공합니다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from src.db.models import MarketDataPoint
from src.db.queries import insert_collector_error, upsert_market_data
from src.services.yahoo_finance import fetch_daily_bars
from src.utils.logging import get_logger
from src.utils.market_data import compute_change_pct
from src.utils.ticker import from_raw as ticker_from_raw
from src.utils.redis_client import TOPIC_MARKET_DATA, publish_message

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")


class _DailyMixin:
    """FDR / Yahoo 일봉 수집 메서드를 제공하는 Mixin.

    CollectorAgent(_CollectorBase, _DailyMixin, ...) 형태로 합성됩니다.
    self 에서 사용하는 속성/메서드:
        - self.agent_id
        - self.settings
        - self._beat()
        - self._cache_latest_tick()
        - self._load_fdr()
        - self._resolve_tickers()
    """

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

    async def collect_daily_bars(
        self,
        tickers: list[str] | None = None,
        lookback_days: int = 120,
        limit: int = 20,
    ) -> list[MarketDataPoint]:
        selected = await asyncio.to_thread(self._resolve_tickers, tickers, limit)
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
                try:
                    await insert_collector_error(
                        source="fdr_daily",
                        ticker=ticker,
                        error_type=type(e).__name__,
                        message=str(e)[:1000],
                    )
                except Exception:
                    pass

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
                    await insert_collector_error(
                        source="yahoo_chart",
                        ticker=ticker,
                        error_type=type(exc).__name__,
                        message=str(exc)[:1000],
                    )
                except Exception:
                    pass
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
                    try:
                        await insert_collector_error(
                            source="yfinance_fallback",
                            ticker=ticker,
                            error_type=type(yf_exc).__name__,
                            message=str(yf_exc)[:1000],
                        )
                    except Exception:
                        pass
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
