import unittest

from src.utils.risk_validation import run_risk_rule_validation


class RiskValidationTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_risk_rule_validation_passes(self) -> None:
        result = await run_risk_rule_validation()

        self.assertTrue(result["passed"])
        self.assertEqual(result["summary"], "리스크 규칙 검증 통과")
        self.assertEqual(len(result["checks"]), 3)
        self.assertTrue(all(item["ok"] for item in result["checks"]))


if __name__ == "__main__":
    unittest.main()
