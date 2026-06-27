"""
Search tools: search_code (ripgrep/grep wrapper), find_symbols,
and get_diagnostics.

search_code is the workhorse — it shells out to ripgrep (preferred)
or falls back to grep.  Output is structured for minimal token cost.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from coding_agent.config import AppConfig
from coding_agent.llm.base import count_tokens
from coding_agent.tools.base import (
    SCHEMA_FIND_SYMBOLS,
    SCHEMA_GET_DIAGNOSTICS,
    SCHEMA_SEARCH_CODE,
    ToolExecutor,
)
from coding_agent.types import ToolCall, ToolResult

logger = logging.getLogger(__name__)


class SearchTools(ToolExecutor):
    """
    Code search and analysis tools.

    Uses ripgrep when available (fast, respects .gitignore),
    falls back to GNU grep otherwise.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.workdir = Path(config.agent.working_directory).resolve()
        self._rg_path = shutil.which("rg")
        self._grep_path = shutil.which("grep")
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str:
        """Detect the best available search backend."""
        if self.config.tools.search.backend == "ripgrep" and self._rg_path:
            return "ripgrep"
        elif self._grep_path:
            return "grep"
        else:
            logger.warning("Neither ripgrep nor grep found — search_code will not work")
            return "none"

    # ── Schema ────────────────────────────────────────────────

    def schemas(self) -> list[Any]:
        return [SCHEMA_SEARCH_CODE, SCHEMA_FIND_SYMBOLS, SCHEMA_GET_DIAGNOSTICS]

    # ── Dispatch ──────────────────────────────────────────────

    async def execute(self, call: ToolCall) -> ToolResult:
        dispatch = {
            "search_code": self._search_code,
            "find_symbols": self._find_symbols,
            "get_diagnostics": self._get_diagnostics,
        }
        handler = dispatch.get(call.name)
        if handler is None:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output=f"Unknown search tool: {call.name}",
                success=False,
                error=f"unknown_search_tool: {call.name}",
            )
        return await handler(call)

    # ── search_code ───────────────────────────────────────────

    async def _search_code(self, call: ToolCall) -> ToolResult:
        """
        Search for a pattern across the codebase.

        Uses ripgrep (preferred) or grep.  Results are returned
        with file:line:content format, limited to max_results.
        """
        pattern = call.arguments.get("pattern", "")
        if not pattern:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output="Error: search pattern is empty",
                success=False,
                error="empty_pattern",
            )

        search_path = call.arguments.get("path", ".")
        file_pattern = call.arguments.get("file_pattern")
        use_regex = call.arguments.get("regex", False)
        max_results = call.arguments.get("max_results", self.config.tools.search.max_results)
        context_lines = self.config.tools.search.context_lines

        if self._backend == "none":
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output="Error: neither ripgrep nor grep is available on this system",
                success=False,
                error="no_search_backend",
            )

        try:
            if self._backend == "ripgrep":
                output = await self._ripgrep_search(
                    pattern, search_path, file_pattern, use_regex, max_results, context_lines
                )
            else:
                output = await self._grep_search(
                    pattern, search_path, file_pattern, use_regex, max_results
                )
        except asyncio.TimeoutError:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output="Search timed out after 15 seconds",
                success=False,
                error="timeout",
            )
        except Exception as exc:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output=f"Search error: {exc}",
                success=False,
                error=str(exc),
            )

        if not output.strip():
            output = f"No matches found for pattern: {pattern}"

        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            output=output,
            success=True,
            token_count=count_tokens(output),
        )

    async def _ripgrep_search(
        self,
        pattern: str,
        search_path: str,
        file_pattern: str | None,
        use_regex: bool,
        max_results: int,
        context_lines: int,
    ) -> str:
        """Execute a search using ripgrep."""
        cmd = [
            self._rg_path,  # type: ignore[list-item]
            "--line-number",
            "--color=never",
            "--no-heading",
            f"--max-count={max_results}",
        ]

        if not use_regex:
            cmd.append("--fixed-strings")

        if file_pattern:
            cmd.extend(["--glob", file_pattern])

        if context_lines > 0:
            cmd.extend(["--context", str(context_lines)])

        # Respect .gitignore and skip hidden files
        cmd.extend(["--smart-case"])

        cmd.append("--")
        cmd.append(pattern)
        cmd.append(search_path)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.workdir),
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        except asyncio.TimeoutError:
            proc.kill()
            raise

        output = stdout.decode(errors="replace").strip()

        # Ripgrep exits with code 1 when no matches — that's fine
        if proc.returncode not in (0, 1):
            error = stderr.decode(errors="replace").strip()
            if error:
                logger.warning("ripgrep error: %s", error)

        return self._format_search_output(output, max_results)

    async def _grep_search(
        self,
        pattern: str,
        search_path: str,
        file_pattern: str | None,
        use_regex: bool,
        max_results: int,
    ) -> str:
        """Execute a search using GNU grep (fallback)."""
        cmd = [
            self._grep_path,  # type: ignore[list-item]
            "--recursive",
            "--line-number",
            "--color=never",
            f"--max-count={max_results}",
            "--extended-regexp" if use_regex else "--fixed-strings",
            "--",
            pattern,
            search_path,
        ]

        # Include/exclude for file patterns
        if file_pattern:
            # Strip leading *. from glob patterns for grep --include
            glob_pattern = file_pattern.lstrip("*")
            if glob_pattern:
                cmd.insert(-3, f"--include={glob_pattern}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.workdir),
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
        except asyncio.TimeoutError:
            proc.kill()
            raise

        output = stdout.decode(errors="replace").strip()
        return self._format_search_output(output, max_results)

    @staticmethod
    def _format_search_output(raw: str, max_results: int) -> str:
        """
        Format search output for the LLM.

        Truncates long lines and limits total output size.
        """
        if not raw:
            return ""

        lines = raw.split("\n")
        result_lines: list[str] = []
        count = 0

        for line in lines:
            if count >= max_results:
                result_lines.append(f"... ({len(lines) - max_results} more matches)")
                break

            # Truncate very long lines
            if len(line) > 200:
                line = line[:197] + "..."

            result_lines.append(line)
            count += 1

        return "\n".join(result_lines)

    # ── find_symbols ──────────────────────────────────────────

    async def _find_symbols(self, call: ToolCall) -> ToolResult:
        """
        Find symbol definitions in source files.

        Uses regex-based pattern matching for common language
        constructs (def, class, function, etc.).  This is a
        lightweight alternative to a full AST-based index.

        When the RAG system is available, it provides a richer
        symbol search — this is the fallback.
        """
        query = call.arguments.get("query", "")
        if not query:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output="Error: query is empty",
                success=False,
                error="empty_query",
            )

        search_path = call.arguments.get("path", ".")

        # Build regex patterns for common symbol definitions
        # Python: def foo, class Foo
        # TypeScript/JS: function foo, class Foo, const foo
        # Rust: fn foo, struct Foo, impl Foo
        # Go: func foo, type Foo
        escaped = re.escape(query)
        symbol_patterns = [
            # Python
            rf"^\s*(def|class)\s+{escaped}\b",
            # TypeScript / JavaScript
            rf"^\s*(export\s+)?(function|class|const|let|var|interface|type)\s+{escaped}\b",
            # Rust
            rf"^\s*(pub\s+)?(fn|struct|enum|impl|trait)\s+{escaped}\b",
            # Go
            rf"^\s*func\s+.*{escaped}\b",
            rf"^\s*type\s+{escaped}\b",
        ]

        combined = "|".join(symbol_patterns)

        # Use ripgrep for the search
        if self._backend == "none":
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output="Error: no search backend available",
                success=False,
                error="no_search_backend",
            )

        try:
            if self._backend == "ripgrep":
                output = await self._ripgrep_search(
                    combined, search_path, None, use_regex=True, max_results=15, context_lines=0
                )
            else:
                output = await self._grep_search(
                    combined, search_path, None, use_regex=True, max_results=15
                )
        except Exception as exc:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output=f"Symbol search error: {exc}",
                success=False,
                error=str(exc),
            )

        if not output.strip():
            output = f"No symbol definitions found for: {query}"

        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            output=output,
            success=True,
            token_count=count_tokens(output),
        )

    # ── get_diagnostics ───────────────────────────────────────

    async def _get_diagnostics(self, call: ToolCall) -> ToolResult:
        """
        Run linter/type-checker on a file.

        Auto-detects the appropriate tool based on file extension.
        """
        path_str = call.arguments.get("path", "")
        if not path_str:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output="Error: path is empty",
                success=False,
                error="empty_path",
            )

        # Resolve path
        path = self.workdir / path_str
        if not path.exists():
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output=f"File not found: {path_str}",
                success=False,
                error="file_not_found",
            )

        ext = path_str.rsplit(".", 1)[-1] if "." in path_str else ""
        diag_output = ""

        if ext == "py":
            diag_output = await self._diag_python(path)
        elif ext in ("ts", "tsx", "js", "jsx"):
            diag_output = await self._diag_typescript(path)
        elif ext == "rs":
            diag_output = await self._diag_rust()
        elif ext == "go":
            diag_output = await self._diag_go(path)
        else:
            diag_output = f"No diagnostics available for .{ext} files"

        if not diag_output.strip():
            diag_output = f"No issues found in {path_str}"

        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            output=diag_output,
            success=True,
            token_count=count_tokens(diag_output),
        )

    async def _diag_python(self, path: Path) -> str:
        """Run Python diagnostics (ruff or pyflakes)."""
        # Try ruff first (faster, more comprehensive)
        for tool in [("ruff", ["ruff", "check", "--output-format=concise"]),
                      ("pyflakes", ["python3", "-m", "pyflakes"])]:
            name, base_cmd = tool
            if not shutil.which(name):
                continue
            try:
                proc = await asyncio.create_subprocess_exec(
                    *base_cmd, str(path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.workdir),
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                output = stdout.decode(errors="replace").strip()
                if output:
                    return output
            except (asyncio.TimeoutError, FileNotFoundError):
                continue
        return ""

    async def _diag_typescript(self, path: Path) -> str:
        """Run TypeScript diagnostics (tsc --noEmit)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "npx", "tsc", "--noEmit", "--pretty", "false",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workdir),
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
            output = stdout.decode(errors="replace").strip()
            # Filter to only errors related to our file
            relevant = [l for l in output.split("\n") if str(path) in l or path.name in l]
            return "\n".join(relevant[:10])
        except (asyncio.TimeoutError, FileNotFoundError):
            return ""

    async def _diag_rust(self) -> str:
        """Run Rust diagnostics (cargo check)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "cargo", "check", "--message-format=short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workdir),
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stderr.decode(errors="replace").strip()
            errors = [l for l in output.split("\n") if "error" in l.lower()][:10]
            return "\n".join(errors)
        except (asyncio.TimeoutError, FileNotFoundError):
            return ""

    async def _diag_go(self, path: Path) -> str:
        """Run Go diagnostics (go vet)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "go", "vet", str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workdir),
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            return stderr.decode(errors="replace").strip()
        except (asyncio.TimeoutError, FileNotFoundError):
            return ""
