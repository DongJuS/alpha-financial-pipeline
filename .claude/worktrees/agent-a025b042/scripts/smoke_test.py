"""
scripts/smoke_test.py — 엔드-투-엔드 스모크 테스트

시스템 전체 파이프라인이 동작하는지 빠르게 확인합니다:
  1. DB 읽기/쓰기
  2. Redis Pub/Sub
  3. FastAPI 헬스 엔드포인트
  4. FinanceDataReader (샘플 종목 1개)
  5. Telegram 테스트 메시지

사용법:
    python scripts/smoke_test.py
    python scripts/smoke_test.py --skip-telegram   # Telegram 테스트 제외
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.utils.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

PASS = "✅ PASS"
FAIL = "❌ FAIL"


async def test_db() -> tuple[bool, str]:
    """DB 읽기/쓰기 테스트."""
    from src.utils.db_client import close_pool, execute, fetchval

    try:
        result = await fetchval("SELECT 1 + 1")
        assert result == 2, "SELECT 1+1 이 2가 아님"

        await execute(
            """
            INSERT INTO agent_heartbeats (agent_id, status, last_action)
            VALUES ('smoke_test', 'healthy', 'smoke test 실행')
            """
        )
        count = await fetchval(
            "SELECT COUNT(*) FROM agent_heartbeats WHERE agent_id = 'smoke_test'"
        )
        assert count >= 1

        await close_pool()
        return True, "DB 읽기/쓰기 정상"
    except Exception as e:
        return False, f"DB 오류: {e}"


async def test_redis_pubsub() -> tuple[bool, str]:
    """Redis Pub/Sub 발행/구독 테스트."""
    import asyncio
    import json

    import redis.asyncio as aioredis

    from src.utils.config import get_settings
    from src.utils.redis_client import TOPIC_ALERTS

    settings = get_settings()
    received: list[str] = []

    try:
        sub_client = await aioredis.from_url(settings.redis_url, decode_responses=True)
        pub_client = await aioredis.from_url(settings.redis_url, decode_responses=True)

        async def subscriber() -> None:
            async with sub_client.pubsub() as ps:
                await ps.subscribe(TOPIC_ALERTS)
                for _ in range(50):
                    msg = await ps.get_message(
                        ignore_subscribe_messages=True,
                        timeout=0.1,
                    )
                    if msg and msg.get("type") == "message":
                        received.append(msg["data"])
                        break
                    await asyncio.sleep(0.05)
                if received:
                    return
                async for msg in ps.listen():
                    if msg["type"] == "message":
                        received.append(msg["data"])
                        break

        sub_task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.2)

        test_payload = json.dumps({"type": "smoke_test", "message": "hello"})
        await pub_client.publish(TOPIC_ALERTS, test_payload)

        await asyncio.wait_for(sub_task, timeout=5.0)
        await sub_client.aclose()
        await pub_client.aclose()

        if received and "smoke_test" in received[0]:
            return True, "Pub/Sub 발행·수신 정상"
        return False, "메시지 수신 실패"

    except Exception as e:
        return False, f"Redis Pub/Sub 오류: {e}"


async def test_fastapi_health() -> tuple[bool, str]:
    """FastAPI /health 엔드포인트 테스트."""
    import httpx
    from src.utils.config import get_settings

    settings = get_settings()
    health_paths = [
        f"{settings.app_url.rstrip('/')}/health",
        "http://localhost:8000/health",
        "http://api:8000/health",
    ]
    tried: list[str] = []
    last_err = "unknown"

    async with httpx.AsyncClient(timeout=5.0) as client:
        for url in health_paths:
            if url in tried:
                continue
            tried.append(url)
            try:
                resp = await client.get(url)
                data = resp.json()
            except Exception as e:
                last_err = str(e)
                continue

            if resp.status_code == 200 and data.get("status") in ("healthy", "degraded"):
                return True, f"{url} HTTP 200, status={data['status']}"
            last_err = f"{url} -> 예상치 못한 응답: {resp.status_code} {data}"

    return False, f"FastAPI 미실행 또는 연결 오류: {last_err}"


async def test_fdr_data() -> tuple[bool, str]:
    """FinanceDataReader 삼성전자 데이터 조회 테스트."""
    try:
        import FinanceDataReader as fdr

        df = fdr.DataReader("005930", "2026-01-01", "2026-01-31")
        if df is not None and len(df) > 0:
            return True, f"삼성전자 데이터 {len(df)}행 조회 성공"
        return False, "데이터가 비어있습니다."
    except ImportError:
        return False, "FinanceDataReader 미설치 — pip install finance-datareader"
    except Exception as e:
        return False, f"FDR 오류: {e}"


async def test_telegram(skip: bool) -> tuple[bool, str]:
    """Telegram 테스트 메시지 발송 테스트."""
    if skip:
        return True, "SKIPPED"

    from src.utils.config import get_settings
    import httpx

    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False, "TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 미설정"

    try:
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": "🔬 Alpha 스모크 테스트 메시지 — 시스템 정상",
                },
            )
            resp.raise_for_status()
        return True, "Telegram 메시지 발송 성공"
    except Exception as e:
        return False, f"Telegram 오류: {e}"


async def run_smoke_test(skip_telegram: bool) -> int:
    print("\n" + "=" * 55)
    print("  Alpha Trading System — 스모크 테스트")
    print("=" * 55)

    results = [
        ("DB 읽기/쓰기", await test_db()),
        ("Redis Pub/Sub", await test_redis_pubsub()),
        ("FastAPI /health", await test_fastapi_health()),
        ("FinanceDataReader", await test_fdr_data()),
        ("Telegram", await test_telegram(skip_telegram)),
    ]

    all_ok = True
    for name, (ok, msg) in results:
        icon = PASS if ok else FAIL
        print(f"  {icon}  {name:<20} {msg}")
        if not ok and msg != "SKIPPED":
            all_ok = False

    print("=" * 55)
    print("  결과:", "🎉 전체 통과" if all_ok else "💥 일부 실패")
    print()

    return 0 if all_ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Alpha 시스템 스모크 테스트")
    parser.add_argument("--skip-telegram", action="store_true", help="Telegram 테스트 건너뜀")
    args = parser.parse_args()
    exit_code = asyncio.run(run_smoke_test(args.skip_telegram))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
