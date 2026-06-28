"""
Local LLM client supporting Ollama and MLX backends.

Ollama (primary):
  - Uses the native /api/chat endpoint (not OpenAI-compatible mode)
  - Converts our Message format to Ollama's format
  - Supports streaming and tool calling (Ollama 0.4+)

MLX (Apple Silicon fallback):
  - Spawns mlx_lm as a subprocess with a local HTTP server
  - Falls back to this if Ollama is unreachable and mlx_fallback=True
  - Uses the same OpenAI-compatible format as RemoteLLMClient
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from collections.abc import AsyncIterator
from typing import Any

import httpx

from coding_agent.config import TurboQuantConfig
from coding_agent.llm.base import (
    LLMClient,
    StreamChunk,
    StreamEvent,
    UsageStats,
    count_tokens,
    message_to_openai_dict,
    openai_sse_chunks,
)
from coding_agent.types import Message, Role, ToolCall, ToolSchema

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Ollama message format conversion
# ──────────────────────────────────────────────────────────────


def _message_to_ollama(msg: Message) -> dict[str, Any]:
    """
    Convert our Message to Ollama's /api/chat format.

    Ollama uses a simpler structure:
      {"role": "...", "content": "...", "images": [...]}
    Tool calls are encoded as a JSON string inside content when needed.
    """
    d: dict[str, Any] = {"role": msg.role.value}

    if msg.role == Role.TOOL:
        # Ollama represents tool results as role="tool" with content
        d["content"] = msg.content
    elif msg.tool_calls:
        # Assistant message with tool calls
        # Ollama 0.4+ supports native tool_calls in the message
        d["content"] = msg.content or ""
        d["tool_calls"] = [
            {
                "function": {
                    "name": tc.name,
                    "arguments": tc.arguments,
                }
            }
            for tc in msg.tool_calls
        ]
    else:
        d["content"] = msg.content or ""

    return d


def _ollama_tool_schemas(tools: list[ToolSchema]) -> list[dict[str, Any]]:
    """Convert our ToolSchema list to Ollama's tools format."""
    result: list[dict[str, Any]] = []
    for t in tools:
        props: dict[str, Any] = {}
        required: list[str] = []
        for p in t.parameters:
            _type_map = {
                "str": "string",
                "int": "integer",
                "float": "number",
                "bool": "boolean",
                "list": "array",
                "dict": "object",
            }
            props[p.name] = {
                "type": _type_map.get(p.type, p.type),
                "description": p.description,
            }
            if p.enum:
                props[p.name]["enum"] = p.enum
            if p.required:
                required.append(p.name)

        result.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            }
        )
    return result


# ──────────────────────────────────────────────────────────────
# LocalLLMClient
# ──────────────────────────────────────────────────────────────


