"""
Code chunker: splits source files into semantically meaningful
chunks for indexing and retrieval.

Two implementations:
  - AstChunker: Uses tree-sitter for precise AST-based chunking
                (requires tree-sitter-languages package)
  - RegexChunker: Uses regex heuristics as a fallback
                  (always available, no extra dependencies)

Both produce CodeChunk objects that can be indexed by the Indexer.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from coding_agent.config import ChunkConfig
from coding_agent.types import CodeChunk, SymbolKind

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Language definitions for regex-based chunking
# ──────────────────────────────────────────────────────────────

# Maps file extension → (function_pattern, class_pattern, comment_prefix)
_LANG_RULES: dict[str, dict[str, Any]] = {
    ".py": {
        "function": re.compile(r"^(\s*)(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE),
        "class": re.compile(r"^(\s*)class\s+(\w+)\s*[:\(]", re.MULTILINE),
        "comment": "#",
        "indent_size": 4,
    },
    ".ts": {
        "function": re.compile(
            r"^(\s*)(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(|"
            r"^(\s*)(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s+)?\(",
            re.MULTILINE,
        ),
        "class": re.compile(r"^(\s*)(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", re.MULTILINE),
        "comment": "//",
        "indent_size": 2,
    },
    ".js": {
        "function": re.compile(
            r"^(\s*)(?:async\s+)?function\s+(\w+)\s*\(|"
            r"^(\s*)(?:const|let)\s+(\w+)\s*=\s*(?:async\s+)?\(",
            re.MULTILINE,
        ),
        "class": re.compile(r"^(\s*)class\s+(\w+)", re.MULTILINE),
        "comment": "//",
        "indent_size": 2,
    },
    ".rs": {
        "function": re.compile(r"^(\s*)(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*[\(<]", re.MULTILINE),
        "class": re.compile(
            r"^(\s*)(?:pub\s+)?(?:struct|enum|impl|trait)\s+(\w+)", re.MULTILINE
        ),
        "comment": "//",
        "indent_size": 4,
    },
    ".go": {
        "function": re.compile(r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(", re.MULTILINE),
        "class": re.compile(r"^type\s+(\w+)\s+struct", re.MULTILINE),
        "comment": "//",
        "indent_size": 4,
    },
    ".java": {
        "function": re.compile(
            r"^(\s+)(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\(",
            re.MULTILINE,
        ),
        "class": re.compile(
            r"^(\s*)(?:public|private|protected)?\s*(?:abstract\s+)?(?:class|interface|enum)\s+(\w+)",
            re.MULTILINE,
        ),
        "comment": "//",
        "indent_size": 4,
    },
    ".rb": {
        "function": re.compile(r"^(\s*)def\s+(\w+)", re.MULTILINE),
        "class": re.compile(r"^(\s*)class\s+(\w+)", re.MULTILINE),
        "comment": "#",
        "indent_size": 2,
    },
}


# ──────────────────────────────────────────────────────────────
# Abstract chunker
# ──────────────────────────────────────────────────────────────


class Chunker(ABC):
    """Base class for code chunkers."""

    def __init__(self, config: ChunkConfig) -> None:
        self.config = config

    @abstractmethod
    def chunk_file(self, path: Path, content: str) -> list[CodeChunk]:
        """
        Split a file's content into chunks.

        Args:
            path: The file's path (for metadata).
            content: The file's full text content.

        Returns:
            List of CodeChunk objects.
        """
        ...

    def _make_chunk(
        self,
        path: Path,
        content: str,
        line_start: int,
        line_end: int,
        symbol_name: str | None = None,
        symbol_kind: SymbolKind | None = None,
    ) -> CodeChunk:
        """Create a CodeChunk with computed token frequencies."""
        lines = content.split("\n")
        selected = lines[line_start - 1 : line_end]
        chunk_content = "\n".join(selected)

        # Simple token frequency for BM25 scoring
        tokens = re.findall(r"\w+", chunk_content.lower())
        freq: dict[str, int] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1

        return CodeChunk(
            file_path=str(path),
            line_start=line_start,
            line_end=line_end,
            content=chunk_content,
            symbol_name=symbol_name,
            symbol_kind=symbol_kind,
            token_frequencies=freq,
        )


# ──────────────────────────────────────────────────────────────
# Regex-based chunker (fallback, no dependencies)
# ──────────────────────────────────────────────────────────────


class RegexChunker(Chunker):
    """
    Chunker that uses regex patterns to identify function and
    class boundaries.

    Works for Python, TypeScript, JavaScript, Rust, Go, Java,
    and Ruby.  Falls back to fixed-size chunking for unknown
    languages.
    """

    def chunk_file(self, path: Path, content: str) -> list[CodeChunk]:
        """
        Chunk a file using regex-based symbol detection.

        Strategy:
          1. Find all function/class definitions
          2. Each definition becomes a chunk (from its start line
             to the next definition or end of file)
          3. Any code before the first definition is a "module" chunk
          4. If no definitions are found, use fixed-size chunking
        """
        ext = path.suffix.lower()
        rules = _LANG_RULES.get(ext)

        if rules:
            return self._chunk_with_rules(path, content, rules)
        else:
            return self._chunk_fixed_size(path, content)

    def _chunk_with_rules(
        self,
        path: Path,
        content: str,
        rules: dict[str, Any],
    ) -> list[CodeChunk]:
        """Chunk using language-specific regex rules."""
        lines = content.split("\n")
        total_lines = len(lines)

        # Find all symbol boundaries
        symbols: list[tuple[int, str, SymbolKind]] = []

        func_re: re.Pattern[str] = rules["function"]
        class_re: re.Pattern[str] = rules["class"]

        for match in func_re.finditer(content):
            # Determine the function name (could be group 2 or 4)
            name = match.group(2) or match.group(4) or match.group(1) or "anonymous"
            line_num = content[: match.start()].count("\n") + 1
            symbols.append((line_num, name, SymbolKind.FUNCTION))

        for match in class_re.finditer(content):
            name = match.group(2) or match.group(1)
            line_num = content[: match.start()].count("\n") + 1
            symbols.append((line_num, name, SymbolKind.CLASS))

        # Sort by line number
        symbols.sort(key=lambda x: x[0])

        if not symbols:
            # No symbols found — use fixed-size chunking
            return self._chunk_fixed_size(path, content)

        chunks: list[CodeChunk] = []

        # Module-level code before first symbol
        first_line = symbols[0][0]
        if first_line > 1:
            chunks.append(
                self._make_chunk(
                    path, content, 1, first_line - 1,
                    symbol_name=f"{path.stem}_module",
                    symbol_kind=SymbolKind.MODULE,
                )
            )

        # Create chunks for each symbol
        max_lines = self.config.max_lines
        for i, (start_line, name, kind) in enumerate(symbols):
            # End line is the start of the next symbol or end of file
            end_line = symbols[i + 1][0] - 1 if i + 1 < len(symbols) else total_lines

            # If the symbol is very long, split it
            symbol_length = end_line - start_line + 1
            if symbol_length > max_lines:
                # Split into max_lines chunks
                offset = start_line
                while offset <= end_line:
                    chunk_end = min(offset + max_lines - 1, end_line)
                    suffix = (
                        f"_part{(offset - start_line) // max_lines + 1}"
                        if symbol_length > max_lines * 1.5
                        else ""
                    )
                    chunks.append(
                        self._make_chunk(
                            path, content, offset, chunk_end,
                            symbol_name=f"{name}{suffix}",
                            symbol_kind=kind,
                        )
                    )
                    offset = chunk_end + 1
            else:
                chunks.append(
                    self._make_chunk(
                        path, content, start_line, end_line,
                        symbol_name=name,
                        symbol_kind=kind,
                    )
                )

        return chunks

    def _chunk_fixed_size(self, path: Path, content: str) -> list[CodeChunk]:
        """
        Fallback: split into fixed-size chunks with overlap.

        Used when no language rules are available.
        """
        lines = content.split("\n")
        total_lines = len(lines)
        max_lines = self.config.max_lines
        overlap = self.config.overlap_lines

        if total_lines <= max_lines:
            return [self._make_chunk(path, content, 1, total_lines)]

        chunks: list[CodeChunk] = []
        start = 1
        while start <= total_lines:
            end = min(start + max_lines - 1, total_lines)
            chunks.append(self._make_chunk(path, content, start, end))
            start = end - overlap + 1
            if start <= chunks[-1].line_start:
                # Avoid infinite loop
                start = end + 1

        return chunks


# ──────────────────────────────────────────────────────────────
# AST-based chunker (tree-sitter, optional)
# ──────────────────────────────────────────────────────────────


class AstChunker(Chunker):
    """
    Chunker that uses tree-sitter for precise AST-aware chunking.

    Falls back to RegexChunker if tree-sitter is not available
    or if the language is not supported.
    """

    def __init__(self, config: ChunkConfig) -> None:
        super().__init__(config)
        self._regex_chunker = RegexChunker(config)
        self._ts_available = False
        try:
            import tree_sitter_languages  # type: ignore[import-not-found]  # noqa: F401
            self._ts_available = True
            logger.info("tree-sitter-languages available — AST chunking enabled")
        except ImportError:
            logger.info("tree-sitter-languages not installed — using regex chunking")

    def chunk_file(self, path: Path, content: str) -> list[CodeChunk]:
        """Chunk using tree-sitter if available, regex otherwise."""
        if not self._ts_available:
            return self._regex_chunker.chunk_file(path, content)

        ext = path.suffix.lower()
        lang = self._ext_to_language(ext)
        if lang is None:
            return self._regex_chunker.chunk_file(path, content)

        try:
            return self._chunk_with_treesitter(path, content, lang)
        except Exception as exc:
            logger.warning(
                "tree-sitter chunking failed for %s: %s — falling back to regex", path, exc
            )
            return self._regex_chunker.chunk_file(path, content)

    def _chunk_with_treesitter(
        self,
        path: Path,
        content: str,
        language: str,
    ) -> list[CodeChunk]:
        """Use tree-sitter to parse and chunk a file."""
        import tree_sitter_languages  # noqa: F401

        parser = tree_sitter_languages.get_parser(language)
        tree = parser.parse(content.encode("utf-8"))

        chunks: list[CodeChunk] = []
        max_lines = self.config.max_lines

        # Node types that represent symbol definitions
        definition_types = {
            "function_definition", "class_definition", "method_definition",
            "decorated_definition",  # Python decorators
            "function_item", "impl_item", "struct_item", "enum_item", "trait_item",  # Rust
            "function_declaration", "class_declaration", "interface_declaration",  # TS
            "method_declaration", "type_declaration",  # Go
        }

        _lines = content.split("\n")

        def visit(node: Any) -> None:
            """Recursively visit AST nodes to find definitions."""
            if node.type in definition_types:
                # Extract the actual definition (unwrap decorators)
                actual_node = node
                if node.type == "decorated_definition" and node.children:
                    actual_node = node.children[-1]

                start_line = actual_node.start_point[0] + 1
                end_line = actual_node.end_point[0] + 1
                name = self._extract_name(actual_node, content)
                kind = self._node_kind(actual_node.type)

                # If the definition is very long, split it
                if end_line - start_line + 1 > max_lines:
                    offset = start_line
                    while offset <= end_line:
                        chunk_end = min(offset + max_lines - 1, end_line)
                        part = (offset - start_line) // max_lines + 1
                        chunks.append(
                            self._make_chunk(
                                path, content, offset, chunk_end,
                                symbol_name=f"{name}_part{part}" if name else None,
                                symbol_kind=kind,
                            )
                        )
                        offset = chunk_end + 1
                else:
                    chunks.append(
                        self._make_chunk(
                            path, content, start_line, end_line,
                            symbol_name=name,
                            symbol_kind=kind,
                        )
                    )
            else:
                # Recurse into children
                for child in node.children:
                    visit(child)

        visit(tree.root_node)

        # If no definitions found, fall back to fixed-size
        if not chunks:
            return self._regex_chunker._chunk_fixed_size(path, content)

        # Add module-level code (before first definition)
        first_start = min(c.line_start for c in chunks)
        if first_start > 1:
            chunks.insert(0, self._make_chunk(
                path, content, 1, first_start - 1,
                symbol_name=f"{path.stem}_module",
                symbol_kind=SymbolKind.MODULE,
            ))

        # Sort by line number
        chunks.sort(key=lambda c: c.line_start)
        return chunks

    @staticmethod
    def _extract_name(node: Any, content: str) -> str | None:
        """Extract the name of a definition from its AST node."""
        # For most languages, the name is the first identifier child
        for child in node.children:
            if child.type == "identifier" or child.type == "type_identifier":
                return content[child.start_byte : child.end_byte]
            if child.type == "property_identifier":
                return content[child.start_byte : child.end_byte]
            if child.type == "name":
                return content[child.start_byte : child.end_byte]
        return None

    @staticmethod
    def _node_kind(node_type: str) -> SymbolKind:
        """Map tree-sitter node types to SymbolKind."""
        if "class" in node_type or "struct" in node_type or "impl" in node_type:
            return SymbolKind.CLASS
        if "function" in node_type or "method" in node_type:
            return SymbolKind.FUNCTION
        if "enum" in node_type or "trait" in node_type or "interface" in node_type:
            return SymbolKind.CLASS
        return SymbolKind.VARIABLE

    @staticmethod
    def _ext_to_language(ext: str) -> str | None:
        """Map file extension to tree-sitter language name."""
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".rb": "ruby",
            ".c": "c",
            ".cpp": "cpp",
            ".cs": "c_sharp",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
            ".lua": "lua",
            ".php": "php",
        }
        return mapping.get(ext)


# ──────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────


def create_chunker(config: ChunkConfig) -> Chunker:
    """
    Create the appropriate chunker based on config.

    If strategy is "ast" and tree-sitter is available, use AstChunker.
    Otherwise, fall back to RegexChunker.
    """
    if config.strategy == "ast":
        return AstChunker(config)
    return RegexChunker(config)
