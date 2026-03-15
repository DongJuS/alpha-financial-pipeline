"""
src/utils/reasoning_client.py — Claude Reasoning Client Adapter

Thin adapter for Claude reasoning (CLI or SDK). Allows easy swapping of
backend from CLI subprocess to SDK later without changing the interface.
"""

import asyncio
import json
import logging
import os
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


class ReasoningClient:
    """Thin adapter for Claude CLI-based or SDK-based reasoning."""

    def __init__(self, model: str = "claude-3-5-sonnet-latest"):
        """
        Initialize reasoning client.

        Args:
            model: Claude model to use (e.g., "claude-3-5-sonnet-latest")
        """
        self.model = model
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    async def reason(
        self,
        prompt: str,
        context: str = "",
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        Run Claude reasoning via CLI subprocess (MVP).

        For production, this can be swapped to use the Anthropic SDK directly
        without changing the interface.

        Args:
            prompt: Main reasoning prompt
            context: Additional context/data to reason about
            system: System prompt (optional)
            temperature: Temperature for generation (0-1)
            max_tokens: Max output tokens

        Returns:
            Claude's reasoning output as string
        """
        combined_prompt = f"{system}\n\n" if system else ""
        combined_prompt += f"{prompt}\n\n"
        if context:
            combined_prompt += f"Context:\n{context}"

        try:
            # Call Claude CLI via subprocess (MVP approach)
            # TODO: Replace with anthropic SDK for production
            result = await self._call_claude_cli(combined_prompt, temperature, max_tokens)
            return result
        except Exception as e:
            logger.error(f"Claude reasoning failed: {e}")
            raise

    async def _call_claude_cli(
        self, prompt: str, temperature: float = 0.7, max_tokens: int = 2048
    ) -> str:
        """
        Call Claude CLI subprocess.

        Args:
            prompt: Full prompt to send
            temperature: Temperature setting
            max_tokens: Max output tokens

        Returns:
            Claude's response text
        """
        try:
            # Use subprocess to call Claude CLI
            # Assumes 'claude' CLI is installed and ANTHROPIC_API_KEY is set
            cmd = [
                "claude",
                "--model", self.model,
                "--temperature", str(temperature),
                "--max-tokens", str(max_tokens),
            ]

            # Run command with stdin
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate(prompt.encode("utf-8"))

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="ignore")
                logger.error(f"Claude CLI error: {error_msg}")
                raise RuntimeError(f"Claude CLI failed: {error_msg}")

            return stdout.decode("utf-8").strip()

        except FileNotFoundError:
            logger.error("Claude CLI not found. Install via: pip install anthropic[claude-cli]")
            raise RuntimeError("Claude CLI not installed")

    async def reason_with_json_output(
        self,
        prompt: str,
        context: str = "",
        *,
        system: Optional[str] = None,
        json_schema: Optional[dict] = None,
    ) -> dict:
        """
        Run Claude reasoning and expect JSON output.

        Args:
            prompt: Reasoning prompt
            context: Additional context
            system: System prompt
            json_schema: Expected JSON schema (for validation)

        Returns:
            Parsed JSON output as dict
        """
        # Append JSON instruction to prompt
        json_prompt = prompt + "\n\nRespond with ONLY valid JSON, no other text."

        response_text = await self.reason(
            json_prompt,
            context=context,
            system=system,
            temperature=0.3,  # Lower temperature for deterministic JSON
            max_tokens=4096,
        )

        try:
            result = json.loads(response_text)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude JSON response: {e}")
            logger.debug(f"Raw response: {response_text}")
            raise RuntimeError(f"Claude did not return valid JSON: {e}")
