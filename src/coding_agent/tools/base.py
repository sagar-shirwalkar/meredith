"""
Tool registry: schema definitions and executor protocol.

The registry holds all tool schemas (for LLM function-calling)
and their executor implementations.  Tools are registered at
startup and looked up by name during the ReAct loop.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from coding_agent.config import AppConfig
from coding_agent.types import ToolCall, ToolParameter, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Executor protocol
# ──────────────────────────────────────────────────────────────


class ToolExecutor(ABC):
    """
    Abstract base for tool executors.

    Each tool type (fs, search, web, git) implements this
    interface.  The registry dispatches calls to the right executor.
    """

    @abstractmethod
    async def execute(self, call: ToolCall) -> ToolResult:
        """
        Execute a tool call and return the result.

        Implementations must:
          - Validate arguments
          - Execute the operation (with timeout)
          - Return a ToolResult with output text
        """
        ...

    @abstractmethod
    def schemas(self) -> list[ToolSchema]:
        """Return the tool schemas this executor provides."""
        ...


# ──────────────────────────────────────────────────────────────
# Tool registry
# ──────────────────────────────────────────────────────────────


class ToolRegistry:
    """
    Central registry of all available tools.

    Holds schemas (for LLM prompt) and executors (for running calls).
    Tools are registered by name and looked up during execution.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        # name → ToolSchema
        self.schemas: dict[str, ToolSchema] = {}
        # name → ToolExecutor
        self.executors: dict[str, ToolExecutor] = {}
        self._initialized = False

    async def setup(self) -> None:
        """
        Discover and register all built-in tools.

        Called once during agent startup.  Imports are lazy to
        avoid circular dependencies and keep startup fast.
        """
        if self._initialized:
            return

        from coding_agent.tools.fs import FsTools
        from coding_agent.tools.search import SearchTools
        from coding_agent.tools.web import WebTools
        from coding_agent.tools.git import GitTools

        executor_instances: list[ToolExecutor] = [
            FsTools(self.config),
            SearchTools(self.config),
            WebTools(self.config),
            GitTools(self.config),
        ]

        for executor in executor_instances:
            await self._register_executor(executor)

        self._initialized = True
        logger.info("Tool registry initialised: %d tools registered", len(self.schemas))

    async def _register_executor(self, executor: ToolExecutor) -> None:
        """Register all schemas from an executor."""
        for schema in executor.schemas():
            name = schema.name
            if name in self.schemas:
                logger.warning("Duplicate tool name %r — overwriting", name)
            self.schemas[name] = schema
            self.executors[name] = executor

    async def execute(self, call: ToolCall) -> ToolResult:
        """
        Execute a tool call by dispatching to the right executor.

        If the tool name is unknown, returns an error ToolResult.
        """
        executor = self.executors.get(call.name)
        if executor is None:
            logger.error("Unknown tool: %s", call.name)
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output=f"Error: unknown tool '{call.name}'",
                success=False,
                error=f"unknown_tool: {call.name}",
            )

        try:
            result = await executor.execute(call)
            return result
        except Exception as exc:
            logger.exception("Tool %s raised an exception", call.name)
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output=f"Tool execution error: {exc}",
                success=False,
                error=str(exc),
            )

    async def close(self) -> None:
        """Tear down any resources held by executors."""
        for executor in self.executors.values():
            if hasattr(executor, "close"):
                await executor.close()  # type: ignore[attr-defined]

    def available_tool_names(self) -> list[str]:
        """Return sorted list of all registered tool names."""
        return sorted(self.schemas.keys())

    def get_schemas_for_names(self, names: list[str]) -> list[ToolSchema]:
        """Return schemas for the given tool names, skipping unknowns."""
        return [self.schemas[n] for n in names if n in self.schemas]


# ──────────────────────────────────────────────────────────────
# Built-in tool schema definitions
# ──────────────────────────────────────────────────────────────

# These are defined here so they can be referenced by both the
# executors and the router without circular imports.


SCHEMA_READ_FILE = ToolSchema(
    name="read_file",
    description="Read contents of a file, optionally a specific line range. Prefer over write_file for understanding code.",
    parameters=[
        ToolParameter(name="path", type="str", description="File path relative to project root"),
        ToolParameter(name="start_line", type="int", description="First line to read (1-based)", required=False),
        ToolParameter(name="end_line", type="int", description="Last line to read (inclusive)", required=False),
    ],
    use_when="Need to see the current content of a file or a region of a file",
    token_cost_hint="medium",
)

SCHEMA_WRITE_FILE = ToolSchema(
    name="write_file",
    description="Create or replace a file with the given content. Use edit_file instead for modifying existing files.",
    parameters=[
        ToolParameter(name="path", type="str", description="File path relative to project root"),
        ToolParameter(name="content", type="str", description="Full file content to write"),
    ],
    use_when="Creating a new file or completely replacing an existing one",
    token_cost_hint="high",
)

