"""
Code indexer: builds a SQLite-backed index of symbols and chunks.

The index supports two kinds of lookups:
  1. Symbol search: find function/class definitions by name
  2. Chunk search: find code regions by content (BM25-style)

The indexer is incremental — it only re-indexes files that have
changed since the last indexing run (tracked by mtime hash).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from coding_agent.config import AppConfig
from coding_agent.rag.chunker import AstChunker, Chunker, RegexChunker, create_chunker
from coding_agent.types import CodeChunk, Symbol, SymbolKind

logger = logging.getLogger(__name__)

# Directories and files to skip during indexing
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".mypy_cache",
    ".pytest_cache", ".tox", ".venv", "venv", "env",
    ".agent", "dist", "build", "target", ".next", ".nuxt",
    "vendor", "Pods", ".gradle", ".idea", ".vscode",
}

_SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".db", ".sqlite", ".sqlite3",
    ".woff", ".woff2", ".ttf", ".eot",
    ".lock", ".min.js", ".min.css",
}

_SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Gemfile.lock", "Cargo.lock", "go.sum",
    ".DS_Store", "Thumbs.db",
}


class Indexer:
    """
    Builds and manages the code index.

    The index is stored as a SQLite database in the configured
    index directory.  It contains:
      - symbols: function/class definitions with signatures
      - chunks: code regions with token frequencies for BM25
      - file_hashes: track which files have been indexed
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.workdir = Path(config.agent.working_directory).resolve()
        self.index_dir = self.workdir / config.rag.index_dir
        self.db_path = self.index_dir / "code_index.db"
        self.chunker = create_chunker(config.rag.chunk)
        self._conn: sqlite3.Connection | None = None

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise the database and create tables."""
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()
        logger.info("Indexer started: db=%s", self.db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Table creation ────────────────────────────────────────

    def _create_tables(self) -> None:
        """Create the index tables if they do not exist."""
        assert self._conn is not None

        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                file_path TEXT NOT NULL,
                line_start INTEGER NOT NULL,
                line_end INTEGER NOT NULL,
                signature TEXT NOT NULL DEFAULT '',
                docstring TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_symbols_name
                ON symbols(name);

            CREATE INDEX IF NOT EXISTS idx_symbols_file
                ON symbols(file_path);

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                line_start INTEGER NOT NULL,
                line_end INTEGER NOT NULL,
                content TEXT NOT NULL,
                symbol_name TEXT,
                symbol_kind TEXT,
                token_freq_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_file
                ON chunks(file_path);

            CREATE INDEX IF NOT EXISTS idx_chunks_symbol
                ON chunks(symbol_name);

            CREATE TABLE IF NOT EXISTS file_hashes (
                file_path TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                indexed_at REAL NOT NULL
            );
        """)
        self._conn.commit()

    # ── Indexing ──────────────────────────────────────────────

    async def index_project(self, force: bool = False) -> dict[str, int]:
        """
        Index the entire project.

        Only re-indexes files that have changed since the last
        indexing run (unless force=True).

        Returns:
            Dict with counts: {"files_indexed": N, "symbols": N, "chunks": N}
        """
        assert self._conn is not None

        source_files = self._discover_source_files()
        files_indexed = 0
        total_symbols = 0
        total_chunks = 0

        for file_path in source_files:
            # Check if the file needs re-indexing
            if not force and self._is_file_current(file_path):
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Remove old data for this file
            rel_path = str(file_path.relative_to(self.workdir))
            self._remove_file_data(rel_path)

            # Chunk the file
            chunks = self.chunker.chunk_file(file_path, content)

            # Extract symbols from chunks
            symbols = self._extract_symbols(chunks, content)

            # Insert into database
            self._insert_symbols(symbols)
            self._insert_chunks(chunks)

            # Update file hash
            content_hash = hashlib.md5(content.encode()).hexdigest()
            import time
            self._conn.execute(
                "INSERT OR REPLACE INTO file_hashes (file_path, content_hash, indexed_at) VALUES (?, ?, ?)",
                (rel_path, content_hash, time.time()),
            )

            files_indexed += 1
            total_symbols += len(symbols)
            total_chunks += len(chunks)

        self._conn.commit()

        logger.info(
            "Indexing complete: %d files, %d symbols, %d chunks",
            files_indexed, total_symbols, total_chunks,
        )

        return {
            "files_indexed": files_indexed,
            "symbols": total_symbols,
            "chunks": total_chunks,
        }

    def _discover_source_files(self) -> list[Path]:
        """Walk the project directory and find source files to index."""
        source_extensions = {
            ".py", ".js", ".ts", ".tsx", ".jsx",
            ".rs", ".go", ".java", ".rb", ".c", ".cpp",
            ".cs", ".swift", ".kt", ".scala", ".lua", ".php",
            ".md", ".yaml", ".yml", ".toml", ".json",
        }

        files: list[Path] = []
        max_files = 5000  # Safety limit

        for root, dirs, filenames in os.walk(self.workdir):
            # Skip ignored directories
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]

            for filename in filenames:
                if filename in _SKIP_FILES:
                    continue
                ext = Path(filename).suffix.lower()
                if ext in _SKIP_EXTENSIONS:
                    continue
                if ext not in source_extensions:
                    continue

                file_path = Path(root) / filename
                # Skip very large files (>1MB)
                try:
                    if file_path.stat().st_size > 1024 * 1024:
                        continue
                except OSError:
                    continue

                files.append(file_path)
                if len(files) >= max_files:
                    logger.warning("File limit reached (%d) — some files not indexed", max_files)
                    return files

        return files

    def _is_file_current(self, file_path: Path) -> bool:
        """Check if a file has already been indexed with the same content hash."""
        assert self._conn is not None
        try:
            rel_path = str(file_path.relative_to(self.workdir))
            content = file_path.read_text(encoding="utf-8", errors="replace")
            current_hash = hashlib.md5(content.encode()).hexdigest()

            row = self._conn.execute(
                "SELECT content_hash FROM file_hashes WHERE file_path = ?",
                (rel_path,),
            ).fetchone()

            return row is not None and row[0] == current_hash
        except (OSError, ValueError):
            return False

    def _remove_file_data(self, rel_path: str) -> None:
        """Remove all indexed data for a file."""
        assert self._conn is not None
        self._conn.execute("DELETE FROM symbols WHERE file_path = ?", (rel_path,))
        self._conn.execute("DELETE FROM chunks WHERE file_path = ?", (rel_path,))
        self._conn.execute("DELETE FROM file_hashes WHERE file_path = ?", (rel_path,))

    # ── Symbol extraction ─────────────────────────────────────

    def _extract_symbols(self, chunks: list[CodeChunk], content: str) -> list[Symbol]:
        """
        Extract Symbol objects from chunks.

        Chunks that have a symbol_name represent a definition.
        We extract the signature (first line) and docstring.
        """
        symbols: list[Symbol] = []
        lines = content.split("\n")

        for chunk in chunks:
            if not chunk.symbol_name or chunk.symbol_kind in (None, SymbolKind.MODULE):
                continue

            # Extract signature: first non-blank, non-comment line
            signature = self._extract_signature(chunk.content)

            # Extract docstring: first string literal after the signature
            docstring = self._extract_docstring(chunk.content)

            # Body is the full chunk content
            body = chunk.content

            symbols.append(Symbol(
                name=chunk.symbol_name,
                kind=chunk.symbol_kind or SymbolKind.FUNCTION,
                file_path=chunk.file_path,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
                signature=signature,
                docstring=docstring,
                body=body,
            ))

        return symbols

    @staticmethod
    def _extract_signature(chunk_content: str) -> str:
        """Extract the function/class signature from a chunk (first meaningful line)."""
        for line in chunk_content.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("//"):
                continue
            # Truncate long signatures
            if len(stripped) > 120:
                stripped = stripped[:117] + "..."
            return stripped
        return ""

    @staticmethod
    def _extract_docstring(chunk_content: str) -> str:
        """
        Extract the docstring from a chunk.

        Looks for triple-quoted strings after the signature line.
        """
        lines = chunk_content.split("\n")
        in_sig = False

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not in_sig:
                # Skip until we find the signature line
                if stripped and not stripped.startswith("#") and not stripped.startswith("//"):
                    in_sig = True
                continue

            # After signature, look for docstring
            if stripped.startswith('"""') or stripped.startswith("'''"):
                # Single-line docstring
                if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                    return stripped[3:-3].strip()
                # Multi-line docstring
                quote_char = stripped[:3]
                doc_lines = [stripped[3:]]
                for j in range(i + 1, min(i + 20, len(lines))):
                    next_line = lines[j].strip()
                    if quote_char in next_line:
                        doc_lines.append(next_line[:next_line.index(quote_char)])
                        break
                    doc_lines.append(next_line)
                return " ".join(doc_lines).strip()[:200]

            # If we hit non-docstring content, stop
            if stripped and not stripped.startswith("#"):
                break

        return ""

    # ── Database inserts ──────────────────────────────────────

    def _insert_symbols(self, symbols: list[Symbol]) -> None:
        """Insert symbols into the database."""
        assert self._conn is not None
        for sym in symbols:
            self._conn.execute(
                """INSERT INTO symbols (name, kind, file_path, line_start, line_end,
                   signature, docstring, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sym.name,
                    sym.kind.value,
                    sym.file_path,
                    sym.line_start,
                    sym.line_end,
                    sym.signature,
                    sym.docstring,
                    sym.body,
                ),
            )

    def _insert_chunks(self, chunks: list[CodeChunk]) -> None:
        """Insert chunks into the database."""
        assert self._conn is not None
        for chunk in chunks:
            self._conn.execute(
                """INSERT INTO chunks (file_path, line_start, line_end, content,
                   symbol_name, symbol_kind, token_freq_json) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk.file_path,
                    chunk.line_start,
                    chunk.line_end,
                    chunk.content,
                    chunk.symbol_name,
                    chunk.symbol_kind.value if chunk.symbol_kind else None,
                    json.dumps(chunk.token_frequencies),
                ),
            )

    # ── Queries ───────────────────────────────────────────────

    def search_symbols(self, query: str, limit: int = 20) -> list[Symbol]:
        """
        Search for symbols by name.

        Supports exact and prefix matching.
        """
        assert self._conn is not None

        # Try exact match first
        rows = self._conn.execute(
            "SELECT name, kind, file_path, line_start, line_end, signature, docstring "
            "FROM symbols WHERE name = ? ORDER BY file_path LIMIT ?",
            (query, limit),
        ).fetchall()

        # Then prefix match
        if len(rows) < limit:
            remaining = limit - len(rows)
            prefix_rows = self._conn.execute(
                "SELECT name, kind, file_path, line_start, line_end, signature, docstring "
                "FROM symbols WHERE name LIKE ? AND name != ? ORDER BY file_path LIMIT ?",
                (f"{query}%", query, remaining),
            ).fetchall()
            rows.extend(prefix_rows)

        # Then fuzzy match (contains)
        if len(rows) < limit:
            remaining = limit - len(rows)
            fuzzy_rows = self._conn.execute(
                "SELECT name, kind, file_path, line_start, line_end, signature, docstring "
                "FROM symbols WHERE name LIKE ? AND name NOT LIKE ? AND name != ? "
                "ORDER BY file_path LIMIT ?",
                (f"%{query}%", f"{query}%", query, remaining),
            ).fetchall()
            rows.extend(fuzzy_rows)

        return [
            Symbol(
                name=r[0],
                kind=SymbolKind(r[1]),
                file_path=r[2],
                line_start=r[3],
                line_end=r[4],
                signature=r[5],
                docstring=r[6],
            )
            for r in rows
        ]

    def get_symbol_body(self, name: str, file_path: str | None = None) -> str | None:
        """Get the full body of a symbol by name."""
        assert self._conn is not None

        if file_path:
            row = self._conn.execute(
                "SELECT body FROM symbols WHERE name = ? AND file_path = ? LIMIT 1",
                (name, file_path),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT body FROM symbols WHERE name = ? LIMIT 1",
                (name,),
            ).fetchone()

        return row[0] if row else None

    def get_all_chunk_freqs(self) -> dict[int, dict[str, int]]:
        """
        Get token frequencies for all chunks (for BM25 IDF computation).

        Returns: {chunk_id: {token: frequency}}
        """
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT id, token_freq_json FROM chunks"
        ).fetchall()

        result: dict[int, dict[str, int]] = {}
        for chunk_id, freq_json in rows:
            try:
                result[chunk_id] = json.loads(freq_json)
            except json.JSONDecodeError:
                result[chunk_id] = {}
        return result

    def get_chunk_count(self) -> int:
        """Return the total number of indexed chunks."""
        assert self._conn is not None
        row = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return row[0] if row else 0

    def get_file_symbols(self, file_path: str) -> list[Symbol]:
        """Get all symbols for a specific file."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT name, kind, file_path, line_start, line_end, signature, docstring "
            "FROM symbols WHERE file_path = ? ORDER BY line_start",
            (file_path,),
        ).fetchall()

        return [
            Symbol(
                name=r[0],
                kind=SymbolKind(r[1]),
                file_path=r[2],
                line_start=r[3],
                line_end=r[4],
                signature=r[5],
                docstring=r[6],
            )
            for r in rows
        ]
