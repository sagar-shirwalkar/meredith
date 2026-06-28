"""
Filesystem tools: read_file, edit_file, write_file, list_directory.

All paths are resolved relative to the agent's working directory.
For safety, path traversal (../) is rejected.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from coding_agent.config import AppConfig
from coding_agent.tools.base import (
    SCHEMA_EDIT_FILE,
    SCHEMA_LIST_DIRECTORY,
    SCHEMA_READ_FILE,
    SCHEMA_WRITE_FILE,
    ToolExecutor,
)
from coding_agent.types import ToolCall, ToolResult

logger = logging.getLogger(__name__)


class FsTools(ToolExecutor):
    """
    Filesystem operations: read, write, edit, list.

    All paths are relative to the configured working directory.
    Paths containing '..' are rejected for safety.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.workdir = Path(config.agent.working_directory).resolve()

    # ── Schema ────────────────────────────────────────────────

    def schemas(self) -> list[Any]:
        return [SCHEMA_READ_FILE, SCHEMA_WRITE_FILE, SCHEMA_EDIT_FILE, SCHEMA_LIST_DIRECTORY]

    # ── Dispatch ──────────────────────────────────────────────

    def _dispatch(self) -> dict[str, Callable[[ToolCall], Awaitable[ToolResult]]]:
        return {
            "read_file": self._read_file,
            "write_file": self._write_file,
            "edit_file": self._edit_file,
            "list_directory": self._list_directory,
        }

    # ── read_file ─────────────────────────────────────────────

    async def _read_file(self, call: ToolCall) -> ToolResult:
        """
        Read a file, optionally within a line range.

        Returns the file content with line numbers prefixed.
        """
        path = self._resolve_safe(call.arguments.get("path", ""))
        if path is None:
            return self._path_error(call)

        if not path.exists():
            return self._error_result(call, f"File not found: {path}", "file_not_found")

        if path.is_dir():
            return self._error_result(
                call, f"Path is a directory, not a file: {path}", "is_directory"
            )

        try:
            lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
        except OSError as exc:
            return self._error_result(call, f"Cannot read file: {exc}", str(exc))

        # Apply line range
        start = call.arguments.get("start_line", 1)
        end = call.arguments.get("end_line", len(lines))

        # Clamp to file bounds
        start = max(1, min(start, len(lines)))
        end = max(start, min(end, len(lines)))

        # Extract the requested range (1-based → 0-based)
        selected = lines[start - 1 : end]

        # Format with line numbers
        output_lines: list[str] = []
        for i, line in enumerate(selected, start=start):
            output_lines.append(f"{i:>6}\t{line}")

        output = "\n".join(output_lines)
        total_lines = len(lines)

        if end < total_lines:
            output += f"\n... [file has {total_lines} total lines, showing {start}-{end}]"

        return self._success_result(call, output)

    # ── write_file ────────────────────────────────────────────

    async def _write_file(self, call: ToolCall) -> ToolResult:
        """
        Create or replace a file with the given content.

        Creates parent directories if they don't exist.
        """
        path = self._resolve_safe(call.arguments.get("path", ""))
        if path is None:
            return self._path_error(call)

        content = call.arguments.get("content", "")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            line_count = content.count("\n") + 1
            output = f"Wrote {line_count} lines to {path}"
            return self._success_result(call, output)
        except OSError as exc:
            return self._error_result(call, f"Cannot write file: {exc}", str(exc))

    # ── edit_file ─────────────────────────────────────────────

    async def _edit_file(self, call: ToolCall) -> ToolResult:
        """
        Edit a file by replacing a search string with a replace string.

        The search string must be unique in the file (exactly one match).
        Supports regex mode if the 'regex' argument is true.
        """
        path = self._resolve_safe(call.arguments.get("path", ""))
        if path is None:
            return self._path_error(call)

        if not path.exists():
            return self._error_result(call, f"File not found: {path}", "file_not_found")

        search = call.arguments.get("search", "")
        replace = call.arguments.get("replace", "")
        use_regex = call.arguments.get("regex", False)

        if not search:
            return self._error_result(call, "Error: search string is empty", "empty_search")

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return self._error_result(call, f"Cannot read file: {exc}", str(exc))

        # Perform the search/replace
        if use_regex:
            matches = list(re.finditer(search, content))
        else:
            # Literal search — count occurrences
            matches = [m for m in re.finditer(re.escape(search), content)]

        if not matches:
            return self._error_result(
                call, f"Search string not found in {path}", "search_not_found"
            )

        if len(matches) > 1:
            locations = []
            for m in matches[:3]:
                line_num = content[: m.start()].count("\n") + 1
                locations.append(f"  Line {line_num}")
            locations_str = "\n".join(locations)
            extra = f"\n  ... and {len(matches) - 3} more" if len(matches) > 3 else ""
            output = (
                f"Search string found {len(matches)} times in {path} — "
                f"it must be unique.\n"
                f"Matches at:\n{locations_str}{extra}\n"
                f"Please provide a more specific search string."
            )
            return self._error_result(call, output, "multiple_matches")

        # Exactly one match — perform the replacement
        if use_regex:
            new_content = re.sub(search, replace, content, count=1)
        else:
            new_content = content.replace(search, replace, 1)

        try:
            path.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            return self._error_result(call, f"Cannot write file: {exc}", str(exc))

        change_line = content[: matches[0].start()].count("\n") + 1
        output = f"Edited {path} (change at line {change_line})"

        return self._success_result(call, output)

    # ── list_directory ────────────────────────────────────────

    async def _list_directory(self, call: ToolCall) -> ToolResult:
        """
        List directory contents.

        Shows files and directories with type indicators.
        """
        rel_path = call.arguments.get("path", ".")
        recursive = call.arguments.get("recursive", False)

        path = self._resolve_safe(rel_path)
        if path is None:
            return self._path_error(call)

        if not path.exists():
            return self._error_result(call, f"Directory not found: {path}", "dir_not_found")

        if not path.is_dir():
            return self._error_result(call, f"Path is a file, not a directory: {path}", "is_file")

        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as exc:
            return self._error_result(call, f"Cannot list directory: {exc}", str(exc))

        output_lines: list[str] = []
        # Respect common ignore patterns
        ignore_dirs = {
            ".git",
            "__pycache__",
            "node_modules",
            ".mypy_cache",
            ".pytest_cache",
            ".tox",
            ".venv",
            "venv",
            ".agent",
        }
        ignore_exts = {".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe"}

        for entry in entries:
            name = entry.name
            if name in ignore_dirs:
                continue
            if entry.is_file() and name.rsplit(".", 1)[-1] in ignore_exts if "." in name else False:
                continue

            if entry.is_dir():
                output_lines.append(f"  {name}/")
                # If recursive, show contents of subdirectories (1 level)
                if recursive:
                    try:
                        sub_entries = sorted(
                            entry.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
                        )
                        for sub in sub_entries[:20]:  # Limit sub-entries
                            prefix = "    " if sub.is_file() else "    "
                            output_lines.append(f"{prefix}{sub.name}")
                        if len(list(entry.iterdir())) > 20:
                            output_lines.append("    ... (more entries)")
                    except OSError:
                        pass
            else:
                size = entry.stat().st_size
                if size > 1024 * 1024:
                    size_str = f" ({size // (1024 * 1024)}MB)"
                elif size > 1024:
                    size_str = f" ({size // 1024}KB)"
                else:
                    size_str = ""
                output_lines.append(f"  {name}{size_str}")

        total = len(output_lines)
        if total > 100:
            output_lines = output_lines[:50]
            output_lines.append(f"  ... ({total - 50} more entries)")

        output = f"Contents of {rel_path}:\n" + "\n".join(output_lines)

        return self._success_result(call, output)

    # ── Safety helpers ────────────────────────────────────────

    def _resolve_safe(self, rel_path: str) -> Path | None:
        """
        Resolve a relative path safely within the working directory.

        Rejects paths that escape the working directory via '..' or
        absolute paths that don't start with the working directory.
        """
        if not rel_path:
            return self.workdir

        # Reject obvious traversal attempts
        if ".." in Path(rel_path).parts:
            logger.warning("Path traversal rejected: %s", rel_path)
            return None

        resolved = (self.workdir / rel_path).resolve()

        # Verify the resolved path is within the working directory
        try:
            resolved.relative_to(self.workdir)
        except ValueError:
            logger.warning("Path escapes working directory: %s", rel_path)
            return None

        return resolved

    def _path_error(self, call: ToolCall) -> ToolResult:
        """Return a standard error for unsafe paths."""
        return self._error_result(
            call,
            "Error: path is empty or contains '..' (path traversal rejected)",
            "unsafe_path",
        )
