import unittest

import pytest

from src.utils.risk_validation import run_risk_rule_validation


@pytest.mark.integration
class RiskValidationTest(unittest.IsolatedAsyncioTestCase):
    @pytest.mark.integration
    async def test_run_risk_rule_validation_passes(self) -> None:
        from src.utils.config import get_settings
        get_settings.cache_clear()
        try:
            result = await run_risk_rule_validation()
        except Exception as e:
            if "password authentication" in str(e) or "Connect call failed" in str(e):
                self.skipTest(f"DB 연결 실패 (순서 의존성) — {e}")
            raise

        self.assertTrue(result["passed"])
        self.assertEqual(result["summary"], "리스크 규칙 검증 통과")
        self.assertEqual(len(result["checks"]), 3)
        self.assertTrue(all(item["ok"] for item in result["checks"]))


if __name__ == "__main__":
    unittest.main()
