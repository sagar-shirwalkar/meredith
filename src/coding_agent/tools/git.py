"""
Git tools: status, diff, log, commit.

All operations are run as subprocesses in the working directory.
Commit requires explicit user consent unless auto_commit is enabled
in the configuration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from coding_agent.config import AppConfig
from coding_agent.llm.base import count_tokens
from coding_agent.tools.base import (
    SCHEMA_GIT_COMMIT,
    SCHEMA_GIT_DIFF,
    SCHEMA_GIT_LOG,
    SCHEMA_GIT_STATUS,
    ToolExecutor,
)
from coding_agent.types import ToolCall, ToolResult

logger = logging.getLogger(__name__)


class GitTools(ToolExecutor):
    """
    Git operations via the git CLI.

    All commands run in the configured working directory.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.workdir = str(config.agent.working_directory)

    # ── Schema ────────────────────────────────────────────────

    def schemas(self) -> list[Any]:
        return [SCHEMA_GIT_STATUS, SCHEMA_GIT_DIFF, SCHEMA_GIT_LOG, SCHEMA_GIT_COMMIT]

    # ── Dispatch ──────────────────────────────────────────────

    async def execute(self, call: ToolCall) -> ToolResult:
        dispatch = {
            "git_status": self._git_status,
            "git_diff": self._git_diff,
            "git_log": self._git_log,
            "git_commit": self._git_commit,
        }
        handler = dispatch.get(call.name)
        if handler is None:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output=f"Unknown git tool: {call.name}",
                success=False,
                error=f"unknown_git_tool: {call.name}",
            )
        return await handler(call)

    # ── git_status ────────────────────────────────────────────

    async def _git_status(self, call: ToolCall) -> ToolResult:
        """Show git working tree status."""
        output = await self._run_git("status", "--short", "--branch")
        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            output=output,
            success=True,
            token_count=count_tokens(output),
        )

    # ── git_diff ──────────────────────────────────────────────

    async def _git_diff(self, call: ToolCall) -> ToolResult:
        """Show changes (staged or unstaged)."""
        staged = call.arguments.get("staged", False)
        path = call.arguments.get("path")

        args = ["diff"]
        if staged:
            args.append("--staged")
        if path:
            args.append("--")
            args.append(path)

        output = await self._run_git(*args)
        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            output=output,
            success=True,
            token_count=count_tokens(output),
        )

    # ── git_log ───────────────────────────────────────────────

    async def _git_log(self, call: ToolCall) -> ToolResult:
        """Show commit logs."""
        n = call.arguments.get("n", 10)
        path = call.arguments.get("path")

        args = [
            "log",
            f"--max-count={n}",
            "--oneline",
            "--decorate",
        ]
        if path:
            args.extend(["--", path])

        output = await self._run_git(*args)
        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            output=output,
            success=True,
            token_count=count_tokens(output),
        )

    # ── git_commit ────────────────────────────────────────────

    async def _git_commit(self, call: ToolCall) -> ToolResult:
        """
        Commit staged changes with a message.

        Unless auto_commit is enabled in config, this requires
        explicit user consent (the agent must ask before committing).
        """
        if not self.config.tools.git.auto_commit:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output=(
                    "Commit blocked: auto_commit is disabled. "
                    "Ask the user for permission before committing."
                ),
                success=False,
                error="auto_commit_disabled",
            )

        message = call.arguments.get("message", "")
        if not message:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output="Error: commit message is empty",
                success=False,
                error="empty_message",
            )

        # Stage all modified files first
        await self._run_git("add", "-A")

        output = await self._run_git("commit", "-m", message)
        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            output=output,
            success=True,
            token_count=count_tokens(output),
        )

    # ── Helper ────────────────────────────────────────────────

    async def _run_git(self, *args: str) -> str:
        """
        Run a git command and return its stdout.

        Returns an error message string if the command fails.
        """
        cmd = ["git", *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workdir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)

            output = stdout.decode(errors="replace").strip()
            error = stderr.decode(errors="replace").strip()

            if proc.returncode != 0:
                if error:
                    return f"git error (exit {proc.returncode}): {error}"
                if not output:
                    return f"git error (exit {proc.returncode})"

            return output if output else "(no output)"

        except FileNotFoundError:
            return "Error: git is not installed or not in PATH"
        except TimeoutError:
            return "Error: git command timed out"
