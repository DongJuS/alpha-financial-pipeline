"""
src/api/routers/market.py — 시장 데이터 조회 라우터
"""

import asyncio
from datetime import datetime, time, timedelta
from typing import Annotated, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.api.deps import get_current_user
from src.db.models import MarketDataPoint
from src.db.queries import upsert_market_data
from src.utils.db_client import fetch, fetchrow
from src.utils.logging import get_logger
from src.utils.redis_client import KEY_LATEST_TICKS, KEY_REALTIME_SERIES, get_redis

logger = get_logger(__name__)

router = APIRouter()
KST = ZoneInfo("Asia/Seoul")


class OHLCVItem(BaseModel):
    timestamp_kst: str
    open: int
    high: int
    low: int
    close: int
    volume: int
    change_pct: Optional[float] = None


class OHLCVResponse(BaseModel):
    ticker: str
    name: str
    data: list[OHLCVItem]


class QuoteResponse(BaseModel):
    ticker: str
    name: str
    current_price: int
    change: Optional[int] = None
    change_pct: Optional[float] = None
    volume: Optional[int] = None
    updated_at: Optional[str] = None


class IndexResponse(BaseModel):
    kospi: dict
    kosdaq: dict


class RealtimePoint(BaseModel):
    timestamp_kst: str
    current_price: int
    volume: Optional[int] = None
    change_pct: Optional[float] = None
    source: Optional[str] = None


class RealtimeSeriesResponse(BaseModel):
    ticker: str
    name: str
    points: list[RealtimePoint]


@router.get("/tickers")
async def list_tickers(
    _: Annotated[dict, Depends(get_current_user)],
    market: Optional[str] = Query(default=None, pattern="^(KOSPI|KOSDAQ)$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
) -> dict:
    """추적 중인 종목 목록을 반환합니다."""
    offset = (page - 1) * per_page

    base_query = "FROM market_data"
    params: list = [per_page, offset]
    where = ""

    if market:
        where = " WHERE market = $3"
        params.append(market)

    rows = await fetch(
        f"""
        SELECT DISTINCT ON (ticker) ticker, name, market
        {base_query}{where}
        ORDER BY ticker
        LIMIT $1 OFFSET $2
        """,
        *params,
    )

    return {
        "data": [dict(r) for r in rows],
        "meta": {"page": page, "per_page": per_page, "total": len(rows)},
    }


@router.get("/ohlcv/{ticker}", response_model=OHLCVResponse)
async def get_ohlcv(
    ticker: str,
    _: Annotated[dict, Depends(get_current_user)],
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    interval: str = Query(default="daily", pattern="^(daily|tick)$"),
) -> OHLCVResponse:
    """특정 종목의 OHLCV 이력을 반환합니다."""
    params: list = [ticker, interval]
    where_extra = ""

    if from_date:
        params.append(from_date)
        where_extra += f" AND timestamp_kst >= ${len(params)}::date"
    if to_date:
        params.append(to_date)
        where_extra += f" AND timestamp_kst < (${len(params)}::date + interval '1 day')"

    rows = await fetch(
        f"""
        SELECT
            to_char(timestamp_kst AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS+09:00') AS timestamp_kst,
            open, high, low, close, volume,
            COALESCE(change_pct, 0)::float AS change_pct
        FROM market_data
        WHERE ticker = $1 AND interval = $2 {where_extra}
        ORDER BY timestamp_kst DESC
        LIMIT 200
        """,
        *params,
    )

    # 종목 이름 조회
    meta = await fetchrow(
        "SELECT name FROM market_data WHERE ticker = $1 LIMIT 1", ticker
    )
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"종목 '{ticker}'를 찾을 수 없습니다.",
        )

    return OHLCVResponse(
        ticker=ticker,
        name=meta["name"],
        data=[OHLCVItem(**dict(r)) for r in rows],
    )


def _fetch_fdr_ohlcv_sync(ticker: str, days: int) -> tuple[str, list[dict]]:
    import FinanceDataReader as fdr

    start = (datetime.now(KST).date() - timedelta(days=max(1, days))).isoformat()
    df = fdr.DataReader(ticker, start)
    if df is None or df.empty:
        return ticker, []

    listing = fdr.StockListing("KRX")
    found = listing.loc[listing["Code"] == ticker]
    name = str(found.iloc[0]["Name"]) if not found.empty else ticker

    rows: list[dict] = []
    for ts, row in df.tail(200).iloc[::-1].iterrows():
        date_value = ts.date() if hasattr(ts, "date") else datetime.now(KST).date()
        ts_kst = datetime.combine(date_value, time(15, 30), tzinfo=KST)
        change = row.get("Change")
        rows.append(
            {
                "timestamp_kst": ts_kst.isoformat(),
                "open": int(row.get("Open", 0)),
                "high": int(row.get("High", 0)),
                "low": int(row.get("Low", 0)),
                "close": int(row.get("Close", 0)),
                "volume": int(row.get("Volume", 0)),
                "change_pct": float(change * 100.0) if change is not None else 0.0,
            }
        )
    return name, rows


