"""
src/utils/redis_client.py — Redis 비동기 클라이언트 (싱글턴)

사용법:
    from src.utils.redis_client import get_redis

    async def handler():
        redis = await get_redis()
        await redis.set("key", "value", ex=60)
        value = await redis.get("key")
"""

import redis.asyncio as aioredis
from typing import Optional
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

_redis_client: Optional[aioredis.Redis] = None

# ── Redis 채널 이름 상수 ────────────────────────────────────────────────────
TOPIC_MARKET_DATA = "redis:topic:market_data"
TOPIC_SIGNALS = "redis:topic:signals"
TOPIC_ORDERS = "redis:topic:orders"
TOPIC_HEARTBEAT = "redis:topic:heartbeat"
TOPIC_ALERTS = "redis:topic:alerts"

# ── Redis 키 패턴 상수 ──────────────────────────────────────────────────────
KEY_HEARTBEAT = "heartbeat:{agent_id}"
KEY_KIS_OAUTH_TOKEN = "kis:oauth_token:{scope}"
KEY_KIS_APPROVAL_KEY = "kis:approval_key:{scope}"
KEY_KRX_HOLIDAYS = "krx:holidays:{year}"
KEY_LATEST_TICKS = "redis:cache:latest_ticks:{ticker}"
KEY_REALTIME_SERIES = "redis:cache:realtime_series:{ticker}"
KEY_MACRO_CONTEXT = "memory:macro_context"
KEY_MARKET_INDEX = "redis:cache:market_index"
KEY_LLM_PROVIDER_DAILY_USAGE = "redis:usage:llm:{provider}:{date}"

# ── 마켓플레이스 확장 키 패턴 ──────────────────────────────────────────────────
KEY_STOCK_MASTER = "redis:cache:stock_master"                    # 전체 종목 마스터
KEY_SECTOR_MAP = "redis:cache:sector_map"                        # 섹터 → 종목 매핑
KEY_THEME_MAP = "redis:cache:theme_map"                          # 테마 → 종목 매핑
KEY_RANKINGS = "redis:cache:rankings:{ranking_type}"             # 랭킹 (타입별)
KEY_MACRO = "redis:cache:macro:{category}"                       # 매크로 지표 (카테고리별)
KEY_ETF_LIST = "redis:cache:etf_list"                            # ETF/ETN 목록

# ── TTL 상수 (초) ────────────────────────────────────────────────────────────
TTL_HEARTBEAT = 90          # 90초 — 에이전트 생존 신호
TTL_KIS_TOKEN = 23 * 3600   # 23시간 — KIS OAuth 토큰
TTL_KIS_APPROVAL_KEY = 22 * 3600  # 22시간 — KIS WebSocket approval_key
TTL_KRX_HOLIDAYS = 24 * 3600  # 24시간 — KRX 휴장일
TTL_LATEST_TICKS = 60       # 60초 — 실시간 시세 캐시
TTL_REALTIME_SERIES = 3600  # 1시간 — 실시간 시계열 캐시
TTL_MACRO_CONTEXT = 4 * 3600  # 4시간 — 거시경제 컨텍스트
TTL_MARKET_INDEX = 120      # 120초 — 시장 지수 캐시
TTL_STOCK_MASTER = 24 * 3600   # 24시간 — 종목 마스터
TTL_SECTOR_MAP = 24 * 3600     # 24시간 — 섹터 매핑
TTL_THEME_MAP = 24 * 3600      # 24시간 — 테마 매핑
TTL_RANKINGS = 300              # 5분 — 랭킹 (장중 빈번 갱신)
TTL_MACRO = 3600                # 1시간 — 매크로 지표
TTL_ETF_LIST = 24 * 3600       # 24시간 — ETF 목록


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = await aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
        logger.info("Redis 연결 완료: %s", settings.redis_url)
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis 연결 종료")


async def publish_message(topic: str, payload: str) -> None:
    redis = await get_redis()
    await redis.publish(topic, payload)
    logger.debug("Published to %s", topic)


async def set_heartbeat(
    agent_id: str,
    status: str = "ok",
    **metadata: str | int | float,
) -> None:
    """에이전트 heartbeat를 Redis Hash로 기록한다.

    기본 필드: status, updated_at.  추가 필드(mode, last_data_at,
    error_count 등)는 keyword argument로 전달한다.
    기존 ``set_heartbeat(agent_id)`` 호출은 그대로 호환된다.
    """
    import time

    redis = await get_redis()
    key = KEY_HEARTBEAT.format(agent_id=agent_id)
    fields: dict[str, str | int | float] = {
        "status": status,
        "updated_at": int(time.time()),
        **metadata,
    }
    try:
        await redis.hset(key, mapping=fields)  # type: ignore[arg-type]
    except Exception:
        # 기존 STRING 키가 남아 있으면 WRONGTYPE — 삭제 후 재시도
        await redis.delete(key)
        await redis.hset(key, mapping=fields)  # type: ignore[arg-type]
    await redis.expire(key, TTL_HEARTBEAT)


def kis_oauth_token_key(scope: str) -> str:
    normalized = "real" if scope == "real" else "paper"
    return KEY_KIS_OAUTH_TOKEN.format(scope=normalized)


def kis_approval_key(scope: str) -> str:
    normalized = "real" if scope == "real" else "paper"
    return KEY_KIS_APPROVAL_KEY.format(scope=normalized)


async def check_heartbeat(agent_id: str) -> bool:
    """heartbeat 키 존재 여부만 반환 (기존 호환)."""
    redis = await get_redis()
    key = KEY_HEARTBEAT.format(agent_id=agent_id)
    return await redis.exists(key) == 1


async def get_heartbeat_detail(agent_id: str) -> dict[str, str] | None:
    """heartbeat Hash의 전체 필드를 반환한다. 키가 없으면 None."""
    redis = await get_redis()
    key = KEY_HEARTBEAT.format(agent_id=agent_id)
    data = await redis.hgetall(key)
    return data if data else None