class LocalLLMClient(LLMClient):
    """
    Client for locally-hosted models via Ollama or MLX.

    Resolution order:
      1. Try Ollama at *ollama_base*
      2. If unreachable and *mlx_fallback* is True, start MLX server
    """

    def __init__(
        self,
        model: str = "qwen3-coder:14b",
        ollama_base: str = "http://localhost:11434",
        mlx_model_path: str | None = None,
        mlx_fallback: bool = False,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        timeout_seconds: float = 180.0,
        turboquant: TurboQuantConfig | None = None,
    ) -> None:
        super().__init__(model, temperature, max_tokens)
        self.ollama_base = ollama_base.rstrip("/")
        self.mlx_model_path = mlx_model_path
        self.mlx_fallback = mlx_fallback
        self._turboquant = turboquant
        self._backend: str = "ollama"  # "ollama" | "mlx"
        self._mlx_port: int = 0
        self._mlx_proc: subprocess.Popen[bytes] | None = None

        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
        )

    # ── Backend selection ─────────────────────────────────────

    async def _ensure_backend(self) -> None:
        """
        Make sure a backend is reachable.

        Attempts Ollama first; if that fails and MLX fallback is
        enabled, tries to start an MLX server.
        """
        if self._backend == "ollama":
            if await self._ollama_is_alive():
                return
            logger.warning("Ollama not reachable at %s", self.ollama_base)
            if self.mlx_fallback and self.mlx_model_path:
                logger.info("Attempting MLX fallback with model %s", self.mlx_model_path)
                await self._start_mlx()
                self._backend = "mlx"
            else:
                raise RuntimeError(
                    f"Ollama not reachable at {self.ollama_base} and MLX fallback disabled. "
                    "Start Ollama or enable MLX fallback."
                )
        elif self._backend == "mlx":
            # Already using MLX — nothing to do
            pass

    async def _ollama_is_alive(self) -> bool:
        """Check if the Ollama server is responding."""
        try:
            resp = await self._http.get(f"{self.ollama_base}/api/tags", timeout=5.0)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.ReadTimeout):
            return False

    async def _start_mlx(self) -> None:
        """
        Start an MLX server as a subprocess.

        Uses ``mlx_lm.server`` which exposes an OpenAI-compatible API.
        """
        if not shutil.which("python3"):
            raise RuntimeError("python3 not found — cannot start MLX server")

        # Find a free port
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        self._mlx_port = sock.getsockname()[1]
        sock.close()

        cmd = [
            "python3",
            "-m",
            "mlx_lm.server",
            "--model",
            self.mlx_model_path or "",
            "--port",
            str(self._mlx_port),
            "--host",
            "127.0.0.1",
        ]

        # Append TurboQuant flags if configured
        tq = getattr(self, "_turboquant", None)
        if tq and tq.enabled:
            cmd.extend(
                [
                    "--kv-bits",
                    str(tq.kv_bits),
                    "--weight-bits",
                    str(tq.weight_bits),
                    "--sink-tokens",
                    str(tq.sink_tokens),
                ]
            )
            if tq.layer_adaptive:
                cmd.append("--layer-adaptive")
        logger.info("Starting MLX server: %s", " ".join(str(c) for c in cmd))
        self._mlx_proc = subprocess.Popen(
            [str(c) for c in cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for the server to be ready (up to 60 seconds)
        mlx_url = f"http://127.0.0.1:{self._mlx_port}"
        for _ in range(30):
            await asyncio.sleep(2)
            try:
                resp = await self._http.get(f"{mlx_url}/v1/models", timeout=3.0)
                if resp.status_code == 200:
                    logger.info("MLX server ready at %s", mlx_url)
                    return
            except (httpx.ConnectError, httpx.ReadTimeout):
                continue

        raise RuntimeError("MLX server failed to start within 60 seconds")

    # ── Chat (non-streaming) ──────────────────────────────────

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Message:
        await self._ensure_backend()
        temp, max_tok = self._resolve_params(temperature, max_tokens)

        if self._backend == "ollama":
            return await self._ollama_chat(messages, tools, temp, max_tok)
        else:
            return await self._mlx_chat(messages, tools, temp, max_tok)

    # ── Chat (streaming) ──────────────────────────────────────

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        await self._ensure_backend()
        temp, max_tok = self._resolve_params(temperature, max_tokens)

        if self._backend == "ollama":
            async for chunk in self._ollama_stream(messages, tools, temp, max_tok):
                yield chunk
        else:
            async for chunk in self._mlx_stream(messages, tools, temp, max_tok):
                yield chunk

    # ── Ollama implementation ─────────────────────────────────

    async def _ollama_chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        temperature: float,
        max_tokens: int,
    ) -> Message:
        """Non-streaming Ollama /api/chat call."""
        payload = self._ollama_payload(messages, tools, temperature, max_tokens, stream=False)
        resp = await self._http.post(f"{self.ollama_base}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

        content = data.get("message", {}).get("content", "")
        tool_calls_raw = data.get("message", {}).get("tool_calls", [])
        tool_calls = self._parse_ollama_tool_calls(tool_calls_raw) if tool_calls_raw else None

        usage = UsageStats(
            prompt_tokens=count_tokens(str(payload)),
            completion_tokens=count_tokens(content),
        )
        logger.debug("Ollama chat usage: %s", usage)

        return Message(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=tool_calls,
        )

    async def _ollama_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming Ollama /api/chat call."""
        payload = self._ollama_payload(messages, tools, temperature, max_tokens, stream=True)

        tool_call_accum: dict[int, dict[str, Any]] = {}

        async with self._http.stream("POST", f"{self.ollama_base}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = chunk.get("message", {})

                # Text content
                if msg.get("content"):
                    yield StreamChunk(event=StreamEvent.TEXT, content=msg["content"])

                # Tool call deltas
                for i, tc in enumerate(msg.get("tool_calls", [])):
                    fn = tc.get("function", {})
                    if i not in tool_call_accum:
                        tool_call_accum[i] = {"name": fn.get("name", ""), "arguments": ""}
                        yield StreamChunk(
                            event=StreamEvent.TOOL_CALL_START,
                            tool_call_id=f"tc_{i}",
                            tool_name=fn.get("name", ""),
                        )
                    if fn.get("arguments"):
                        # Ollama sends full dict, not string deltas
                        args_str = (
                            json.dumps(fn["arguments"])
                            if isinstance(fn["arguments"], dict)
                            else str(fn["arguments"])
                        )
                        tool_call_accum[i]["arguments"] = args_str
                        yield StreamChunk(
                            event=StreamEvent.TOOL_CALL_DELTA,
                            tool_call_id=f"tc_{i}",
                            tool_arguments_delta=args_str,
                        )

                if chunk.get("done"):
                    # Yield end events for any tool calls
                    for idx, td in tool_call_accum.items():
                        yield StreamChunk(
                            event=StreamEvent.TOOL_CALL_END,
                            tool_call_id=f"tc_{idx}",
                            tool_name=td["name"],
                        )
                    yield StreamChunk(event=StreamEvent.DONE)
                    return

    def _ollama_payload(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        """Build the JSON payload for Ollama /api/chat."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_to_ollama(m) for m in messages],
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if tools:
            payload["tools"] = _ollama_tool_schemas(tools)
        return payload

    @staticmethod
    def _parse_ollama_tool_calls(raw: list[dict[str, Any]]) -> list[ToolCall]:
        """Parse tool_calls from an Ollama response."""
        calls: list[ToolCall] = []
        for i, tc in enumerate(raw):
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append(ToolCall(id=f"tc_{i}", name=fn.get("name", ""), arguments=args))
        return calls

    # ── MLX implementation (delegates to OpenAI-compatible server) ──

    async def _mlx_chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        temperature: float,
        max_tokens: int,
    ) -> Message:
        """Chat via the MLX OpenAI-compatible server."""
        url = f"http://127.0.0.1:{self._mlx_port}/v1/chat/completions"
        payload = self._mlx_payload(messages, tools, temperature, max_tokens, stream=False)

        resp = await self._http.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]["message"]
        tool_calls = self._parse_mlx_tool_calls(choice.get("tool_calls", []))

        return Message(
            role=Role.ASSISTANT,
            content=choice.get("content", "") or "",
            tool_calls=tool_calls or None,
        )

    async def _mlx_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming chat via the MLX OpenAI-compatible server."""
        url = f"http://127.0.0.1:{self._mlx_port}/v1/chat/completions"
        payload = self._mlx_payload(messages, tools, temperature, max_tokens, stream=True)

        tool_call_accum: dict[str, dict[str, Any]] = {}

        async for chunk in openai_sse_chunks(self._http, url, payload):
            delta = chunk.get("choices", [{}])[0].get("delta", {})

            if delta.get("content"):
                yield StreamChunk(event=StreamEvent.TEXT, content=delta["content"])

            for tc_delta in delta.get("tool_calls", []):
                call_id = tc_delta.get("id", f"tc_{tc_delta.get('index', 0)}")
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

        for call_id, td in tool_call_accum.items():
            yield StreamChunk(
                event=StreamEvent.TOOL_CALL_END,
                tool_call_id=call_id,
                tool_name=td.get("name", ""),
            )
        yield StreamChunk(event=StreamEvent.DONE)

    def _mlx_payload(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        """Build the JSON payload for the MLX OpenAI-compatible server."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message_to_openai_dict(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if tools:
            payload["tools"] = [t.to_openai_dict() for t in tools]
        return payload

    @staticmethod
    def _parse_mlx_tool_calls(raw: list[dict[str, Any]]) -> list[ToolCall] | None:
        """Parse tool_calls from an MLX server response (OpenAI format)."""
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
        if self._mlx_proc is not None:
            logger.info("Shutting down MLX server (PID %d)", self._mlx_proc.pid)
            self._mlx_proc.terminate()
            try:
                self._mlx_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._mlx_proc.kill()

    async def __aenter__(self) -> LocalLLMClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
