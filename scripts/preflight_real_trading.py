"""
scripts/preflight_real_trading.py — 실거래 전환 사전 점검

사용법:
    python scripts/preflight_real_trading.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.utils.readiness import evaluate_real_trading_readiness


async def _main() -> int:
    result = await evaluate_real_trading_readiness()
    print("\n=== Real Trading Readiness ===")
    for check in result["checks"]:
        icon = "✅" if check["ok"] else "❌"
        print(f"{icon} [{check['severity']}] {check['key']}: {check['message']}")
    print("------------------------------")
    print(
        "READY =", result["ready"],
        "| critical_ok =", result["critical_ok"],
        "| high_ok =", result["high_ok"],
    )
    return 0 if result["ready"] else 1


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
