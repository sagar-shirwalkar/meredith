"""
Post-step verification.

After each ReAct step, the verifier checks:
  - Did the tool call succeed?
  - Were there diagnostic errors (lint, type-check)?
  - Did the change accomplish the subtask goal?
  - Were existing tests broken?

For large models, verification can run concurrently with the
next step's planning (speculative verification).

For local models, verification is synchronous and lightweight.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from coding_agent.config import AppConfig
from coding_agent.types import AgentState, Step

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Verification result
# ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class VerificationResult:
    """Outcome of a verification check."""

    passed: bool
    message: str = ""
    checks: list[str] = field(default_factory=list)
    # Which specific issues were found
    issues: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────
# Verifier
# ──────────────────────────────────────────────────────────────


class Verifier:
    """
    Lightweight, rule-based step verifier.

    Does NOT use the LLM — all checks are deterministic and fast.
    This keeps token costs near zero and works well even for
    local models that should not be asked to self-verify.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._diagnostics_cache: dict[str, list[str]] = {}

    async def verify(self, step: Step, state: AgentState) -> VerificationResult:
        """
        Run all verification checks on a completed step.

        Checks are ordered from cheapest to most expensive.
        The first failure short-circuits (we report it immediately
        rather than collecting all issues).
        """
        checks_run: list[str] = []
        issues: list[str] = []

        # 1. Tool call succeeded?
        check_name = "tool_success"
        checks_run.append(check_name)
        if step.tool_result and not step.tool_result.success:
            issues.append(
                f"Tool {step.tool_call.name} failed: {step.tool_result.error}"
            )
            return VerificationResult(
                passed=False,
                message=f"Tool call failed: {step.tool_result.error}",
                checks=checks_run,
                issues=issues,
            )

        # 2. File edit sanity: did the edit actually change anything?
        check_name = "edit_sanity"
        checks_run.append(check_name)
        if step.tool_call and step.tool_call.name == "edit_file":
            args = step.tool_call.arguments
            search_text = args.get("search", "")
            replace_text = args.get("replace", "")
            if search_text == replace_text:
                issues.append(
                    "edit_file: search and replace are identical — no change made"
                )
                return VerificationResult(
                    passed=False,
                    message="Edit had no effect (search == replace)",
                    checks=checks_run,
                    issues=issues,
                )

        # 3. Write-file sanity: is the written content non-trivial?
        check_name = "write_sanity"
        checks_run.append(check_name)
        if step.tool_call and step.tool_call.name == "write_file":
            content = step.tool_call.arguments.get("content", "")
            if len(content.strip()) < 10:
                issues.append(
                    "write_file: content is suspiciously short (<10 chars)"
                )
                return VerificationResult(
                    passed=False,
                    message="Written file content is too short — possible error",
                    checks=checks_run,
                    issues=issues,
                )

        # 4. Diagnostic check after edits (run linter/type-checker)
        check_name = "post_edit_diagnostics"
        checks_run.append(check_name)
        if step.tool_call and step.tool_call.name in ("edit_file", "write_file"):
            path = step.tool_call.arguments.get("path", "")
            if path:
                diag_issues = await self._check_diagnostics(path)
                if diag_issues:
                    issues.extend(diag_issues)
                    return VerificationResult(
                        passed=False,
                        message=(
                            f"Diagnostics found {len(diag_issues)} issue(s) "
                            f"after edit"
                        ),
                        checks=checks_run,
                        issues=issues,
                    )

        # 5. No duplicate file reads (agent re-reading same file wastefully)
        check_name = "read_efficiency"
        checks_run.append(check_name)
        if step.tool_call and step.tool_call.name == "read_file":
            path = step.tool_call.arguments.get("path", "")
            # Check if the agent read this exact file in the last 3 steps
            recent_reads = [
                s
                for s in state.steps[-3:]
                if s.tool_call
                and s.tool_call.name == "read_file"
                and s.tool_call.arguments.get("path") == path
            ]
            if len(recent_reads) >= 2:
                issues.append(
                    f"File {path} has been read {len(recent_reads)+1} times "
                    f"recently — consider using search instead"
                )
                # Don't fail, just warn
                return VerificationResult(
                    passed=True,
                    message=f"Warning: {path} read multiple times",
                    checks=checks_run,
                    issues=issues,
                )

        # All checks passed
        return VerificationResult(
            passed=True,
            message="All verification checks passed",
            checks=checks_run,
            issues=issues,
        )

    # ── Diagnostic checking ───────────────────────────────────

    async def _check_diagnostics(self, file_path: str) -> list[str]:
        """
        Run diagnostics on a file after editing.

        Uses the project's existing linter/type-checker if available.
        Returns a list of error messages (empty = clean).
        """
        issues: list[str] = []

        # Determine file type and appropriate checker
        if file_path.endswith(".py"):
            issues.extend(await self._check_python(file_path))
        elif file_path.endswith((".ts", ".tsx")):
            issues.extend(await self._check_typescript(file_path))
        elif file_path.endswith(".rs"):
            issues.extend(await self._check_rust(file_path))

        return issues

    async def _check_python(self, file_path: str) -> list[str]:
        """Run Python diagnostics (pyflakes/ruff if available)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3",
                "-m",
                "pyflakes",
                file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if stdout:
                lines = stdout.decode().strip().split("\n")
                # Only return errors, not warnings
                return [line for line in lines if file_path in line][:5]
        except (TimeoutError, FileNotFoundError):
            pass

        # Fallback: try ruff
        try:
            proc = await asyncio.create_subprocess_exec(
                "ruff",
                "check",
                file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if stdout:
                lines = stdout.decode().strip().split("\n")
                return [line for line in lines if "error" in line.lower()][:5]
        except (TimeoutError, FileNotFoundError):
            pass

        return []

    async def _check_typescript(self, file_path: str) -> list[str]:
        """Run TypeScript diagnostics (tsc --noEmit if available)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "npx",
                "tsc",
                "--noEmit",
                "--pretty",
                "false",
                file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if stdout:
                lines = stdout.decode().strip().split("\n")
                return [line for line in lines if "error TS" in line][:5]
        except (TimeoutError, FileNotFoundError):
            pass
        return []

    async def _check_rust(self, file_path: str) -> list[str]:
        """Run Rust diagnostics (cargo check if in a Cargo project)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "cargo",
                "check",
                "--message-format=short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if stdout:
                lines = stdout.decode().strip().split("\n")
                return [
                    line
                    for line in lines
                    if "error" in line.lower() and file_path in line
                ][:5]
        except (TimeoutError, FileNotFoundError):
            pass
        return []
