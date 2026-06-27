"""
Tool router: decides which tools to expose and applies
pre/post execution rules.

Three routing strategies:
  - "hybrid": LLM chooses from a filtered set + rule-based overrides
  - "llm_only": LLM chooses from all available tools
  - "rules_only": Deterministic filtering only (best for local models)

Rule-based routing enforces invariants that the LLM might violate:
  - Always run get_diagnostics after editing Python/TS/Rust files
  - Clamp read_file ranges to the configured max_read_lines
  - Truncate long command outputs
"""

from __future__ import annotations

import logging

from coding_agent.config import AppConfig
from coding_agent.tools.base import ToolRegistry
from coding_agent.types import AgentState, ToolCall, ToolResult

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Context-dependent tool availability
# ──────────────────────────────────────────────────────────────

# Tools always available
_BASE_TOOLS = [
    "read_file",
    "edit_file",
    "write_file",
    "list_directory",
    "search_code",
    "run_command",
    "get_diagnostics",
]

# Tools for exploration/debugging
_EXPLORATION_TOOLS = [
    "find_symbols",
]

# Tools for web access
_WEB_TOOLS = [
    "web_search",
    "web_fetch",
]

# Tools for git
_GIT_TOOLS = [
    "git_status",
    "git_diff",
    "git_log",
    "git_commit",
]


class ToolRouter:
    """
    Routes tool calls: determines availability, applies pre/post rules.

    The router does NOT execute tools — it just filters and modifies
    calls before/after execution by the ToolRegistry.
    """

    def __init__(self, config: AppConfig, registry: ToolRegistry) -> None:
        self.config = config
        self.registry = registry
        self.strategy = config.tools.router.strategy

    # ── Tool availability ─────────────────────────────────────

    def get_available_tools(self, state: AgentState | None = None) -> list[str]:
        """
        Return the list of tool names available for the current step.

        Availability depends on:
          - Routing strategy (hybrid vs rules_only vs llm_only)
          - Current task phase (exploration vs execution)
          - Whether git tools are needed
        """
        tools = list(_BASE_TOOLS)

        # Exploration tools (always available for hybrid/llm_only;
        # conditional for rules_only)
        if self.strategy == "rules_only":
            # Only add exploration tools if the agent hasn't read
            # many files yet (early exploration phase)
            if state and state.step_count < 5:
                tools.extend(_EXPLORATION_TOOLS)
        else:
            tools.extend(_EXPLORATION_TOOLS)

        # Web tools (always available except for strict rules_only)
        if self.strategy != "rules_only":
            tools.extend(_WEB_TOOLS)
        else:
            # Only add web tools if explicitly needed
            if state and "search" in state.task.lower():
                tools.extend(_WEB_TOOLS)

        # Git tools (add after a few steps or when explicitly needed)
        if state and (
            state.step_count > 3
            or "git" in state.task.lower()
            or "commit" in state.task.lower()
        ):
            tools.extend(_GIT_TOOLS)

        # Filter to only tools that are actually registered
        available = [t for t in tools if t in self.registry.schemas]

        return available

    # ── Pre-execution rules ───────────────────────────────────

    def pre_execute(self, call: ToolCall, state: AgentState | None = None) -> ToolCall:
        """
        Apply pre-execution rules to modify a tool call.

        Rules:
          - read_file: clamp line range to max_read_lines
          - edit_file: no-op if search == replace
          - run_command: set default timeout
        """
        if call.name == "read_file":
            return self._clamp_read_range(call)
        elif call.name == "run_command":
            return self._set_command_defaults(call)
        elif call.name == "search_code":
            return self._clamp_search_results(call)
        return call

    def _clamp_read_range(self, call: ToolCall) -> ToolCall:
        """
        Ensure read_file has a line range and it doesn't exceed
        the configured max_read_lines.
        """
        args = dict(call.arguments)
        max_lines = self.config.tools.fs.max_read_lines

        start = args.get("start_line")
        end = args.get("end_line")

        if start is None and end is None:
            # No range specified — read from line 1 up to max_lines
            args["start_line"] = 1
            args["end_line"] = max_lines
            logger.debug("Clamped read_file to lines 1-%d", max_lines)
        elif start is not None and end is None:
            args["end_line"] = start + max_lines - 1
        elif start is not None and end is not None:
            span = end - start + 1
            if span > max_lines:
                args["end_line"] = start + max_lines - 1
                logger.debug("Clamped read_file range from %d to %d lines", span, max_lines)

        return ToolCall(id=call.id, name=call.name, arguments=args)

    def _set_command_defaults(self, call: ToolCall) -> ToolCall:
        """Set default timeout for run_command if not specified."""
        args = dict(call.arguments)
        if "timeout" not in args:
            args["timeout"] = self.config.agent.step_timeout_seconds
        return ToolCall(id=call.id, name=call.name, arguments=args)

    def _clamp_search_results(self, call: ToolCall) -> ToolCall:
        """Ensure search_code has a reasonable max_results."""
        args = dict(call.arguments)
        max_results = self.config.tools.search.max_results
        if "max_results" not in args:
            args["max_results"] = max_results
        elif args["max_results"] > max_results * 2:
            args["max_results"] = max_results * 2
        return ToolCall(id=call.id, name=call.name, arguments=args)

    # ── Post-execution rules ──────────────────────────────────

    def post_execute(
        self,
        call: ToolCall,
        result: ToolResult,
        state: AgentState | None = None,
    ) -> ToolResult:
        """
        Apply post-execution rules to modify a tool result.

        Rules:
          - Truncate long command outputs
          - Auto-schedule get_diagnostics after edits (logged as a hint)
        """
        if call.name == "run_command":
            return self._truncate_command_output(result)
        elif call.name in ("edit_file", "write_file"):
            self._log_diagnostic_hint(call)

        return result

    def _truncate_command_output(self, result: ToolResult) -> ToolResult:
        """Truncate command output if it's very long."""
        max_chars = 6000
        if len(result.output) <= max_chars:
            return result

        lines = result.output.split("\n")
        if len(lines) > 80:
            head = "\n".join(lines[:30])
            tail = "\n".join(lines[-30:])
            omitted = len(lines) - 60
            output = f"{head}\n... [{omitted} lines omitted] ...\n{tail}"
            return ToolResult(
                tool_call_id=result.tool_call_id,
                tool_name=result.tool_name,
                output=output,
                success=result.success,
                error=result.error,
                token_count=0,
                duration_seconds=result.duration_seconds,
            )

        return result

    def _log_diagnostic_hint(self, call: ToolCall) -> None:
        """Log a hint that diagnostics should be run after an edit."""
        path = call.arguments.get("path", "")
        if path:
            ext = path.rsplit(".", 1)[-1] if "." in path else ""
            if ext in ("py", "ts", "tsx", "rs", "go"):
                logger.info("Post-edit hint: consider running get_diagnostics on %s", path)

    # ── Auto-enqueue rules ────────────────────────────────────

    def should_auto_run_diagnostics(self, call: ToolCall) -> bool:
        """
        Should the agent automatically run get_diagnostics after
        this tool call?

        Used by the agent core to chain diagnostic checks after edits.
        """
        if call.name not in ("edit_file", "write_file"):
            return False

        path = call.arguments.get("path", "")
        ext = path.rsplit(".", 1)[-1] if "." in path else ""
        return ext in ("py", "ts", "tsx", "rs", "go")
