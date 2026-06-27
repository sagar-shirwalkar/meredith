"""
Context management subsystem.

Controls what goes into the LLM's context window and when,
using a hierarchical zone model and token budgets to avoid
overflow and minimise waste.
"""

from coding_agent.context.budget import TokenBudget
from coding_agent.context.compressor import OutputCompressor
from coding_agent.context.manager import ContextManager

__all__ = [
    "ContextManager",
    "OutputCompressor",
    "TokenBudget",
]
