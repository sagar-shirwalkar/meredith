"""
Core types and data structures shared across the entire agent.

All dataclasses use slots=True for memory efficiency.
Python 3.12+ type syntax throughout (X | Y, type statements).
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

# ──────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────


class Role(enum.StrEnum):
    """Message role in the conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class TaskStatus(enum.StrEnum):
    """Status of a subtask or overall plan."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class LoopType(enum.StrEnum):
    """Category of loop detected by the recovery system."""

    EXACT_REPETITION = "exact_repetition"
    SEMANTIC_LOOP = "semantic_loop"
    ERROR_LOOP = "error_loop"
    STALL = "stall"


class Severity(enum.StrEnum):
    """How severe a detected loop is."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SymbolKind(enum.StrEnum):
    """Kind of code symbol extracted by the RAG indexer."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    VARIABLE = "variable"
    IMPORT = "import"
    CONSTANT = "constant"
    MODULE = "module"


class ZoneName(enum.StrEnum):
    """Named zones in the hierarchical context window."""

    IMMUTABLE = "immutable"
    TASK = "task"
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    SCRATCH = "scratch"


# ──────────────────────────────────────────────────────────────
# Messages & Conversation
# ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Message:
    """A single message in the conversation history."""

    role: Role
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None  # Tool name when role == TOOL
    timestamp: float = field(default_factory=time.time)

    def token_estimate(self) -> int:
        """Rough token estimate: ~4 chars per token for code, ~5 for prose."""
        chars = len(self.content)
        if chars == 0:
            return 0
        divisor = 4 if any(c in self.content for c in "{}()[];=") else 5
        return max(1, chars // divisor)


# ──────────────────────────────────────────────────────────────
# Tool Types
# ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class ToolParameter:
    """JSON-schema-style description of a single tool parameter."""

    name: str
    type: str  # "str", "int", "bool", "list[str]", etc.
    description: str
    required: bool = True
    default: Any | None = None
    enum: list[str] | None = None


@dataclass(slots=True)
class ToolSchema:
    """Full schema describing a tool the agent can invoke."""

    name: str
    description: str
    parameters: list[ToolParameter]
    # Hints for the router — which situations favour this tool
    use_when: str = ""
    token_cost_hint: str = "medium"  # "minimal" | "low" | "medium" | "high"

    def to_openai_dict(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling format."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in self.parameters:
            prop: dict[str, Any] = {
                "type": _python_type_to_json(p.type), "description": p.description
            }
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


@dataclass(slots=True)
class ToolCall:
    """A single tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ToolResult:
    """Result returned by a tool after execution."""

    tool_call_id: str
    tool_name: str
    output: str
    success: bool = True
    error: str | None = None
    token_count: int = 0
    duration_seconds: float = 0.0


# ──────────────────────────────────────────────────────────────
# Planning
# ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class SubTask:
    """A single decomposed sub-task within a plan."""

    id: int
    description: str
    files: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result_summary: str = ""


@dataclass(slots=True)
class Plan:
    """Strategic plan produced by the planner."""

    goal: str
    subtasks: list[SubTask] = field(default_factory=list)
    dependencies: dict[int, list[int]] = field(default_factory=dict)
    # Which subtask is currently active (-1 = not started)
    current_subtask_idx: int = -1

    @property
    def current_subtask(self) -> SubTask | None:
        if 0 <= self.current_subtask_idx < len(self.subtasks):
            return self.subtasks[self.current_subtask_idx]
        return None

    def advance(self) -> SubTask | None:
        """Move to the next pending subtask. Returns it or None if done."""
        for i, st in enumerate(self.subtasks):
            if st.status == TaskStatus.PENDING:
                # Check dependencies
                deps = self.dependencies.get(st.id, [])
                if all(
                    self.subtasks[d - 1].status == TaskStatus.COMPLETED
                    for d in deps if d - 1 < len(self.subtasks)
                ):
                    st.status = TaskStatus.IN_PROGRESS
                    self.current_subtask_idx = i
                    return st
        return None


