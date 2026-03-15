import unittest

from src.utils.secret_validation import is_placeholder_secret


class SecretValidationTest(unittest.TestCase):
    def test_empty_and_none_are_placeholder(self) -> None:
        self.assertTrue(is_placeholder_secret(None))
        self.assertTrue(is_placeholder_secret(""))
        self.assertTrue(is_placeholder_secret("   "))

    def test_common_placeholder_patterns(self) -> None:
        self.assertTrue(is_placeholder_secret("sk-..."))
        self.assertTrue(is_placeholder_secret("change-this-value"))
        self.assertTrue(is_placeholder_secret("YOUR_API_KEY"))
        self.assertTrue(is_placeholder_secret("<secret>"))
        self.assertTrue(is_placeholder_secret("example-token"))

    def test_non_placeholder_value(self) -> None:
        self.assertFalse(is_placeholder_secret("sk-ant-abc123def456ghi789jkl012"))


if __name__ == "__main__":
    unittest.main()