SCHEMA_EDIT_FILE = ToolSchema(
    name="edit_file",
    description="Edit a file by replacing a search string with a replace string. Preferred over write_file for modifications.",
    parameters=[
        ToolParameter(name="path", type="str", description="File path relative to project root"),
        ToolParameter(name="search", type="str", description="Exact text to find (must be unique in the file)"),
        ToolParameter(name="replace", type="str", description="Replacement text"),
        ToolParameter(name="regex", type="bool", description="Whether search is a regex pattern", required=False, default="false"),
    ],
    use_when="Modifying a specific part of an existing file",
    token_cost_hint="low",
)

SCHEMA_LIST_DIRECTORY = ToolSchema(
    name="list_directory",
    description="List files and directories at the given path. Use to understand project structure.",
    parameters=[
        ToolParameter(name="path", type="str", description="Directory path relative to project root", required=False, default="."),
        ToolParameter(name="recursive", type="bool", description="List recursively", required=False, default="false"),
    ],
    use_when="Exploring project structure or finding where files are located",
    token_cost_hint="low",
)

SCHEMA_SEARCH_CODE = ToolSchema(
    name="search_code",
    description="Search for a text pattern across the codebase using ripgrep. Supports regex.",
    parameters=[
        ToolParameter(name="pattern", type="str", description="Search pattern (literal or regex)"),
        ToolParameter(name="path", type="str", description="Directory or file to search in", required=False),
        ToolParameter(name="file_pattern", type="str", description="Glob filter e.g. *.py", required=False),
        ToolParameter(name="regex", type="bool", description="Whether pattern is a regex", required=False, default="false"),
        ToolParameter(name="max_results", type="int", description="Maximum number of results", required=False),
    ],
    use_when="Finding where a string, function name, or pattern appears in the codebase",
    token_cost_hint="medium",
)

SCHEMA_FIND_SYMBOLS = ToolSchema(
    name="find_symbols",
    description="Find symbol definitions (functions, classes, methods) in a file or across the project. Returns signatures.",
    parameters=[
        ToolParameter(name="query", type="str", description="Symbol name or pattern to search for"),
        ToolParameter(name="path", type="str", description="File path to search in (optional)", required=False),
    ],
    use_when="Locating where a class, function, or method is defined",
    token_cost_hint="low",
)

SCHEMA_GET_DIAGNOSTICS = ToolSchema(
    name="get_diagnostics",
    description="Run linter or type-checker on a file and return errors/warnings.",
    parameters=[
        ToolParameter(name="path", type="str", description="File path to check"),
    ],
    use_when="Checking for errors after editing a file",
    token_cost_hint="low",
)

SCHEMA_RUN_COMMAND = ToolSchema(
    name="run_command",
    description="Execute a shell command and return its output. Use for running tests, builds, git, etc.",
    parameters=[
        ToolParameter(name="command", type="str", description="Shell command to run"),
        ToolParameter(name="cwd", type="str", description="Working directory", required=False),
        ToolParameter(name="timeout", type="int", description="Timeout in seconds", required=False, default="30"),
    ],
    use_when="Running tests, builds, linters, git operations, or any shell command",
    token_cost_hint="medium",
)

SCHEMA_WEB_SEARCH = ToolSchema(
    name="web_search",
    description="Search the web for information. Returns titles, URLs, and snippets.",
    parameters=[
        ToolParameter(name="query", type="str", description="Search query"),
        ToolParameter(name="max_results", type="int", description="Maximum results to return", required=False),
    ],
    use_when="Looking up documentation, API references, error solutions, or current information",
    token_cost_hint="high",
)

SCHEMA_WEB_FETCH = ToolSchema(
    name="web_fetch",
    description="Fetch the content of a web page. Returns extracted text.",
    parameters=[
        ToolParameter(name="url", type="str", description="URL to fetch"),
        ToolParameter(name="extract", type="bool", description="Extract main content vs raw HTML", required=False, default="true"),
    ],
    use_when="You have a URL and need to read its content",
    token_cost_hint="high",
)

SCHEMA_GIT_STATUS = ToolSchema(
    name="git_status",
    description="Show git working tree status.",
    parameters=[],
    use_when="Checking what files have been changed or are staged",
    token_cost_hint="low",
)

SCHEMA_GIT_DIFF = ToolSchema(
    name="git_diff",
    description="Show changes between commits, commit and working tree, etc.",
    parameters=[
        ToolParameter(name="staged", type="bool", description="Show staged changes", required=False, default="false"),
        ToolParameter(name="path", type="str", description="Limit to a specific path", required=False),
    ],
    use_when="Reviewing what changes have been made before committing",
    token_cost_hint="medium",
)

SCHEMA_GIT_LOG = ToolSchema(
    name="git_log",
    description="Show commit logs.",
    parameters=[
        ToolParameter(name="n", type="int", description="Number of commits to show", required=False, default="10"),
        ToolParameter(name="path", type="str", description="Limit to a specific path", required=False),
    ],
    use_when="Understanding recent commit history",
    token_cost_hint="low",
)

SCHEMA_GIT_COMMIT = ToolSchema(
    name="git_commit",
    description="Commit staged changes with a message.",
    parameters=[
        ToolParameter(name="message", type="str", description="Commit message"),
    ],
    use_when="Committing changes after verifying they are correct",
    token_cost_hint="low",
)
