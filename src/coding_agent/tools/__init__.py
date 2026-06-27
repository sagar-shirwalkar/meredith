"""
Tools subsystem: definition, routing, and execution.

Provides the ToolRegistry (schema + executor) and ToolRouter
(LLM-driven + rule-based selection), along with built-in tool
implementations for filesystem, search, web, and git operations.
"""

from coding_agent.tools.base import ToolExecutor, ToolRegistry, ToolSchema
from coding_agent.tools.router import ToolRouter

__all__ = [
    "ToolExecutor",
    "ToolRegistry",
    "ToolRouter",
    "ToolSchema",
]