# ──────────────────────────────────────────────────────────────
# Agent State & Steps
# ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Step:
    """Record of a single ReAct step (think → act → observe)."""

    step_number: int
    thinking: str  # Agent's chain-of-thought
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    timestamp: float = field(default_factory=time.time)

    def summary(self, max_length: int = 120) -> str:
        """One-line summary for episodic memory."""
        action = f"{self.tool_call.name}({self._arg_summary()})" if self.tool_call else "reasoning"
        result = "ok" if self.tool_result and self.tool_result.success else "error"
        text = f"Step {self.step_number}: {action} → {result}"
        return text[:max_length]

    def _arg_summary(self) -> str:
        if not self.tool_call:
            return ""
        args = self.tool_call.arguments
        # Show at most 2 key args
        items = list(args.items())[:2]
        parts = [f"{k}={v!r}" if len(repr(v)) < 30 else f"{k}=…" for k, v in items]
        return ", ".join(parts)


@dataclass(slots=True)
class AgentState:
    """Mutable state carried through the agent's lifecycle."""

    task: str
    plan: Plan | None = None
    steps: list[Step] = field(default_factory=list)
    files_modified: set[str] = field(default_factory=set)
    files_read: set[str] = field(default_factory=set)
    diagnostics_count: int = 0
    test_status: str = "unknown"
    last_error: str | None = None
    total_tokens_used: int = 0
    started_at: float = field(default_factory=time.time)

    @property
    def step_count(self) -> int:
        return len(self.steps)

    def record_step(self, step: Step) -> None:
        self.steps.append(step)
        if step.tool_result:
            if not step.tool_result.success:
                self.last_error = step.tool_result.error or step.tool_result.output[:200]
            self.total_tokens_used += step.tool_result.token_count


# ──────────────────────────────────────────────────────────────
# Recovery
# ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class LoopDetection:
    """Information about a detected loop."""

    loop_type: LoopType
    severity: Severity
    repeated_actions: list[Step] = field(default_factory=list)
    recurring_error: str | None = None
    message: str = ""


@dataclass(slots=True)
class RecoveryAction:
    """Action to take when a loop is detected."""

    inject_message: str | None = None
    force_think: bool = False
    suggest_tools: list[str] = field(default_factory=list)
    force_user_intervention: bool = False
    reset_working_memory: bool = False
    max_retries: int = -1  # -1 = unlimited


# ──────────────────────────────────────────────────────────────
# RAG
# ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Symbol:
    """A code symbol extracted from a source file."""

    name: str
    kind: SymbolKind
    file_path: str
    line_start: int
    line_end: int
    signature: str  # One-liner: "def authenticate(user: str, pw: str) -> Token"
    docstring: str = ""
    body: str = ""  # Full implementation (loaded lazily)


@dataclass(slots=True)
class CodeChunk:
    """A chunk of code produced by the chunker."""

    file_path: str
    line_start: int
    line_end: int
    content: str
    symbol_name: str | None = None
    symbol_kind: SymbolKind | None = None
    # Precomputed for BM25 scoring
    token_frequencies: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class SearchResult:
    """A retrieval result from the RAG system."""

    content: str
    file_path: str
    line_start: int
    line_end: int
    score: float
    symbol_name: str | None = None
    source: str = "bm25"  # "bm25" | "dense" | "symbol"


# ──────────────────────────────────────────────────────────────
# Context
# ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class ContextItem:
    """An item stored in a context zone."""

    content: str
    source: str  # e.g. "tool_result", "summary", "memory", "system"
    token_count: int = 0
    timestamp: float = field(default_factory=time.time)
    compressible: bool = True  # Can this be truncated/summarised?


# ──────────────────────────────────────────────────────────────
# Protocols (structural subtyping for dependency injection)
# ──────────────────────────────────────────────────────────────


class LLMProtocol(Protocol):
    """Minimal interface any LLM client must implement."""

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Message: ...

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any: pass

    def count_tokens(self, text: str) -> int: pass


class ToolExecutorProtocol(Protocol):
    """Interface for executing a tool call."""

    async def execute(self, call: ToolCall) -> ToolResult: pass


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


_PY_TO_JSON_TYPE: dict[str, str] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "list[str]": "array",
    "dict": "object",
}


def _python_type_to_json(py_type: str) -> str:
    """Map a Python type hint string to a JSON Schema type."""
    return _PY_TO_JSON_TYPE.get(py_type, "string")
