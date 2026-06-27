"""
coding-agent: A cutting-edge AI coding agent with RAG, MCP integration,
and smart context management.

Supports both large remote models (Claude, GPT-4) and local models
(Ollama/MLX on Apple Silicon and Linux+CUDA).
"""

__version__ = "0.1.0"

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
