"""
scripts/run_dual_execution.py — 빠른/꼼꼼 2-에이전트 자동 실행 CLI

사용 예:
    python scripts/run_dual_execution.py --task "docker 기반 실행 구성 점검"
    python scripts/run_dual_execution.py --task "API 라우터 점검" --context "권한 정책 유지" --context "문서 동기화"
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.agents.dual_execution import (
    DualExecutionCoordinator,
    record_dual_execution_heartbeat,
)
from src.utils.logging import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="2-에이전트 자동 실행 코디네이터")
    parser.add_argument("--task", required=True, help="실행할 작업 지시")
    parser.add_argument(
        "--context",
        action="append",
        default=[],
        help="보조 컨텍스트 (여러 번 입력 가능)",
    )
    parser.add_argument(
        "--skip-heartbeat",
        action="store_true",
        help="Redis/DB heartbeat 기록 생략",
    )
    return parser.parse_args()


async def main_async() -> int:
    setup_logging()
    args = parse_args()

    coordinator = DualExecutionCoordinator()
    result = coordinator.run(task=args.task, context=args.context)

    if not args.skip_heartbeat:
        await record_dual_execution_heartbeat(result, source="script:run_dual_execution")

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
