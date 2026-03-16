"""
src/gen/generator.py — 랜덤 시장 데이터 생성 엔진

1초마다 20종목의 시세를 GBM(Geometric Brownian Motion) 기반으로
랜덤 생성하며, KOSPI/KOSDAQ 지수와 매크로 지표도 함께 갱신합니다.
"""

from __future__ import annotations

import math
import random
import threading
import time
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from src.gen.models import (
    GenIndex,
    GenMacro,
    GenOHLCV,
    GenQuote,
    GenTick,
    GenTicker,
)

KST = ZoneInfo("Asia/Seoul")

# ── 가상 종목 마스터 (실제 티커 사용) ────────────────────────────────────────

_STOCK_MASTER: list[dict] = [
    {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "반도체", "base_price": 72000},
    {"ticker": "000660", "name": "SK하이닉스", "market": "KOSPI", "sector": "반도체", "base_price": 185000},
    {"ticker": "035420", "name": "NAVER", "market": "KOSPI", "sector": "인터넷", "base_price": 210000},
    {"ticker": "035720", "name": "카카오", "market": "KOSPI", "sector": "인터넷", "base_price": 42000},
    {"ticker": "051910", "name": "LG화학", "market": "KOSPI", "sector": "화학", "base_price": 380000},
    {"ticker": "006400", "name": "삼성SDI", "market": "KOSPI", "sector": "전자부품", "base_price": 420000},
    {"ticker": "005380", "name": "현대자동차", "market": "KOSPI", "sector": "자동차", "base_price": 235000},
    {"ticker": "000270", "name": "기아", "market": "KOSPI", "sector": "자동차", "base_price": 120000},
    {"ticker": "068270", "name": "셀트리온", "market": "KOSPI", "sector": "바이오", "base_price": 178000},
    {"ticker": "207940", "name": "삼성바이오로직스", "market": "KOSPI", "sector": "바이오", "base_price": 790000},
    {"ticker": "259960", "name": "크래프톤", "market": "KOSPI", "sector": "게임", "base_price": 250000},
    {"ticker": "003670", "name": "포스코퓨처엠", "market": "KOSPI", "sector": "소재", "base_price": 195000},
    {"ticker": "055550", "name": "신한지주", "market": "KOSPI", "sector": "금융", "base_price": 52000},
    {"ticker": "105560", "name": "KB금융", "market": "KOSPI", "sector": "금융", "base_price": 82000},
    {"ticker": "028260", "name": "삼성물산", "market": "KOSPI", "sector": "지주", "base_price": 145000},
    {"ticker": "247540", "name": "에코프로비엠", "market": "KOSDAQ", "sector": "2차전지", "base_price": 125000},
    {"ticker": "086520", "name": "에코프로", "market": "KOSDAQ", "sector": "2차전지", "base_price": 62000},
    {"ticker": "328130", "name": "루닛", "market": "KOSDAQ", "sector": "AI/의료", "base_price": 58000},
    {"ticker": "403870", "name": "HPSP", "market": "KOSDAQ", "sector": "반도체장비", "base_price": 37000},
    {"ticker": "196170", "name": "알테오젠", "market": "KOSDAQ", "sector": "바이오", "base_price": 310000},
]


