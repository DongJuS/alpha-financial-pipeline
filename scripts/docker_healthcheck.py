"""
scripts/docker_healthcheck.py — Docker/K8s 용 경량 healthcheck 스크립트

사용법:
    python scripts/docker_healthcheck.py --service worker

exit 0: healthy, exit 1: unhealthy
"""

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# worker 서비스가 관리하는 에이전트 ID 목록
_SERVICE_AGENTS: dict[str, list[str]] = {
    "worker": [
        "collector_agent",
        "orchestrator_agent",
        "portfolio_manager_agent",
        "notifier_agent",
    ],
}


async def _check(service: str) -> bool:
    from src.utils.redis_client import close_redis, get_redis

    agent_ids = _SERVICE_AGENTS.get(service)
    if not agent_ids:
        print(f"[healthcheck] 알 수 없는 서비스: {service}", file=sys.stderr)
        return False

    try:
        redis = await get_redis()
        pong = await redis.ping()
        if not pong:
            print("[healthcheck] Redis PING 실패", file=sys.stderr)
            await close_redis()
            return False
    except Exception as e:
        print(f"[healthcheck] Redis 연결 실패: {e}", file=sys.stderr)
        return False

    # 하나라도 heartbeat 키가 존재하고 status != error 이면 healthy
    any_alive = False
    for agent_id in agent_ids:
        key = f"heartbeat:{agent_id}"
        try:
            data = await redis.hgetall(key)
        except Exception:
            # Hash가 아닌 기존 STRING 키일 수 있음 — EXISTS로 폴백
            exists = await redis.exists(key)
            if exists:
                any_alive = True
            continue

        if not data:
            continue  # 키 없음 — 아직 시작 안 됐거나 TTL 만료

        status = data.get("status", "ok")
        if status == "error":
            print(f"[healthcheck] {agent_id} status=error", file=sys.stderr)
            await close_redis()
            return False

        any_alive = True

    await close_redis()

    if not any_alive:
        print("[healthcheck] 활성 heartbeat 없음", file=sys.stderr)
        return False

    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", default="worker", help="서비스 이름")
    args = parser.parse_args()

    ok = asyncio.run(_check(args.service))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
