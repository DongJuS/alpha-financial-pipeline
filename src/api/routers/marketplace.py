"""
src/api/routers/marketplace.py — 마켓플레이스 확장 라우터

종목 마스터, 섹터, 테마, 랭킹, 매크로 지표, ETF, 관심종목, 검색 API.
"""

import json
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from src.api.deps import get_current_user
from src.db.marketplace_queries import (
    add_watchlist_item,
    count_stock_master,
    get_daily_rankings,
    get_macro_indicators,
    get_sectors,
    get_stock_master,
    get_theme_stocks,
    get_themes,
    get_watchlist,
    list_stock_master,
    remove_watchlist_item,
    search_stocks,
)
from src.utils.redis_client import (
    KEY_ETF_LIST,
    KEY_MACRO,
    KEY_RANKINGS,
    KEY_SECTOR_MAP,
    KEY_THEME_MAP,
    get_redis,
)

router = APIRouter()


# ── 응답 모델 ────────────────────────────────────────────────────────────────


class StockItem(BaseModel):
    ticker: str
    name: str
    market: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[int] = None
    is_etf: bool = False
    is_etn: bool = False
    tier: Optional[str] = None


class SectorItem(BaseModel):
    sector: str
    stock_count: int
    total_market_cap: int


class ThemeItem(BaseModel):
    theme_slug: str
    theme_name: str
    stock_count: int
    leader_count: int


class RankingItem(BaseModel):
    rank: int
    ticker: str
    name: str
    value: Optional[float] = None
    change_pct: Optional[float] = None
    extra: Optional[dict] = None


class MacroItem(BaseModel):
    category: str
    symbol: str
    name: str
    value: float
    change_pct: Optional[float] = None
    previous_close: Optional[float] = None
    snapshot_date: str
    source: str


class WatchlistAddRequest(BaseModel):
    ticker: str
    name: str
    group_name: str = "default"
    price_alert_above: Optional[int] = None
    price_alert_below: Optional[int] = None


# ── 종목 마스터 ──────────────────────────────────────────────────────────────


