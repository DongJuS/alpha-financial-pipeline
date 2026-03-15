"""
scripts/validate_rl_trading.py — RL trading lane 자동 검증

사용법:
  python scripts/validate_rl_trading.py
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromName("test.test_rl_trading")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
