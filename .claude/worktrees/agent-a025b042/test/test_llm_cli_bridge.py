import unittest

from src.llm.cli_bridge import build_cli_command, is_cli_available, run_cli_prompt


class LlmCliBridgeTest(unittest.IsolatedAsyncioTestCase):
    def test_build_cli_command_replaces_model_placeholder(self) -> None:
        command = build_cli_command("echo {model}", model="gemini-1.5-pro")
        self.assertEqual(command, ["echo", "gemini-1.5-pro"])

    def test_is_cli_available_for_existing_binary(self) -> None:
        self.assertTrue(is_cli_available(["cat"]))

    async def test_run_cli_prompt_with_cat(self) -> None:
        output = await run_cli_prompt(["cat"], "hello-cli")
        self.assertEqual(output, "hello-cli")


if __name__ == "__main__":
    unittest.main()