@router.get("/opensource/ohlcv/{ticker}", response_model=OHLCVResponse)
async def get_opensource_ohlcv(
    ticker: str,
    _: Annotated[dict, Depends(get_current_user)],
    days: int = Query(default=120, ge=5, le=365),
) -> OHLCVResponse:
    """FinanceDataReader 기반 오픈소스 OHLCV 데이터를 반환합니다."""
    try:
        name, rows = await asyncio.to_thread(_fetch_fdr_ohlcv_sync, ticker, days)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"오픈소스 데이터 조회 실패: {e}",
        ) from e

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"종목 '{ticker}'의 오픈소스 데이터가 없습니다.",
        )

    return OHLCVResponse(
        ticker=ticker,
        name=name,
        data=[OHLCVItem(**r) for r in rows],
    )


@router.get("/quote/{ticker}", response_model=QuoteResponse)
async def get_quote(
    ticker: str,
    _: Annotated[dict, Depends(get_current_user)],
) -> QuoteResponse:
    """종목 최신 실시간 시세를 반환합니다. Redis 캐시를 우선 확인합니다."""
    import json

    # Redis에서 최신 틱 캐시 확인
    redis = await get_redis()
    cached = await redis.get(KEY_LATEST_TICKS.format(ticker=ticker))
    if cached:
        data = json.loads(cached)
        return QuoteResponse(**data)

    # DB에서 최신 종가 조회 (fallback)
    row = await fetchrow(
        """
        SELECT
            ticker, name, close AS current_price, change_pct,
            volume,
            to_char(timestamp_kst AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS+09:00') AS updated_at
        FROM market_data
        WHERE ticker = $1
        ORDER BY timestamp_kst DESC
        LIMIT 1
        """,
        ticker,
    )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"종목 '{ticker}'의 시세 데이터가 없습니다.",
        )

    return QuoteResponse(
        ticker=row["ticker"],
        name=row["name"],
        current_price=row["current_price"],
        change_pct=float(row["change_pct"]) if row["change_pct"] else None,
        volume=row["volume"],
        updated_at=row["updated_at"],
    )


@router.get("/realtime/{ticker}", response_model=RealtimeSeriesResponse)
async def get_realtime_series(
    ticker: str,
    _: Annotated[dict, Depends(get_current_user)],
    limit: int = Query(default=120, ge=10, le=300),
) -> RealtimeSeriesResponse:
    """Redis에 저장된 실시간 시세 시계열(최신 우선 캐시)을 반환합니다."""
    import json

    redis = await get_redis()
    key = KEY_REALTIME_SERIES.format(ticker=ticker)
    cached = await redis.lrange(key, 0, limit - 1)

    if cached:
        points_raw = [json.loads(x) for x in cached]
        name = str(points_raw[0].get("name") or ticker)
        points = [
            RealtimePoint(
                timestamp_kst=str(p.get("updated_at") or ""),
                current_price=int(p.get("current_price") or 0),
                volume=int(p.get("volume") or 0) if p.get("volume") is not None else None,
                change_pct=float(p.get("change_pct")) if p.get("change_pct") is not None else None,
                source=p.get("source"),
            )
            for p in reversed(points_raw)
            if p.get("current_price") is not None
        ]
        return RealtimeSeriesResponse(ticker=ticker, name=name, points=points)

    # 캐시가 비어 있으면 DB 최신 일봉으로 최소 시계열 구성
    rows = await fetch(
        """
        SELECT
            name,
            close AS current_price,
            volume,
            COALESCE(change_pct, 0)::float AS change_pct,
            to_char(timestamp_kst AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS+09:00') AS ts
        FROM market_data
        WHERE ticker = $1 AND interval = 'daily'
        ORDER BY timestamp_kst DESC
        LIMIT $2
        """,
        ticker,
        min(limit, 60),
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"종목 '{ticker}'의 시계열 데이터가 없습니다.",
        )

    data = [dict(r) for r in rows]
    return RealtimeSeriesResponse(
        ticker=ticker,
        name=str(data[0]["name"]),
        points=[
            RealtimePoint(
                timestamp_kst=r["ts"],
                current_price=int(r["current_price"]),
                volume=int(r["volume"]) if r["volume"] is not None else None,
                change_pct=float(r["change_pct"]) if r["change_pct"] is not None else None,
                source="market_data_daily",
            )
            for r in reversed(data)
        ],
    )


