"""
Text-mode command parser: translates natural-language commands into
structured ToolCall objects when the LLM cannot use function-calling.

Used by AgentCore._execute_step() when ``_tools_enabled`` is False
(local models that don't support tool calling, such as <1B-7B models).

Pattern: regex-based matching against a set of known command patterns.
Each pattern extracts tool name and arguments from free-text output.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from coding_agent.types import ToolCall

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Command patterns — ordered by specificity (most specific first)
# ──────────────────────────────────────────────────────────────

_COMMAND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # read_file: "read src/main.py", "read file src/main.py lines 20-40"
    (
        "read_file",
        re.compile(
            r"(?:read|open|show)\s+(?:file\s+)?"
            r"(?P<path>\S+)"
            r"(?:\s+(?:lines?\s+)?(?P<start_line>\d+)(?:[-\s]+\s*(?P<end_line>\d+))?)?",
            re.IGNORECASE,
        ),
    ),
    # write_file: "write src/new.py", "create file src/new.py"
    (
        "write_file",
        re.compile(
            r"(?:write|create|save)\s+(?:file\s+)?"
            r"(?P<path>\S+)",
            re.IGNORECASE,
        ),
    ),
    # edit_file: "edit src/main.py [search] -> [replace]"
    (
        "edit_file",
        re.compile(
            r"(?:edit|update|modify)\s+(?:file\s+)?"
            r"(?P<path>\S+)\s+"
            r"(?:search\s+)?(?:`(?P<search>[^`]+)`|(?P<search2>.+?))\s*"
            r"(?:->|→|with|to|replace\s+(?:with|by)?)\s*"
            r"(?:`(?P<replace>[^`]+)`|(?P<replace2>.+))",
            re.IGNORECASE,
        ),
    ),
    # search_code: "search for X", "find X in src/", "grep X"
    (
        "search_code",
        re.compile(
            r"(?:search|find|grep|look\s+for)\s+"
            r"(?:for\s+)?(?:code\s+)?"
            r"(?:pattern\s+)?"
            r"(?:`(?P<pattern>[^`]+)`|(?P<pattern2>\S+(?:\s+\S+)*?))"
            r"(?:\s+in\s+(?P<path>\S+))?"
            r"(?:\s+filter\s+(?P<file_pattern>\S+))?",
            re.IGNORECASE,
        ),
    ),
    # list_directory: "list dir", "list", "ls src/"
    (
        "list_directory",
        re.compile(
            r"(?:list|ls)\s+"
            r"(?:dir(?:ectory)?\s+)?"
            r"(?P<path>\S+)?"
            r"(?:\s+--recursive)?",
            re.IGNORECASE,
        ),
    ),
    # run_command: "run pytest", "run: pytest", "run command pytest"
    (
        "run_command",
        re.compile(
            r"(?:run|execute|bash|shell)\s+"
            r"(?:command\s+)?"
            r"(?:`(?P<command>[^`]+)`|(?P<command2>.+))",
            re.IGNORECASE,
        ),
    ),
]

# Fallback: single-word or short patterns that are unambiguous
_SIMPLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "list_directory",
        re.compile(r"^(?:list|ls)\s*$", re.IGNORECASE),
    ),
    (
        "git_status",
        re.compile(r"(?:git\s+)?status", re.IGNORECASE),
    ),
    (
        "git_diff",
        re.compile(r"(?:git\s+)?diff", re.IGNORECASE),
    ),
    (
        "git_log",
        re.compile(r"(?:git\s+)?log", re.IGNORECASE),
    ),
]


def parse_text_command(text: str) -> ToolCall | None:
    """
    Translate a natural-language command into a ToolCall.

    Tries specific patterns first, then simple patterns.
    Returns None if no pattern matches.

    The *text* should be a single line or short block containing
    the command. The caller (AgentCore) should extract the most
    command-like portion of the LLM's response.
    """
    # Strip common wrappers: backtick blocks, parenthetical notes
    cleaned = text.strip().rstrip(".!").strip()

    # Try specific patterns
    for tool_name, pattern in _COMMAND_PATTERNS:
        m = pattern.search(cleaned)
        if m:
            args: dict[str, Any] = {}
            gd = m.groupdict()

            if tool_name == "read_file":
                args["path"] = gd["path"]
                if gd.get("start_line"):
                    args["start_line"] = int(gd["start_line"])
                if gd.get("end_line"):
                    args["end_line"] = int(gd["end_line"])

            elif tool_name == "write_file":
                args["path"] = gd["path"]

            elif tool_name == "edit_file":
                args["path"] = gd["path"]
                args["search"] = gd.get("search") or gd.get("search2", "").strip()
                args["replace"] = gd.get("replace") or gd.get("replace2", "").strip()

            elif tool_name == "search_code":
                args["pattern"] = gd.get("pattern") or gd.get("pattern2", "").strip()
                if gd.get("path"):
                    args["path"] = gd["path"]
                if gd.get("file_pattern"):
                    args["file_pattern"] = gd["file_pattern"]

            elif tool_name == "list_directory":
                args["path"] = gd.get("path") or "."

            elif tool_name == "run_command":
                args["command"] = gd.get("command") or gd.get("command2", "").strip()

            logger.debug(
                "Text-mode parsed %r → %s(%s)",
                cleaned[:60],
                tool_name,
                ", ".join(f"{k}={v!r}" for k, v in args.items()),
            )
            return ToolCall(id=f"text_{tool_name}", name=tool_name, arguments=args)

    # Try simple patterns
    for tool_name, pattern in _SIMPLE_PATTERNS:
        m = pattern.match(cleaned)
        if m:
            args = {}
            if tool_name == "list_directory":
                args["path"] = "."
            logger.debug("Text-mode simple match: %s", tool_name)
            return ToolCall(id=f"text_{tool_name}", name=tool_name, arguments=args)

    return None


def extract_command_from_response(response: str) -> str | None:
    """
    Extract the most command-like line from an LLM text response.

    Looks for:
      1. Lines starting with a known command verb
      2. Lines inside fenced code blocks (```...```)
      3. The first line that resembles a command

    Returns the extracted command text, or None.
    """
    lines = response.split("\n")

    # First, try to find a fenced code block containing a command
    in_block = False
    for line in lines:
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        if in_block and _looks_like_command(line.strip()):
            return line.strip()

    # Next, look for lines starting with known verbs
    for line in lines:
        stripped = line.strip()
        if _looks_like_command(stripped):
            return stripped

    # Finally, try the first non-empty, non-trivial line
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) > 10 and len(stripped) < 500:
            return stripped

    return None


def _looks_like_command(text: str) -> bool:
    """Quick heuristic: does *text* start with a known command verb?"""
    verbs = {
        "read",
        "open",
        "show",
        "write",
        "create",
        "save",
        "edit",
        "update",
        "modify",
        "search",
        "find",
        "grep",
        "list",
        "ls",
        "run",
        "execute",
        "bash",
        "shell",
        "look",
    }
    first_word = text.split()[0].lower().rstrip(".:") if text else ""
    return first_word in verbs
