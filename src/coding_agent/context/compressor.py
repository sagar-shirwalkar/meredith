"""
Output compressor: reduces token cost of tool results before
they enter the context window.

Different tool outputs need different compression strategies:
  - run_command: keep summary + failures only
  - read_file: strip docstrings, blank lines, comments
  - find_references: compact into one line per reference
  - search_code: limit to top N matches, truncate long lines
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Maximum characters for a single output after compression
_HARD_CHAR_LIMIT = 4000


class OutputCompressor:
    """
    Compresses tool outputs to fit within token budgets.

    All methods are pure functions (no state) so the compressor
    can be called freely from any context zone.
    """

    def compress(
        self,
        tool_name: str,
        output: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """
        Compress a tool output based on the tool type and current
        budget pressure.

        Args:
            tool_name: Name of the tool that produced the output.
            output: Raw tool output string.
            context: Optional dict with budget_remaining (0.0–1.0)
                     and other hints.

        Returns:
            Compressed output string.
        """
        ctx = context or {}
        budget_fraction = ctx.get("budget_remaining", 1.0)

        # Select compression strategy by tool
        if tool_name == "run_command":
            result = self._compress_command_output(output, budget_fraction)
        elif tool_name == "read_file":
            result = self._compress_file_output(output, budget_fraction)
        elif tool_name == "search_code":
            result = self._compress_search_output(output, budget_fraction)
        elif tool_name == "find_references":
            result = self._compress_references(output, budget_fraction)
        elif tool_name == "list_directory":
            result = self._compress_directory(output, budget_fraction)
        else:
            result = output

        # Hard character limit — never exceed this
        if len(result) > _HARD_CHAR_LIMIT:
            result = self._truncate_middle(result, _HARD_CHAR_LIMIT)

        return result

    # ── Command output compression ────────────────────────────

    def _compress_command_output(self, output: str, budget: float) -> str:
        """
        Compress terminal/command output.

        Strategies:
          - Test output: keep summary line + failures only
          - Build/lint output: keep errors and warnings
          - General: head + tail
        """
        lines = output.split("\n")

        # Detect test output (pytest, vitest, jest, go test, cargo test)
        if self._looks_like_test_output(output):
            return self._extract_test_summary(output)

        # Detect build/lint output (lots of "error" / "warning")
        if self._looks_like_error_output(output):
            return self._extract_errors(output)

        # General truncation: keep head + tail
        if budget > 0.5:
            max_lines = 60
        elif budget > 0.2:
            max_lines = 30
        else:
            max_lines = 15

        if len(lines) <= max_lines:
            return output

        head_count = max_lines // 2
        tail_count = max_lines - head_count - 1
        head = "\n".join(lines[:head_count])
        tail = "\n".join(lines[-tail_count:])
        omitted = len(lines) - head_count - tail_count
        return f"{head}\n... [{omitted} lines omitted] ...\n{tail}"

    def _looks_like_test_output(self, output: str) -> bool:
        """Heuristic: does this look like test runner output?"""
        lower = output.lower()
        return any(
            marker in lower
            for marker in ("passed", "failed", "pytest", "vitest", "jest", "go test", "cargo test")
        )

    def _looks_like_error_output(self, output: str) -> bool:
        """Heuristic: does this look like compiler/linter output?"""
        lower = output.lower()
        error_count = lower.count("error")
        warning_count = lower.count("warning")
        return (error_count + warning_count) >= 3

    def _extract_test_summary(self, output: str) -> str:
        """
        Extract test summary and failure details.

        Keeps:
          - The summary line (e.g. "5 passed, 1 failed in 0.3s")
          - Failure details (lines after "FAILURES" or "FAILED")
          - Everything else is dropped
        """
        lines = output.split("\n")
        result_lines: list[str] = []
        in_failures = False
        failure_indent = 0

        for line in lines:
            stripped = line.strip()

            # Capture summary line
            if re.search(r"\d+ (passed|failed|skipped|error)", stripped.lower()):
                result_lines.append(line)
                continue

            # Detect start of failure section
            if re.match(r"^(FAILURES|FAILED|FAIL\s)", stripped, re.IGNORECASE):
                in_failures = True
                failure_indent = len(line) - len(line.lstrip())
                result_lines.append(line)
                continue

            # Capture failure details (indented under FAILURES)
            if in_failures:
                current_indent = len(line) - len(line.lstrip()) if stripped else 0
                if stripped and current_indent <= failure_indent and not stripped.startswith("_"):
                    # New top-level section — stop capturing failures
                    in_failures = False
                else:
                    result_lines.append(line)
                    continue

        if not result_lines:
            # Fallback: return last 20 lines
            return "\n".join(lines[-20:])

        compressed = "\n".join(result_lines)
        if len(compressed) > _HARD_CHAR_LIMIT:
            return self._truncate_middle(compressed, _HARD_CHAR_LIMIT)
        return compressed

    def _extract_errors(self, output: str) -> str:
        """Extract only lines containing 'error' or 'warning'."""
        lines = output.split("\n")
        error_lines = [
            line for line in lines
            if "error" in line.lower() or "warning" in line.lower()
        ]
        if not error_lines:
            # Fallback: last 20 lines
            return "\n".join(lines[-20:])
        return "\n".join(error_lines[:50])

    # ── File output compression ───────────────────────────────

    def _compress_file_output(self, output: str, budget: float) -> str:
        """
        Compress file content read by the agent.

        At high budget: keep everything.
        At medium budget: strip blank lines and comments.
        At low budget: strip everything non-essential.
        """
        if budget > 0.6:
            return output

        lines = output.split("\n")
        compressed: list[str] = []
        in_docstring = False
        docstring_char: str | None = None

        for line in lines:
            stripped = line.strip()

            # Track docstrings (""" or ''')
            if not in_docstring:
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    docstring_char = stripped[:3]
                    if stripped.count(docstring_char) >= 2 and len(stripped) > 3:
                        # Single-line docstring — skip it
                        continue
                    in_docstring = True
                    continue
            else:
                if docstring_char and docstring_char in stripped:
                    in_docstring = False
                continue

            # Skip blank lines when budget is tight
            if budget < 0.3 and not stripped:
                continue

            # Skip inline comments (but keep TODO/FIXME/HACK)
            if "#" in line and not stripped.startswith("#"):
                code_part = line.split("#")[0].rstrip()
                comment_part = line[len(code_part):]
                if any(tag in comment_part.upper() for tag in ("TODO", "FIXME", "HACK", "XXX")):
                    compressed.append(line)
                elif code_part:
                    compressed.append(code_part)
                continue

            # Skip standalone comment lines at low budget
            if budget < 0.3 and stripped.startswith("#"):
                if any(tag in stripped.upper() for tag in ("TODO", "FIXME", "HACK", "XXX")):
                    compressed.append(line)
                continue

            compressed.append(line)

        return "\n".join(compressed)

    # ── Search output compression ─────────────────────────────

    def _compress_search_output(self, output: str, budget: float) -> str:
        """
        Compress search/grep results.

        Keep the first N matching lines and truncate long lines.
        """
        lines = output.split("\n")

        max_lines = 30 if budget > 0.3 else 15
        max_line_length = 200 if budget > 0.3 else 120

        result: list[str] = []
        for line in lines[:max_lines]:
            if len(line) > max_line_length:
                result.append(line[:max_line_length] + " ...")
            else:
                result.append(line)

        if len(lines) > max_lines:
            result.append(f"... {len(lines) - max_lines} more matches omitted")

        return "\n".join(result)

    # ── Reference output compression ──────────────────────────

    def _compress_references(self, output: str, budget: float) -> str:
        """
        Compress find_references output.

        Keep one line per reference location.
        """
        lines = output.split("\n")
        if len(lines) <= 20:
            return output

        # Keep first 15 + last 5
        head = lines[:15]
        tail = lines[-5:]
        omitted = len(lines) - 20
        head.append(f"... {omitted} references omitted ...")
        return "\n".join(head + tail)

    # ── Directory listing compression ─────────────────────────

    def _compress_directory(self, output: str, budget: float) -> str:
        """
        Compress directory listing.

        At low budget, show only top-level entries.
        """
        if budget > 0.3:
            return output

        lines = output.split("\n")
        # Keep only non-indented lines (top-level entries)
        top_level = [
            line for line in lines
            if line and not line.startswith(" ") and not line.startswith("\t")
        ]
        return "\n".join(top_level[:50])

    # ── Utility ───────────────────────────────────────────────

    @staticmethod
    def _truncate_middle(text: str, max_length: int) -> str:
        """Truncate text in the middle, keeping head and tail."""
        if len(text) <= max_length:
            return text
        head_len = max_length // 2 - 20
        tail_len = max_length - head_len - 30
        return (
            text[:head_len]
            + "\n... [heavily truncated] ...\n"
            + text[-tail_len:]
        )
