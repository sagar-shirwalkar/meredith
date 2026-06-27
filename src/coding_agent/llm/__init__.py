"""
LLM client abstractions and implementations.

Provides a unified interface (LLMProtocol) with backends for:
  - Remote OpenAI-compatible APIs (Claude, GPT-4, Together, etc.)
  - Local Ollama instances
  - Local MLX models (Apple Silicon subprocess)
"""

from coding_agent.llm.base import (
    LLMClient,
    StreamChunk,
    StreamEvent,
    UsageStats,
)
from coding_agent.llm.remote import RemoteLLMClient
from coding_agent.llm.local import LocalLLMClient

__all__ = [
    "LLMClient",
    "LocalLLMClient",
    "RemoteLLMClient",
    "StreamChunk",
    "StreamEvent",
    "UsageStats",
]
