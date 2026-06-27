"""
Cross-session memory store backed by SQLite.

Persists learnings across agent sessions:
  - Project conventions (detected from code / AGENTS.md)
  - Error patterns and their solutions
  - Tool usage patterns (what works for which task types)
  - Project structure notes

The store is queried at the start of each session and updated
at the end with new learnings.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from pathlib import Path

from coding_agent.config import AppConfig
from coding_agent.llm.base import count_tokens
from coding_agent.types import AgentState

logger = logging.getLogger(__name__)


class MemoryStore:
    """
    SQLite-backed cross-session memory.

    Stores typed entries with tags for retrieval.  Each entry has:
      - type: "convention" | "error_pattern" | "tool_pattern" | "structure"
      - content: The actual learning (short text)
      - tags: Comma-separated keywords for relevance matching
      - confidence: "high" | "medium" | "low"
      - created_at: Timestamp
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.workdir = Path(config.agent.working_directory).resolve()
        self.db_path = self.workdir / config.memory.store_path
        self._conn: sqlite3.Connection | None = None

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise the database and create tables."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _create_tables(self) -> None:
        """Create the memory tables."""
        assert self._conn is not None

        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                confidence TEXT NOT NULL DEFAULT 'medium',
                created_at REAL NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed_at REAL
            );

            CREATE INDEX IF NOT EXISTS idx_memories_type
                ON memories(type);

            CREATE INDEX IF NOT EXISTS idx_memories_tags
                ON memories(tags);
        """)
        self._conn.commit()

    # ── Storing memories ──────────────────────────────────────

    def store(
        self,
        type: str,
        content: str,
        tags: str = "",
        confidence: str = "medium",
    ) -> None:
        """
        Store a new memory entry.

        Args:
            type: Category ("convention", "error_pattern", "tool_pattern", "structure")
            content: The learning text.
            tags: Comma-separated keywords for relevance matching.
            confidence: "high", "medium", or "low".
        """
        assert self._conn is not None

        # Truncate content if it exceeds the configured limit
        max_tokens = self.config.memory.max_entry_tokens
        if count_tokens(content) > max_tokens:
            # Rough truncation: ~4 chars per token
            content = content[: max_tokens * 4 - 50] + "..."

        now = time.time()
        self._conn.execute(
            """INSERT INTO memories (type, content, tags, confidence, created_at, access_count)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (type, content, tags, confidence, now),
        )
        self._conn.commit()

    # ── Recalling memories ────────────────────────────────────

    def recall_relevant(self, query: str, limit: int = 10) -> str:
        """
        Recall memories relevant to a query.

        Uses tag matching and simple keyword overlap to rank
        relevance.  Returns a formatted string suitable for
        injection into the system prompt.
        """
        assert self._conn is not None

        # Get all memories (there shouldn't be too many)
        rows = self._conn.execute(
            "SELECT id, type, content, tags, confidence, access_count FROM memories "
            "ORDER BY created_at DESC"
        ).fetchall()

        if not rows:
            return ""

        # Score each memory by relevance to the query
        query_words = set(re.findall(r"\w+", query.lower()))
        scored: list[tuple[float, tuple]] = []

        for row in rows:
            mem_id, mem_type, content, tags, confidence, access_count = row
            tag_words = set(re.findall(r"\w+", tags.lower()))
            content_words = set(re.findall(r"\w+", content.lower()))

            # Relevance score: overlap between query and (tags + content)
            overlap = len(query_words & (tag_words | content_words))
            if overlap == 0 and len(query_words) > 2:
                continue  # Skip completely irrelevant memories

            score = overlap

            # Boost frequently accessed memories
            score += min(access_count * 0.1, 2.0)

            # Boost high-confidence memories
            conf_boost = {"high": 1.0, "medium": 0.5, "low": 0.2}
            score += conf_boost.get(confidence, 0.5)

            scored.append((score, row))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Format the top results
        results: list[str] = []
        total_tokens = 0
        max_total_tokens = 800

        for _score, row in scored[:limit]:
            mem_id, mem_type, content, tags, confidence, _ = row
            entry = f"[{mem_type}] {content}"
            entry_tokens = count_tokens(entry)

            if total_tokens + entry_tokens > max_total_tokens:
                break

            results.append(entry)
            total_tokens += entry_tokens

            # Update access count
            self._conn.execute(
                "UPDATE memories SET access_count = access_count + 1, "
                "last_accessed_at = ? WHERE id = ?",
                (time.time(), mem_id),
            )

        self._conn.commit()

        if not results:
            return ""

        return "Relevant project knowledge:\n" + "\n".join(results)

    # ── Session-level operations ──────────────────────────────

    async def save_session(self, state: AgentState) -> None:
        """
        Extract and store learnings from a completed session.

        Called when the agent finishes a task.  Analyses the
        session state for patterns worth remembering.
        """
        # Learning 1: Project structure
        if state.files_modified or state.files_read:
            file_list = sorted(state.files_modified | state.files_read)
            self.store(
                type="structure",
                content=f"Files involved in '{state.task[:50]}': {', '.join(file_list[:10])}",
                tags=",".join(Path(f).stem for f in file_list[:5]),
                confidence="medium",
            )

        # Learning 2: Error patterns (if there were failures that were eventually resolved)
        if state.last_error and state.steps:
            # Find the step after the last error
            error_step = None
            success_after_error = False
            for step in reversed(state.steps):
                if step.tool_result and not step.tool_result.success:
                    error_step = step
                    break
                if (
                    step.tool_result and step.tool_result.success
                    and step.tool_call and step.tool_call.name in ("edit_file", "write_file")
                ):
                    success_after_error = True

            if error_step and success_after_error:
                error_msg = (error_step.tool_result.error or error_step.tool_result.output)[:100]
                self.store(
                    type="error_pattern",
                    content=f"Encountered '{error_msg}' — resolved by subsequent edit",
                    tags=state.task.split()[0] if state.task else "unknown",
                    confidence="low",
                )

        # Learning 3: Task type → tool pattern mapping
        if state.steps:
            tool_sequence = []
            for step in state.steps:
                if step.tool_call:
                    tool_sequence.append(step.tool_call.name)

            if tool_sequence:
                # Create a compressed pattern
                pattern = self._compress_tool_pattern(tool_sequence)
                self.store(
                    type="tool_pattern",
                    content=f"For task '{state.task[:40]}': effective tool sequence was {pattern}",
                    tags=state.task.split()[0] if state.task else "unknown",
                    confidence="medium" if len(state.steps) > 5 else "low",
                )

        logger.info("Session learnings saved to memory store")

    @staticmethod
    def _compress_tool_pattern(tools: list[str]) -> str:
        """
        Compress a tool sequence into a readable pattern.

        E.g. [search, search, read, edit, run, edit, run]
         →   search*2 → read → edit → run → edit → run
        """
        if not tools:
            return "none"

        compressed: list[str] = []
        i = 0
        while i < len(tools):
            name = tools[i]
            count = 1
            while i + count < len(tools) and tools[i + count] == name:
                count += 1
            if count > 1:
                compressed.append(f"{name}x{count}")
            else:
                compressed.append(name)
            i += count

        return " → ".join(compressed[:12])

    # ── Loading AGENTS.md ─────────────────────────────────────

    def load_agents_md(self) -> None:
        """
        Load an AGENTS.md file from the working directory into memory.

        Parses the markdown into typed entries so they can be
        recalled during future sessions.
        """
        agents_md_path = self.workdir / "AGENTS.md"
        if not agents_md_path.exists():
            return

        try:
            content = agents_md_path.read_text(encoding="utf-8")
        except OSError:
            return

        # Parse sections (## headings)
        current_section = "general"
        for line in content.split("\n"):
            if line.startswith("## "):
                current_section = line[3:].strip().lower()
                continue

            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Store non-trivial lines as convention memories
            if len(stripped) > 10:
                self.store(
                    type="convention",
                    content=f"[AGENTS.md/{current_section}] {stripped}",
                    tags=current_section,
                    confidence="high",
                )

        logger.info("Loaded AGENTS.md into memory store")

    # ── Maintenance ───────────────────────────────────────────

    def prune_old_entries(self, max_age_days: int = 90) -> int:
        """
        Remove entries older than *max_age_days* with low access counts.

        Returns the number of entries pruned.
        """
        assert self._conn is not None

        cutoff = time.time() - (max_age_days * 86400)
        cursor = self._conn.execute(
            "DELETE FROM memories WHERE created_at < ? AND access_count < 2 AND confidence = 'low'",
            (cutoff,),
        )
        self._conn.commit()
        return cursor.rowcount

    def get_stats(self) -> dict[str, int]:
        """Return memory store statistics."""
        assert self._conn is not None

        total = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        by_type: dict[str, int] = {}
        rows = self._conn.execute(
            "SELECT type, COUNT(*) FROM memories GROUP BY type"
        ).fetchall()
        for type_name, count in rows:
            by_type[type_name] = count

        return {"total": total, **by_type}
