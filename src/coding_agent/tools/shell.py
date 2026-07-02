"""
Shell tools: run_command.

Executes shell commands via asyncio subprocess. The output is
captured and returned as the tool result.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from coding_agent.config import AppConfig
from coding_agent.tools.base import SCHEMA_RUN_COMMAND, ToolExecutor
from coding_agent.types import ToolCall, ToolResult

logger = logging.getLogger(__name__)


class ShellTools(ToolExecutor):
    """
    Shell command execution via asyncio subprocess.

    Commands run in the configured working directory with a
    configurable timeout.  The full stdout/stderr is returned.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.workdir = str(Path(config.agent.working_directory).resolve())

    # ── Schema ────────────────────────────────────────────────

    def schemas(self) -> list[Any]:
        return [SCHEMA_RUN_COMMAND]

    # ── Dispatch ──────────────────────────────────────────────

    def _dispatch(self) -> dict[str, Callable[[ToolCall], Awaitable[ToolResult]]]:
        return {
            "run_command": self._run_command,
        }

    # ── run_command ───────────────────────────────────────────

    async def _run_command(self, call: ToolCall) -> ToolResult:
        """Execute a shell command and return its output."""
        command: str = call.arguments.get("command", "")
        cwd: str = call.arguments.get("cwd", self.workdir)
        timeout: int = int(call.arguments.get("timeout", self.config.agent.step_timeout_seconds))

        if not command.strip():
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output="",
                success=False,
                error="No command provided",
            )

        logger.info("Running command: %s (cwd=%s, timeout=%ds)", command[:200], cwd, timeout)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )

            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            exit_code = proc.returncode or 0

            success = exit_code == 0
            # Truncate very long output
            if len(output) > 100_000:
                output = output[:100_000] + f"\n... (truncated, {len(output)} total chars)"

            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output=output,
                success=success,
                error="" if success else f"exit code {exit_code}",
            )

        except TimeoutError:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output="",
                success=False,
                error=f"Command timed out after {timeout}s",
            )
        except Exception as exc:
            logger.exception("Command failed: %s", command[:200])
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output="",
                success=False,
                error=str(exc),
            )
