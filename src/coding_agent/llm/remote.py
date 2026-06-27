"""
Remote LLM client for OpenAI-compatible APIs.

Works with:
  - OpenAI (GPT-4o, o3, etc.)
  - Anthropic via OpenAI-compatible gateway
  - Together AI, Fireworks, any /v1/chat/completions endpoint

Uses httpx with async + streaming.  Retries on transient failures
(429, 500, 502, 503) with exponential backoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncIterator

import httpx

from coding_agent.llm.base import (
    LLMClient,
    StreamChunk,
    StreamEvent,
    UsageStats,
    count_tokens,
    parse_tool_calls_from_response,
)
from coding_agent.types import Message, Role, ToolCall, ToolSchema

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Defaults & constants
# ──────────────────────────────────────────────────────────────

_MAX_RETRIES = 3
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_BACKOFF_BASE = 1.5  # seconds


class RemoteLLMClient(LLMClient):
    """
    Async client for any OpenAI-compatible chat/completions endpoint.

    The API key is read from the environment variable named in
    *api_key_env* (default ``OPENAI_API_KEY``).
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_base: str = "https://api.openai.com/v1",
        api_key_env: str = "OPENAI_API_KEY",
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout_seconds: float = 120.0,
    ) -> None:
        super().__init__(model, temperature, max_tokens)
        self.api_base = api_base.rstrip("/")
        self.api_key = os.environ.get(api_key_env, "")
        if not self.api_key:
            logger.warning("API key env var %s is not set — requests will fail", api_key_env)
        self._http = httpx.AsyncClient(
            base_url=self.api_base,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
        )

    # ── Core: non-streaming ───────────────────────────────────

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Message:
        """
        Full chat completion (no streaming).

        Retries on transient server errors with exponential backoff.
        """
        temp, max_tok = self._resolve_params(temperature, max_tokens)
        payload = self._build_payload(messages, tools, temp, max_tok, stream=False)

        resp_data = await self._request_with_retries("/chat/completions", payload)

        choice = resp_data["choices"][0]
        msg = choice["message"]

        tool_calls = self._parse_tool_calls_response(msg.get("tool_calls", []))

        usage_raw = resp_data.get("usage", {})
        usage = UsageStats(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )

        return Message(
            role=Role.ASSISTANT,
            content=msg.get("content", "") or "",
            tool_calls=tool_calls or None,
        )

    # ── Core: streaming ───────────────────────────────────────

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """
        Streaming chat completion.  Yields StreamChunk objects.

        The caller accumulates TEXT for content and TOOL_CALL_*
        events for function calls.  A final DONE chunk signals
        the end of the response.
        """
        temp, max_tok = self._resolve_params(temperature, max_tokens)
        payload = self._build_payload(messages, tools, temp, max_tok, stream=True)

        # Accumulate tool call deltas
        tool_call_accum: dict[str, dict[str, Any]] = {}

        async for line in self._stream_lines("/chat/completions", payload):
            if not line.startswith("data: "):
                continue
            data_str = line[6:].strip()
            if data_str == "[DONE]":
                # Yield any completed tool calls
                if tool_call_accum:
                    for call_id, td in tool_call_accum.items():
                        yield StreamChunk(
                            event=StreamEvent.TOOL_CALL_END,
                            tool_call_id=call_id,
                            tool_name=td.get("name", ""),
                        )
                yield StreamChunk(event=StreamEvent.DONE)
                return

            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            delta = chunk.get("choices", [{}])[0].get("delta", {})

            # Text content
            if delta.get("content"):
                yield StreamChunk(event=StreamEvent.TEXT, content=delta["content"])

            # Tool call deltas
            for tc_delta in delta.get("tool_calls", []):
                idx = tc_delta.get("index", 0)
                call_id = tc_delta.get("id", f"tc_{idx}")
                if call_id not in tool_call_accum:
                    tool_call_accum[call_id] = {"name": "", "arguments": ""}
                    yield StreamChunk(
                        event=StreamEvent.TOOL_CALL_START,
                        tool_call_id=call_id,
                        tool_name=tc_delta.get("function", {}).get("name", ""),
                    )
                fn_delta = tc_delta.get("function", {})
                if fn_delta.get("name"):
                    tool_call_accum[call_id]["name"] = fn_delta["name"]
                if fn_delta.get("arguments"):
                    tool_call_accum[call_id]["arguments"] += fn_delta["arguments"]
                    yield StreamChunk(
                        event=StreamEvent.TOOL_CALL_DELTA,
                        tool_call_id=call_id,
                        tool_arguments_delta=fn_delta["arguments"],
                    )

            # Usage (only in last chunk for some providers)
            usage_raw = chunk.get("usage")
            if usage_raw:
                yield StreamChunk(
                    event=StreamEvent.USAGE,
                    usage=UsageStats(
                        prompt_tokens=usage_raw.get("prompt_tokens", 0),
                        completion_tokens=usage_raw.get("completion_tokens", 0),
                        total_tokens=usage_raw.get("total_tokens", 0),
                    ),
                )

    # ── HTTP helpers ──────────────────────────────────────────

    async def _request_with_retries(self, path: str, payload: dict) -> dict:
        """POST with exponential backoff on retryable status codes."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await self._http.post(path, json=payload)
                if resp.status_code in _RETRYABLE_STATUS:
                    wait = _BACKOFF_BASE ** attempt
                    logger.warning(
                        "LLM API %d, retry %d/%d in %.1fs",
                        resp.status_code, attempt + 1, _MAX_RETRIES, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in _RETRYABLE_STATUS:
                    raise
                last_exc = exc
                wait = _BACKOFF_BASE ** attempt
                logger.warning("LLM API error %d, retry %d/%d in %.1fs",
                               exc.response.status_code, attempt + 1, _MAX_RETRIES, wait)
                await asyncio.sleep(wait)
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_exc = exc
                wait = _BACKOFF_BASE ** attempt
                logger.warning("LLM connection error, retry %d/%d in %.1fs: %s",
                               attempt + 1, _MAX_RETRIES, wait, exc)
                await asyncio.sleep(wait)

        raise RuntimeError(f"LLM API failed after {_MAX_RETRIES} retries") from last_exc

    async def _stream_lines(self, path: str, payload: dict) -> AsyncIterator[str]:
        """POST with streaming and yield raw SSE lines."""
        async with self._http.stream("POST", path, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                yield line

    # ── Payload construction ──────────────────────────────────

    def _build_payload(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        """Build the JSON payload for /chat/completions."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_to_dict(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if tools:
            payload["tools"] = [t.to_openai_dict() for t in tools]
        return payload

    @staticmethod
    def _message_to_dict(msg: Message) -> dict[str, Any]:
        """Convert a Message to the OpenAI wire format."""
        d: dict[str, Any] = {"role": msg.role.value, "content": msg.content or ""}
        if msg.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]
        if msg.tool_call_id:
            d["tool_call_id"] = msg.tool_call_id
        if msg.name:
            d["name"] = msg.name
        return d

    @staticmethod
    def _parse_tool_calls_response(raw: list[dict]) -> list[ToolCall] | None:
        """Parse tool_calls from a non-streaming response."""
        if not raw:
            return None
        calls: list[ToolCall] = []
        for tc in raw:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))
        return calls

    # ── Lifecycle ─────────────────────────────────────────────

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> RemoteLLMClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