@router.get("/stocks")
async def get_stocks(
    _: Annotated[dict, Depends(get_current_user)],
    market: Optional[str] = Query(default=None, pattern="^(KOSPI|KOSDAQ|KONEX)$"),
    sector: Optional[str] = None,
    is_etf: Optional[bool] = None,
    tier: Optional[str] = Query(default=None, pattern="^(core|extended|universe)$"),
    search: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> dict:
    """종목 마스터 목록 조회 (필터/검색/페이징)."""
    offset = (page - 1) * per_page
    stocks = await list_stock_master(
        market=market,
        sector=sector,
        is_etf=is_etf,
        tier=tier,
        search=search,
        limit=per_page,
        offset=offset,
    )
    total = await count_stock_master(market=market, sector=sector, is_etf=is_etf, search=search)
    return {
        "data": stocks,
        "meta": {"page": page, "per_page": per_page, "total": total},
    }


@router.get("/stocks/{ticker}")
async def get_stock_detail(
    ticker: str,
    _: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """단일 종목 상세 조회."""
    stock = await get_stock_master(ticker)
    if not stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"종목 '{ticker}'을(를) 찾을 수 없습니다.")
    return stock


# ── 섹터 ─────────────────────────────────────────────────────────────────────


@router.get("/sectors")
async def list_sectors(
    _: Annotated[dict, Depends(get_current_user)],
) -> list[dict]:
    """섹터 목록과 종목 수를 반환합니다."""
    # Redis 캐시 확인
    redis = await get_redis()
    cached = await redis.get(KEY_SECTOR_MAP)
    if cached:
        return json.loads(cached)
    return await get_sectors()


@router.get("/sectors/heatmap")
async def get_sector_heatmap(
    _: Annotated[dict, Depends(get_current_user)],
) -> list[dict]:
    """섹터별 평균 등락률 히트맵 데이터."""
    from src.utils.db_client import fetch as db_fetch

    redis = await get_redis()
    cached = await redis.get("redis:cache:sector_heatmap")
    if cached:
        return json.loads(cached)

    # Cache miss fallback: compute from DB
    rows = await db_fetch(
        """
        SELECT sm.sector,
               COUNT(*) AS stock_count,
               COALESCE(AVG(od.change_pct), 0) AS avg_change_pct,
               COALESCE(SUM(sm.market_cap), 0) AS total_market_cap,
               COALESCE(SUM(od.volume), 0) AS total_volume
        FROM stock_master sm
        LEFT JOIN LATERAL (
            SELECT od.change_pct, od.volume
            FROM ohlcv_daily od
            JOIN instruments i ON od.instrument_id = i.instrument_id
            WHERE i.raw_code = sm.ticker
            ORDER BY od.traded_at DESC
            LIMIT 1
        ) od ON TRUE
        WHERE sm.is_active = TRUE
          AND sm.is_etf = FALSE AND sm.is_etn = FALSE
          AND sm.sector IS NOT NULL AND sm.sector != ''
        GROUP BY sm.sector
        ORDER BY total_market_cap DESC
        """
    )
    result = [
        {
            "sector": row["sector"],
            "stock_count": int(row["stock_count"]),
            "avg_change_pct": round(float(row["avg_change_pct"]), 2),
            "total_market_cap": int(row["total_market_cap"]),
            "total_volume": int(row["total_volume"]),
        }
        for row in rows
    ]
    await redis.set("redis:cache:sector_heatmap", json.dumps(result, ensure_ascii=False), ex=300)
    return result


@router.get("/sectors/{sector}/stocks")
async def list_sector_stocks(
    sector: str,
    _: Annotated[dict, Depends(get_current_user)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> dict:
    """특정 섹터에 속한 종목 목록."""
    offset = (page - 1) * per_page
    stocks = await list_stock_master(sector=sector, limit=per_page, offset=offset)
    total = await count_stock_master(sector=sector)
    return {
        "data": stocks,
        "meta": {"page": page, "per_page": per_page, "total": total, "sector": sector},
    }


# ── 테마 ─────────────────────────────────────────────────────────────────────


@router.get("/themes")
async def list_themes(
    _: Annotated[dict, Depends(get_current_user)],
) -> list[dict]:
    """전체 테마 목록."""
    # Redis 캐시 확인
    redis = await get_redis()
    cached = await redis.get(KEY_THEME_MAP)
    if cached:
        return json.loads(cached)
    return await get_themes()


@router.get("/themes/{theme_slug}/stocks")
async def list_theme_stocks(
    theme_slug: str,
    _: Annotated[dict, Depends(get_current_user)],
) -> list[dict]:
    """특정 테마에 속한 종목 목록."""
    stocks = await get_theme_stocks(theme_slug)
    if not stocks:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"테마 '{theme_slug}'을(를) 찾을 수 없습니다.")
    return stocks


# ── 랭킹 ─────────────────────────────────────────────────────────────────────


@router.get("/rankings/{ranking_type}")
async def get_rankings(
    ranking_type: str,
    _: Annotated[dict, Depends(get_current_user)],
    ranking_date: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """일별 랭킹 조회 (market_cap, volume, turnover, gainer, loser, new_high, new_low)."""
    valid_types = {"market_cap", "volume", "turnover", "gainer", "loser", "new_high", "new_low"}
    if ranking_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"유효하지 않은 ranking_type: {ranking_type}. 가능한 값: {', '.join(sorted(valid_types))}",
        )

    # Redis 캐시 확인
    redis = await get_redis()
    cache_key = KEY_RANKINGS.format(ranking_type=ranking_type)
    if not ranking_date:
        cached = await redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            return {"ranking_type": ranking_type, "data": data[:limit]}

    parsed_date = date.fromisoformat(ranking_date) if ranking_date else None
    rankings = await get_daily_rankings(ranking_type, ranking_date=parsed_date, limit=limit)
    return {"ranking_type": ranking_type, "data": rankings}


# ── 매크로 지표 ──────────────────────────────────────────────────────────────


@router.get("/macro")
async def get_all_macro(
    _: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """전체 매크로 지표 (인덱스/환율/원자재/금리)."""
    result = {}
    for category in ["index", "currency", "commodity", "rate"]:
        # Redis 캐시 확인
        redis = await get_redis()
        cache_key = KEY_MACRO.format(category=category)
        cached = await redis.get(cache_key)
        if cached:
            result[category] = json.loads(cached)
        else:
            result[category] = await get_macro_indicators(category=category)
    return result


@router.get("/macro/{category}")
async def get_macro_by_category(
    category: str,
    _: Annotated[dict, Depends(get_current_user)],
) -> list[dict]:
    """카테고리별 매크로 지표 (index, currency, commodity, rate)."""
    valid_categories = {"index", "currency", "commodity", "rate"}
    if category not in valid_categories:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"유효하지 않은 category: {category}. 가능한 값: {', '.join(sorted(valid_categories))}",
        )

    redis = await get_redis()
    cache_key = KEY_MACRO.format(category=category)
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    return await get_macro_indicators(category=category)


# ── ETF/ETN ──────────────────────────────────────────────────────────────────


@router.get("/etf")
async def list_etf(
    _: Annotated[dict, Depends(get_current_user)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    search: Optional[str] = None,
) -> dict:
    """ETF/ETN 목록."""
    # Redis 캐시 확인 (검색 없는 경우)
    if not search and page == 1:
        redis = await get_redis()
        cached = await redis.get(KEY_ETF_LIST)
        if cached:
            all_etfs = json.loads(cached)
            return {
                "data": all_etfs[:per_page],
                "meta": {"page": 1, "per_page": per_page, "total": len(all_etfs)},
            }

    offset = (page - 1) * per_page
    etfs = await list_stock_master(is_etf=True, search=search, limit=per_page, offset=offset)
    total = await count_stock_master(is_etf=True, search=search)
    return {
        "data": etfs,
        "meta": {"page": page, "per_page": per_page, "total": total},
    }


# ── 검색 ─────────────────────────────────────────────────────────────────────


@router.get("/search")
async def search_stock(
    q: str,
    _: Annotated[dict, Depends(get_current_user)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    """종목 검색 (이름 또는 티커)."""
    if not q or len(q.strip()) < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="검색어를 입력해주세요.")
    return await search_stocks(q.strip(), limit=limit)


# ── 관심 종목 ────────────────────────────────────────────────────────────────


@router.get("/watchlist")
async def get_user_watchlist(
    user: Annotated[dict, Depends(get_current_user)],
    group_name: Optional[str] = None,
) -> list[dict]:
    """사용자 관심 종목 목록."""
    user_id = str(user.get("id", user.get("sub", "")))
    return await get_watchlist(user_id, group_name=group_name)


@router.post("/watchlist", status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    body: WatchlistAddRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """관심 종목 추가."""
    user_id = str(user.get("id", user.get("sub", "")))
    await add_watchlist_item(
        user_id=user_id,
        ticker=body.ticker,
        name=body.name,
        group_name=body.group_name,
        price_alert_above=body.price_alert_above,
        price_alert_below=body.price_alert_below,
    )
    return {"message": "관심 종목에 추가되었습니다.", "ticker": body.ticker}


@router.delete("/watchlist/{ticker}")
async def remove_from_watchlist(
    ticker: str,
    user: Annotated[dict, Depends(get_current_user)],
    group_name: str = Query(default="default"),
) -> dict:
    """관심 종목 삭제."""
    user_id = str(user.get("id", user.get("sub", "")))
    removed = await remove_watchlist_item(user_id, ticker, group_name=group_name)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"관심 종목 '{ticker}'이(가) 존재하지 않습니다.")
    return {"message": "관심 종목에서 삭제되었습니다.", "ticker": ticker}
