"""
Hybrid retriever: combines BM25 (sparse) and optional dense
retrieval for code search.

BM25 is the primary retrieval method — it works well for code
because identifier names and keywords carry strong signals.
Dense retrieval (embeddings) is optional and can be added later.

The retriever coordinates between the Indexer (for data) and
the agent's tool router (for search queries).
"""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Any

from coding_agent.config import AppConfig, RetrievalConfig
from coding_agent.llm.base import count_tokens
from coding_agent.rag.indexer import Indexer
from coding_agent.types import SearchResult

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# BM25 implementation
# ──────────────────────────────────────────────────────────────


class BM25:
    """
    Okapi BM25 ranking for code chunks.

    Uses token frequencies stored in the index to score
    chunks against a query.  No external dependencies required.
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = k1
        self.b = b
        self._doc_freqs: dict[str, int] = {}
        self._doc_lengths: dict[int, int] = {}
        self._avg_dl: float = 0.0
        self._n_docs: int = 0
        self._doc_tokens: dict[int, dict[str, int]] = {}

    def index(
        self,
        doc_tokens: dict[int, dict[str, int]],
    ) -> None:
        """
        Build the BM25 index from token frequencies.

        Args:
            doc_tokens: {chunk_id: {token: frequency}}
        """
        self._doc_tokens = doc_tokens
        self._n_docs = len(doc_tokens)
        self._doc_freqs = {}
        total_length = 0

        for doc_id, freqs in doc_tokens.items():
            doc_length = sum(freqs.values())
            self._doc_lengths[doc_id] = doc_length
            total_length += doc_length

            for token in freqs:
                self._doc_freqs[token] = self._doc_freqs.get(token, 0) + 1

        self._avg_dl = total_length / self._n_docs if self._n_docs > 0 else 1.0

    def score(
        self,
        query_tokens: list[str],
        top_k: int = 10,
    ) -> list[tuple[int, float]]:
        """
        Score all documents against a query.

        Args:
            query_tokens: List of query terms (lowercase).
            top_k: Return only the top K results.

        Returns:
            List of (chunk_id, score) tuples, sorted descending.
        """
        scores: dict[int, float] = {}

        for term in query_tokens:
            if term not in self._doc_freqs:
                continue

            df = self._doc_freqs[term]
            idf = math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1.0)

            for doc_id, freqs in self._doc_tokens.items():
                tf = freqs.get(term, 0)
                if tf == 0:
                    continue

                dl = self._doc_lengths[doc_id]
                tf_norm = (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * dl / self._avg_dl)
                )

                scores[doc_id] = scores.get(doc_id, 0.0) + idf * tf_norm

        # Sort by score descending
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


# ──────────────────────────────────────────────────────────────
# Retriever
# ──────────────────────────────────────────────────────────────


class Retriever:
    """
    Hybrid retrieval system for code.

    Combines:
      - Symbol lookup (exact name matching)
      - BM25 search (keyword matching)
      - Optional dense search (embeddings — not yet implemented)

    The retriever also provides a project_overview() method that
    returns a high-level summary for the planner.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.indexer = Indexer(config)
        self.bm25 = BM25()
        self._bm25_indexed = False

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        """Start the indexer and build the BM25 index."""
        await self.indexer.start()

        # Check if we need to index
        chunk_count = self.indexer.get_chunk_count()
        if chunk_count == 0 or self.config.rag.reindex_on_startup:
            logger.info("Building code index...")
            result = await self.indexer.index_project(force=self.config.rag.reindex_on_startup)
            logger.info("Indexed: %s", result)

        # Build BM25 index
        self._build_bm25_index()

    async def close(self) -> None:
        """Close the indexer."""
        await self.indexer.close()

    def _build_bm25_index(self) -> None:
        """Build the BM25 index from the chunk token frequencies."""
        doc_tokens = self.indexer.get_all_chunk_freqs()
        if doc_tokens:
            self.bm25.index(doc_tokens)
            self._bm25_indexed = True
            logger.info("BM25 index built: %d documents", len(doc_tokens))
        else:
            logger.warning("No chunks found — BM25 index is empty")

    # ── Public search methods ─────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int | None = None,
        search_type: str = "hybrid",
    ) -> list[SearchResult]:
        """
        Search the codebase for relevant code.

        Args:
            query: Natural language or code query.
            top_k: Number of results to return (default from config).
            search_type: "bm25" | "symbol" | "hybrid"

        Returns:
            List of SearchResult objects, sorted by relevance.
        """
        k = top_k or self.config.rag.retrieval.top_k

        if search_type == "symbol":
            return self._symbol_search(query, k)
        elif search_type == "bm25":
            return self._bm25_search(query, k)
        else:
            # Hybrid: combine symbol and BM25 results
            return self._hybrid_search(query, k)

    def find_symbol(self, name: str) -> list[SearchResult]:
        """
        Find a symbol definition by name.

        Returns symbol signatures (no body) to save tokens.
        """
        symbols = self.indexer.search_symbols(name, limit=10)
        results: list[SearchResult] = []

        for sym in symbols:
            content = sym.signature
            if sym.docstring:
                content += f"\n  {sym.docstring[:100]}"
            results.append(SearchResult(
                content=content,
                file_path=sym.file_path,
                line_start=sym.line_start,
                line_end=sym.line_end,
                score=1.0 if sym.name == name else 0.5,
                symbol_name=sym.name,
                source="symbol",
            ))

        return results

    def find_symbol_body(self, name: str, file_path: str | None = None) -> SearchResult | None:
        """
        Find the full body of a symbol by name.

        More expensive than find_symbol — use when you need
        the actual implementation, not just the signature.
        """
        body = self.indexer.get_symbol_body(name, file_path)
        if body is None:
            return None

        # We also need the metadata
        symbols = self.indexer.search_symbols(name, limit=1)
        if not symbols:
            return None

        sym = symbols[0]
        return SearchResult(
            content=body,
            file_path=sym.file_path,
            line_start=sym.line_start,
            line_end=sym.line_end,
            score=1.0,
            symbol_name=sym.name,
            source="symbol",
        )

    def project_overview(self) -> str:
        """
        Generate a brief project overview for the planner.

        Lists the main source files and their top-level symbols.
        """
        assert self.indexer._conn is not None

        # Get all indexed files
        rows = self.indexer._conn.execute(
            "SELECT DISTINCT file_path FROM symbols ORDER BY file_path"
        ).fetchall()
        files = [r[0] for r in rows]

        if not files:
            return f"Project at {self.config.agent.working_directory} (not yet indexed)"

        # Build a compact overview
        lines: list[str] = [f"Project structure ({len(files)} files with symbols):"]

        for file_path in files[:30]:
            symbols = self.indexer.get_file_symbols(file_path)
            sym_names = [f"{s.kind.value} {s.name}" for s in symbols[:8]]
            if len(symbols) > 8:
                sym_names.append(f"... +{len(symbols) - 8} more")
            lines.append(f"  {file_path}: {', '.join(sym_names)}")

        if len(files) > 30:
            lines.append(f"  ... +{len(files) - 30} more files")

        return "\n".join(lines)

    # ── Internal search methods ───────────────────────────────

    def _symbol_search(self, query: str, top_k: int) -> list[SearchResult]:
        """Search using symbol name matching."""
        symbols = self.indexer.search_symbols(query, limit=top_k)

        results: list[SearchResult] = []
        for sym in symbols:
            content = sym.signature
            if sym.docstring:
                content += f"\n  {sym.docstring[:100]}"
            results.append(SearchResult(
                content=content,
                file_path=sym.file_path,
                line_start=sym.line_start,
                line_end=sym.line_end,
                score=1.0 if sym.name == query else 0.7,
                symbol_name=sym.name,
                source="symbol",
            ))

        return results

    def _bm25_search(self, query: str, top_k: int) -> list[SearchResult]:
        """Search using BM25 keyword matching."""
        if not self._bm25_indexed:
            return []

        # Tokenise the query
        query_tokens = re.findall(r"\w+", query.lower())
        if not query_tokens:
            return []

        # Score documents
        scored = self.bm25.score(query_tokens, top_k=top_k * 2)

        # Fetch chunk data for scored documents
        assert self.indexer._conn is not None
        results: list[SearchResult] = []

        for chunk_id, score in scored[:top_k]:
            row = self.indexer._conn.execute(
                "SELECT file_path, line_start, line_end, content, symbol_name, symbol_kind "
                "FROM chunks WHERE id = ?",
                (chunk_id,),
            ).fetchone()

            if row:
                results.append(SearchResult(
                    content=row[3],
                    file_path=row[0],
                    line_start=row[1],
                    line_end=row[2],
                    score=score,
                    symbol_name=row[4],
                    source="bm25",
                ))

        return results

    def _hybrid_search(self, query: str, top_k: int) -> list[SearchResult]:
        """
        Combine symbol and BM25 search results.

        Symbol results get a score boost because exact name
        matches are usually more relevant.
        """
        bm25_weight = self.config.rag.retrieval.bm25_weight
        symbol_weight = 1.0 - bm25_weight

        # Get results from both methods
        symbol_results = self._symbol_search(query, top_k=top_k)
        bm25_results = self._bm25_search(query, top_k=top_k)

        # Normalise BM25 scores to [0, 1]
        if bm25_results:
            max_bm25 = max(r.score for r in bm25_results)
            if max_bm25 > 0:
                for r in bm25_results:
                    r.score = (r.score / max_bm25) * bm25_weight

        # Symbol results get a fixed high score
        for r in symbol_results:
            r.score = r.score * symbol_weight

        # Merge and deduplicate (by file_path + line_start)
        seen: set[tuple[str, int]] = set()
        merged: list[SearchResult] = []

        # Symbol results first (higher priority)
        for r in symbol_results:
            key = (r.file_path, r.line_start)
            if key not in seen:
                seen.add(key)
                merged.append(r)

        # Then BM25 results
        for r in bm25_results:
            key = (r.file_path, r.line_start)
            if key not in seen:
                seen.add(key)
                merged.append(r)

        # Sort by score descending
        merged.sort(key=lambda r: r.score, reverse=True)

        return merged[:top_k]
