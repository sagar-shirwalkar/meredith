"""
meredith: A modern AI coding agent with RAG, ACP integration,
and smart context management.

Supports any OpenAI-compatible remote API (Claude, GPT, Opencode, etc.)
and local models via Ollama (Linux, macOS, Windows) or MLX (Apple Silicon).
"""

__version__ = "0.2.3"

from coding_agent.types import (
    AgentState,
    LoopDetection,
    LoopType,
    Message,
    Plan,
    RecoveryAction,
    Role,
    Step,
    SubTask,
    ToolCall,
    ToolResult,
)

__all__ = [
    "__version__",
    "AgentState",
    "LoopDetection",
    "LoopType",
    "Message",
    "Plan",
    "RecoveryAction",
    "Role",
    "Step",
    "SubTask",
    "ToolCall",
    "ToolResult",
]
