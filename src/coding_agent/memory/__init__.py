"""
Cross-session memory subsystem.

Persists learnings across agent sessions using SQLite:
  - Project conventions (detected from code and AGENTS.md)
  - Error patterns and their solutions
  - Tool usage patterns (what works for which task types)
  - Project structure notes
"""

from coding_agent.memory.store import MemoryStore

__all__ = [
    "MemoryStore",
]
