"""
Base LLM abstractions: streaming types, usage stats, and the
abstract LLMClient that both Remote and Local backends implement.

Token counting uses tiktoken (cl100k_base) as a universal approximation.
Local Ollama models don't share OpenAI's tokenizer, but the approximation
is good enough for budget tracking — we never rely on exact counts.
"""

from __future__ import annotations

import abc
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import tiktoken

from coding_agent.types import Message, ToolCall, ToolSchema

# ──────────────────────────────────────────────────────────────
# Streaming types
# ──────────────────────────────────────────────────────────────


class StreamEvent(StrEnum):
    """Kind of event yielded during streaming generation."""

    TEXT = "text"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_END = "tool_call_end"
    USAGE = "usage"
    DONE = "done"


@dataclass(slots=True)
class StreamChunk:
    """A single chunk from a streaming LLM response."""

    event: StreamEvent
    content: str = ""
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments_delta: str = ""
    usage: UsageStats | None = None


@dataclass(slots=True)
class UsageStats:
    """Token usage statistics from an LLM response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: UsageStats) -> UsageStats:
        return UsageStats(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


# ──────────────────────────────────────────────────────────────
# Token counting
# ──────────────────────────────────────────────────────────────

_encoding = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens using cl100k_base. Approximation for non-OpenAI models."""
    return len(_encoding.encode(text))


def count_messages_tokens(messages: list[Message]) -> int:
    """Estimate total tokens across a list of messages, including overhead."""
    total = 0
    for msg in messages:
        # OpenAI-style overhead: ~4 tokens per message for role/separators
        total += 4
        total += count_tokens(msg.content)
        if msg.tool_calls:
            for tc in msg.tool_calls:
                total += count_tokens(tc.name)
                total += count_tokens(json.dumps(tc.arguments))
    return total


# ──────────────────────────────────────────────────────────────
# Tool-call response parser
# ──────────────────────────────────────────────────────────────


def parse_tool_calls_from_response(
    tool_call_deltas: dict[str, dict[str, Any]],
) -> list[ToolCall]:
    """
    Convert accumulated streaming tool-call deltas into ToolCall objects.

    *tool_call_deltas* maps call_id → {"name": str, "arguments": str}.
    """
    calls: list[ToolCall] = []
    for call_id, data in tool_call_deltas.items():
        raw_args = data.get("arguments", "{}")
        try:
            arguments = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError:
            # Partial JSON from streaming — best effort
            arguments = {"_raw": raw_args}
        calls.append(
            ToolCall(id=call_id, name=data.get("name", ""), arguments=arguments)
        )
    return calls


# ──────────────────────────────────────────────────────────────
# Abstract LLM client
# ──────────────────────────────────────────────────────────────


class LLMClient(abc.ABC):
    """
    Abstract base for all LLM backends.

    Subclasses must implement chat() and chat_stream().
    Token counting is inherited from this base class.
    """

    def __init__(self, model: str, temperature: float, max_tokens: int) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    # ── Synchronous (collects full response) ──────────────────

    @abc.abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Message:
        """
        Send messages and return the full assistant response.

        If tools are provided, the response may contain tool_calls.
        """
        ...

    # ── Streaming ─────────────────────────────────────────────

    @abc.abstractmethod
    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """
        Send messages and yield streaming chunks.

        The caller should accumulate TEXT chunks for content and
        TOOL_CALL_* chunks for function calls, then assemble the
        final Message once a DONE event is received.
        """
        ...

    # ── Convenience: count tokens ─────────────────────────────

    def count_tokens(self, text: str) -> int:
        return count_tokens(text)

    def count_messages_tokens(self, messages: list[Message]) -> int:
        return count_messages_tokens(messages)

    # ── Helpers for subclasses ────────────────────────────────

    @staticmethod
    def _new_call_id() -> str:
        """Generate a unique tool call ID."""
        return f"call_{uuid.uuid4().hex[:12]}"

    def _resolve_params(
        self,
        temperature: float | None,
        max_tokens: int | None,
    ) -> tuple[float, int]:
        """Apply per-call overrides or fall back to instance defaults."""
        return (
            temperature if temperature is not None else self.temperature,
            max_tokens if max_tokens is not None else self.max_tokens,
        )