@router.get("/index", response_model=IndexResponse)
async def get_index(
    _: Annotated[dict, Depends(get_current_user)],
) -> IndexResponse:
    """KOSPI/KOSDAQ 지수 현황을 반환합니다."""
    import json

    redis = await get_redis()
    cached = await redis.get("redis:cache:market_index")
    if cached:
        return IndexResponse(**json.loads(cached))

    # 최신 데이터가 없으면 기본값 반환
    return IndexResponse(
        kospi={"value": 0.0, "change_pct": 0.0, "note": "데이터 수집 전"},
        kosdaq={"value": 0.0, "change_pct": 0.0, "note": "데이터 수집 전"},
    )


# ── 데이터 수집 엔드포인트 ─────────────────────────────────────────────────


class CollectRequest(BaseModel):
    tickers: List[str] = Field(
        default_factory=list,
        description="수집할 종목 코드 목록. 비워두면 KOSPI/KOSDAQ 상위 30개 자동 선택",
    )
    days: int = Field(default=120, ge=10, le=365, description="수집 기간(일)")


class CollectResponse(BaseModel):
    saved: int
    tickers_collected: List[str]
    tickers_failed: List[str]
    message: str


def _collect_fdr_to_db_sync(tickers: list[str], days: int) -> tuple[int, list[str], list[str]]:
    """FDR로 일봉 데이터를 수집하고 DB용 MarketDataPoint 리스트를 반환합니다."""
    import FinanceDataReader as fdr

    start = (datetime.now(KST).date() - timedelta(days=days + 5)).isoformat()

    # 종목 코드 → (이름, 마켓) 매핑
    listing = fdr.StockListing("KRX")
    info: dict[str, tuple[str, str]] = {}
    for _, row in listing.iterrows():
        code = str(row.get("Code", "")).strip()
        name = str(row.get("Name", code)).strip()
        market = str(row.get("Market", "")).strip().upper()
        if market in {"KOSPI", "KOSDAQ"}:
            info[code] = (name, market)

    # 대상 종목 결정: 요청 없으면 KOSPI 상위 30개
    if not tickers:
        tickers = list(info.keys())[:30]

    points: list[MarketDataPoint] = []
    collected: list[str] = []
    failed: list[str] = []

    for ticker in tickers:
        try:
            df = fdr.DataReader(ticker, start)
            if df is None or df.empty:
                failed.append(ticker)
                continue

            name, market = info.get(ticker, (ticker, "KOSPI"))

            for idx, row in df.iterrows():
                trade_date = idx.date() if hasattr(idx, "date") else datetime.now(KST).date()
                ts = datetime(
                    trade_date.year, trade_date.month, trade_date.day,
                    15, 30, 0, tzinfo=KST,
                )
                close_val = int(row.get("Close", 0))
                if close_val <= 0:
                    continue
                change = row.get("Change")
                points.append(
                    MarketDataPoint(
                        ticker=ticker,
                        name=name,
                        market=market,  # type: ignore[arg-type]
                        timestamp_kst=ts,
                        interval="daily",
                        open=int(row.get("Open", close_val)),
                        high=int(row.get("High", close_val)),
                        low=int(row.get("Low", close_val)),
                        close=close_val,
                        volume=int(row.get("Volume", 0)),
                        change_pct=float(change * 100.0) if change is not None else None,
                    )
                )
            collected.append(ticker)
        except Exception as e:
            logger.warning("FDR 수집 실패 [%s]: %s", ticker, e)
            failed.append(ticker)

    return points, collected, failed


@router.post("/collect", response_model=CollectResponse, status_code=status.HTTP_202_ACCEPTED)
async def collect_market_data(
    req: CollectRequest,
    _: Annotated[dict, Depends(get_current_user)],
) -> CollectResponse:
    """FinanceDataReader로 일봉 데이터를 수집하여 DB에 저장합니다.

    tickers를 비워서 요청하면 KOSPI/KOSDAQ 상위 30개 종목을 자동으로 수집합니다.
    """
    try:
        points, collected, failed = await asyncio.to_thread(
            _collect_fdr_to_db_sync, req.tickers, req.days
        )
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FinanceDataReader가 설치되어 있지 않습니다. `pip install finance-datareader`",
        )
    except Exception as e:
        logger.error("FDR 수집 오류: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    saved = await upsert_market_data(points)
    logger.info("FDR 수집 완료: saved=%d, tickers=%s", saved, collected)

    return CollectResponse(
        saved=saved,
        tickers_collected=collected,
        tickers_failed=failed,
        message=f"{len(collected)}개 종목 {saved}건 저장 완료" + (
            f" ({len(failed)}개 실패: {', '.join(failed[:5])})" if failed else ""
        ),
    )