class MarketDataGenerator:
    """GBM 기반 랜덤 시세 생성 엔진.

    매 tick마다 각 종목의 현재가를 GBM 모델로 업데이트하며,
    일봉 히스토리도 과거 N일분을 역방향으로 생성할 수 있습니다.
    """

    def __init__(
        self,
        volatility: float = 0.02,
        drift: float = 0.0001,
        seed: Optional[int] = None,
    ) -> None:
        self._vol = volatility
        self._drift = drift
        self._rng = random.Random(seed)
        self._lock = threading.Lock()

        self._tickers: list[GenTicker] = []
        self._prices: dict[str, float] = {}
        self._day_open: dict[str, float] = {}
        self._day_high: dict[str, float] = {}
        self._day_low: dict[str, float] = {}
        self._day_volume: dict[str, int] = {}
        self._prev_close: dict[str, float] = {}

        self._kospi: float = 2620.0
        self._kosdaq: float = 850.0
        self._usdkrw: float = 1365.0
        self._gold: float = 2340.0
        self._oil: float = 78.5
        self._us10y: float = 4.25

        self._tick_buffer: dict[str, list[GenTick]] = {}
        self._tick_count: int = 0
        self._started_at: float = time.monotonic()
        self._last_generated_at: Optional[str] = None

        self._init_stocks()

    def _init_stocks(self) -> None:
        for s in _STOCK_MASTER:
            t = GenTicker(**s)
            self._tickers.append(t)
            price = float(t.base_price)
            price *= 1.0 + self._rng.gauss(0, 0.01)
            price = max(100, round(price))
            self._prices[t.ticker] = price
            self._day_open[t.ticker] = price
            self._day_high[t.ticker] = price
            self._day_low[t.ticker] = price
            self._day_volume[t.ticker] = 0
            self._prev_close[t.ticker] = price
            self._tick_buffer[t.ticker] = []

    def generate_tick(self) -> list[GenTick]:
        """모든 종목의 1틱을 생성하고 내부 상태를 갱신합니다."""
        with self._lock:
            ticks: list[GenTick] = []
            now_str = datetime.now(KST).isoformat()

            for t in self._tickers:
                z = self._rng.gauss(0, 1)
                log_return = (self._drift - 0.5 * self._vol**2) + self._vol * z
                new_price = self._prices[t.ticker] * math.exp(log_return)
                new_price = max(100, round(new_price))

                self._prices[t.ticker] = new_price
                self._day_high[t.ticker] = max(self._day_high[t.ticker], new_price)
                self._day_low[t.ticker] = min(self._day_low[t.ticker], new_price)

                vol = self._rng.randint(1000, 50000)
                self._day_volume[t.ticker] += vol

                tick = GenTick(
                    ticker=t.ticker,
                    name=t.name,
                    price=int(new_price),
                    volume=vol,
                    timestamp=now_str,
                )
                ticks.append(tick)

                buf = self._tick_buffer[t.ticker]
                buf.append(tick)
                if len(buf) > 100:
                    self._tick_buffer[t.ticker] = buf[-100:]

            self._kospi *= 1.0 + self._rng.gauss(0, 0.001)
            self._kosdaq *= 1.0 + self._rng.gauss(0, 0.0015)
            self._usdkrw *= 1.0 + self._rng.gauss(0, 0.0005)
            self._gold *= 1.0 + self._rng.gauss(0, 0.0008)
            self._oil *= 1.0 + self._rng.gauss(0, 0.001)
            self._us10y += self._rng.gauss(0, 0.005)
            self._us10y = max(0.5, min(8.0, self._us10y))

            self._tick_count += 1
            self._last_generated_at = now_str

            return ticks

    def generate_daily_history(self, ticker: str, days: int = 120) -> list[GenOHLCV]:
        """과거 N일분 일봉 데이터를 역방향 GBM으로 생성합니다."""
        with self._lock:
            info = self._get_ticker_info(ticker)
            if not info:
                return []

            bars: list[GenOHLCV] = []
            price = self._prices[ticker]
            today = date.today()

            prices_rev: list[float] = [price]
            for _ in range(days - 1):
                log_return = self._rng.gauss(0, 0.015)
                prev_price = price / math.exp(log_return)
                prev_price = max(100, prev_price)
                prices_rev.append(prev_price)
                price = prev_price

            prices_fwd = list(reversed(prices_rev))

            for i, p in enumerate(prices_fwd):
                bar_date = today - timedelta(days=days - 1 - i)
                if bar_date.weekday() >= 5:
                    continue

                close = int(round(p))
                intraday_range = max(1, int(close * self._rng.uniform(0.005, 0.025)))
                open_price = close + self._rng.randint(-intraday_range, intraday_range)
                open_price = max(100, open_price)
                high = max(open_price, close) + self._rng.randint(0, intraday_range)
                low = min(open_price, close) - self._rng.randint(0, intraday_range)
                low = max(100, low)
                high = max(high, max(open_price, close))
                low = min(low, min(open_price, close))

                volume = self._rng.randint(100_000, 5_000_000)

                prev_close = int(round(prices_fwd[i - 1])) if i > 0 else close
                change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0.0

                bars.append(GenOHLCV(
                    ticker=ticker,
                    name=info.name,
                    market=info.market,
                    date=bar_date.isoformat(),
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    change_pct=change_pct,
                ))

            return bars

    def get_quote(self, ticker: str) -> Optional[GenQuote]:
        with self._lock:
            info = self._get_ticker_info(ticker)
            if not info:
                return None
            price = self._prices[ticker]
            prev = self._prev_close[ticker]
            change_pct = round((price - prev) / prev * 100, 2) if prev else 0.0

            return GenQuote(
                ticker=ticker,
                name=info.name,
                market=info.market,
                current_price=int(price),
                open=int(self._day_open[ticker]),
                high=int(self._day_high[ticker]),
                low=int(self._day_low[ticker]),
                volume=self._day_volume[ticker],
                change_pct=change_pct,
                updated_at=datetime.now(KST).isoformat(),
            )

    def get_all_quotes(self) -> list[GenQuote]:
        return [q for t in self._tickers if (q := self.get_quote(t.ticker)) is not None]

    def get_ticks(self, ticker: str, count: int = 10) -> list[GenTick]:
        with self._lock:
            buf = self._tick_buffer.get(ticker, [])
            return buf[-count:]

    def get_tickers(self) -> list[GenTicker]:
        return list(self._tickers)

    def get_indices(self) -> list[GenIndex]:
        now_str = datetime.now(KST).isoformat()
        return [
            GenIndex(
                symbol="KOSPI", name="코스피",
                value=round(self._kospi, 2),
                change_pct=round(self._rng.gauss(0, 0.5), 2),
                updated_at=now_str,
            ),
            GenIndex(
                symbol="KOSDAQ", name="코스닥",
                value=round(self._kosdaq, 2),
                change_pct=round(self._rng.gauss(0, 0.7), 2),
                updated_at=now_str,
            ),
        ]

    def get_macro(self) -> list[GenMacro]:
        today_str = date.today().isoformat()
        return [
            GenMacro(category="currency", symbol="USD/KRW", name="원/달러 환율",
                     value=round(self._usdkrw, 2),
                     change_pct=round(self._rng.gauss(0, 0.3), 2),
                     previous_close=round(self._usdkrw * (1 - self._rng.gauss(0, 0.003)), 2),
                     snapshot_date=today_str),
            GenMacro(category="commodity", symbol="GOLD", name="국제 금",
                     value=round(self._gold, 2),
                     change_pct=round(self._rng.gauss(0, 0.5), 2),
                     previous_close=round(self._gold * (1 - self._rng.gauss(0, 0.005)), 2),
                     snapshot_date=today_str),
            GenMacro(category="commodity", symbol="WTI", name="WTI 원유",
                     value=round(self._oil, 2),
                     change_pct=round(self._rng.gauss(0, 0.8), 2),
                     previous_close=round(self._oil * (1 - self._rng.gauss(0, 0.005)), 2),
                     snapshot_date=today_str),
            GenMacro(category="rate", symbol="US10Y", name="미국 10년물 금리",
                     value=round(self._us10y, 3),
                     change_pct=round(self._rng.gauss(0, 0.2), 2),
                     previous_close=round(self._us10y - self._rng.gauss(0, 0.01), 3),
                     snapshot_date=today_str),
            GenMacro(category="index", symbol="SPX", name="S&P 500",
                     value=round(5200 + self._rng.gauss(0, 50), 2),
                     change_pct=round(self._rng.gauss(0, 0.5), 2),
                     previous_close=round(5200 + self._rng.gauss(0, 30), 2),
                     snapshot_date=today_str),
            GenMacro(category="index", symbol="IXIC", name="NASDAQ Composite",
                     value=round(16500 + self._rng.gauss(0, 100), 2),
                     change_pct=round(self._rng.gauss(0, 0.6), 2),
                     previous_close=round(16500 + self._rng.gauss(0, 80), 2),
                     snapshot_date=today_str),
        ]

    def get_status(self) -> dict:
        return {
            "running": True,
            "tick_count": self._tick_count,
            "tickers_count": len(self._tickers),
            "uptime_seconds": round(time.monotonic() - self._started_at, 1),
            "last_generated_at": self._last_generated_at,
        }

    def _get_ticker_info(self, ticker: str) -> Optional[GenTicker]:
        for t in self._tickers:
            if t.ticker == ticker:
                return t
        return None
