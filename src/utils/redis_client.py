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
KEY_KIS_OAUTH_TOKEN = "kis:oauth_token"
KEY_KRX_HOLIDAYS = "krx:holidays:{year}"
KEY_LATEST_TICKS = "redis:cache:latest_ticks:{ticker}"
KEY_REALTIME_SERIES = "redis:cache:realtime_series:{ticker}"
KEY_MACRO_CONTEXT = "memory:macro_context"

# ── TTL 상수 (초) ────────────────────────────────────────────────────────────
TTL_HEARTBEAT = 90          # 90초 — 에이전트 생존 신호
TTL_KIS_TOKEN = 23 * 3600   # 23시간 — KIS OAuth 토큰
TTL_KRX_HOLIDAYS = 24 * 3600  # 24시간 — KRX 휴장일
TTL_LATEST_TICKS = 60       # 60초 — 실시간 시세 캐시
TTL_REALTIME_SERIES = 3600  # 1시간 — 실시간 시계열 캐시
TTL_MACRO_CONTEXT = 4 * 3600  # 4시간 — 거시경제 컨텍스트


async def get_redis() -> aioredis.Redis:
    """Redis 클라이언트 싱글턴을 반환합니다. 연결이 없으면 새로 생성합니다."""
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
    """앱 종료 시 Redis 연결을 닫습니다."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis 연결 종료")


async def publish_message(topic: str, payload: str) -> None:
    """Redis Pub/Sub 채널에 메시지를 발행합니다."""
    redis = await get_redis()
    await redis.publish(topic, payload)
    logger.debug("Published to %s", topic)


async def set_heartbeat(agent_id: str, value: str = "1") -> None:
    """에이전트 생존 신호를 Redis에 기록합니다 (TTL 90초)."""
    redis = await get_redis()
    key = KEY_HEARTBEAT.format(agent_id=agent_id)
    await redis.set(key, value, ex=TTL_HEARTBEAT)


async def check_heartbeat(agent_id: str) -> bool:
    """에이전트 생존 여부를 확인합니다."""
    redis = await get_redis()
    key = KEY_HEARTBEAT.format(agent_id=agent_id)
    return await redis.exists(key) == 1
