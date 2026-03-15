import unittest

from src.utils.account_scope import is_paper_scope, normalize_account_scope, scope_from_is_paper


class AccountScopeTest(unittest.TestCase):
    def test_normalize_defaults_unknown_to_paper(self) -> None:
        self.assertEqual(normalize_account_scope(None), "paper")
        self.assertEqual(normalize_account_scope("unknown"), "paper")

    def test_normalize_real_scope(self) -> None:
        self.assertEqual(normalize_account_scope("real"), "real")

    def test_scope_from_is_paper(self) -> None:
        self.assertEqual(scope_from_is_paper(True), "paper")
        self.assertEqual(scope_from_is_paper(False), "real")
        self.assertTrue(is_paper_scope("paper"))
        self.assertFalse(is_paper_scope("real"))


if __name__ == "__main__":
    unittest.main()
