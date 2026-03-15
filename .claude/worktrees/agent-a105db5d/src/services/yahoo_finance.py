"""
src/services/yahoo_finance.py — Yahoo Finance chart API helper
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import urllib.parse
import urllib.request
from uuid import uuid4
from zoneinfo import ZoneInfo

YAHOO_CHART_URLS = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
    "https://query2.finance.yahoo.com/v8/finance/chart/{ticker}",
)
YAHOO_QUOTE_URL = "https://finance.yahoo.com/quote/{ticker}"
KST = ZoneInfo("Asia/Seoul")


@dataclass
class YahooDailyBar:
    ticker: str
    date: str
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int

    def to_dict(self) -> dict:
        return asdict(self)


async def fetch_daily_bars(
    ticker: str,
    *,
    range_: str = "1y",
    interval: str = "1d",
) -> list[YahooDailyBar]:
    params = {
        "range": range_,
        "interval": interval,
        "includeAdjustedClose": "true",
        "events": "div,splits",
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Referer": quote_page_url(ticker),
    }
    payload = None
    last_error: Exception | None = None

    for base_url in YAHOO_CHART_URLS:
        for attempt in range(2):
            try:
                payload = await asyncio.to_thread(
                    _fetch_chart_payload,
                    base_url.format(ticker=ticker),
                    params,
                    headers,
                )
                break
            except Exception as exc:  # pragma: no cover - network fallback
                last_error = exc
                await asyncio.sleep(1.0 + attempt)
        if payload is not None:
            break

    if payload is None:
        try:
            payload = await asyncio.to_thread(
                _fetch_chart_payload_via_playwright,
                ticker,
                params,
            )
        except Exception as playwright_error:
            raise ValueError(
                f"Yahoo chart API 호출 실패: ticker={ticker}, error={last_error}, playwright_error={playwright_error}"
            ) from playwright_error

    return bars_from_chart_payload(ticker, payload)


def quote_page_url(ticker: str) -> str:
    return YAHOO_QUOTE_URL.format(ticker=ticker)


def bars_from_chart_payload(ticker: str, payload: dict) -> list[YahooDailyBar]:
    chart = payload.get("chart", {})
    errors = chart.get("error")
    if errors:
        raise ValueError(f"Yahoo chart API 오류: {errors}")

    results = chart.get("result") or []
    if not results:
        raise ValueError(f"Yahoo chart API 결과 없음: ticker={ticker}")

    result = results[0]
    granularity = str((result.get("meta") or {}).get("dataGranularity") or "")
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators", {})
    quotes = indicators.get("quote") or [{}]
    quote = quotes[0]
    adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []

    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    bars: list[YahooDailyBar] = []
    for idx, timestamp in enumerate(timestamps):
        close = _safe_float(closes, idx)
        open_ = _safe_float(opens, idx)
        high = _safe_float(highs, idx)
        low = _safe_float(lows, idx)
        adj_close = _safe_float(adjusted, idx, fallback=close)
        if close is None or open_ is None or high is None or low is None:
            continue
        date_str = _format_timestamp_label(int(timestamp), granularity)
        bars.append(
            YahooDailyBar(
                ticker=ticker,
                date=date_str,
                open=open_,
                high=high,
                low=low,
                close=close,
                adj_close=adj_close if adj_close is not None else close,
                volume=int(_safe_float(volumes, idx, fallback=0) or 0),
            )
        )

    if not bars:
        raise ValueError(f"Yahoo chart API에서 유효한 OHLCV를 찾지 못했습니다: ticker={ticker}")
    return bars


def _fetch_chart_payload(base_url: str, params: dict[str, str], headers: dict[str, str]) -> dict:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{base_url}?{query}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _fetch_chart_payload_via_playwright(ticker: str, params: dict[str, str]) -> dict:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    pwcli = codex_home / "skills" / "playwright" / "scripts" / "playwright_cli.sh"
    if not pwcli.exists():
        raise FileNotFoundError(f"Playwright CLI wrapper를 찾을 수 없습니다: {pwcli}")

    session = f"yahoo_{ticker.replace('.', '_').replace('-', '_')}_{uuid4().hex[:8]}"
    chart_url = f"{YAHOO_CHART_URLS[0].format(ticker=ticker)}?{urllib.parse.urlencode(params)}"

    open_cmd = (
        f"{shlex.quote(str(pwcli))} --session {shlex.quote(session)} "
        f"open {shlex.quote(quote_page_url(ticker))}"
    )
    try:
        subprocess.run(
            ["zsh", "-lc", open_cmd],
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )
        eval_source = f"() => fetch('{chart_url}').then(r => r.json())"
        eval_cmd = (
            f"{shlex.quote(str(pwcli))} --session {shlex.quote(session)} "
            f"eval {shlex.quote(eval_source)}"
        )
        result = subprocess.run(
            ["zsh", "-lc", eval_cmd],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        match = re.search(r"### Result\n(.*?)\n### Ran Playwright code", result.stdout, re.S)
        if not match:
            raise ValueError(f"Playwright 결과 파싱 실패: {result.stdout[:500]}")
        return json.loads(match.group(1))
    finally:
        close_cmd = f"{shlex.quote(str(pwcli))} --session {shlex.quote(session)} close"
        subprocess.run(
            ["zsh", "-lc", close_cmd],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )


def _safe_float(values: list, idx: int, fallback: float | None = None) -> float | None:
    if idx >= len(values):
        return fallback
    value = values[idx]
    if value is None:
        return fallback
    return float(value)


def _format_timestamp_label(timestamp: int, granularity: str) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=KST)
    if granularity.endswith("m") or granularity.endswith("h"):
        return dt.isoformat(timespec="minutes")
    return dt.date().isoformat()
