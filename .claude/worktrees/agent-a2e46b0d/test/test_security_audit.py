import tempfile
from pathlib import Path
import unittest

from src.utils.security_audit import check_env_example_safety, scan_repository_for_secrets


class SecurityAuditUtilsTest(unittest.TestCase):
    def test_scan_repository_detects_secret_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "sample.py"
            token = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
            target.write_text(f"OPENAI_API_KEY='{token}'\n", encoding="utf-8")

            result = scan_repository_for_secrets(root, tracked_files=[target])

            self.assertFalse(result["ok"])
            self.assertGreaterEqual(len(result["findings"]), 1)
            self.assertEqual(result["findings"][0]["path"], "sample.py")

    def test_check_env_example_safety_accepts_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env.example").write_text(
                "\n".join(
                    [
                        "JWT_SECRET=change-this-secret",
                        "OPENAI_API_KEY=sk-...",
                        "GEMINI_API_KEY=AI...",
                    ]
                ),
                encoding="utf-8",
            )

            result = check_env_example_safety(root)

            self.assertTrue(result["ok"])
            self.assertEqual(result["issues"], [])

    def test_check_env_example_safety_flags_real_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env.example").write_text(
                "OPENAI_API_KEY=production-secret-value-123456789\n",
                encoding="utf-8",
            )

            result = check_env_example_safety(root)

            self.assertFalse(result["ok"])
            self.assertEqual(len(result["issues"]), 1)


if __name__ == "__main__":
    unittest.main()
