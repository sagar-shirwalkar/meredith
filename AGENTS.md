# AGENTS.md — Project Instructions for AI Coding Agents

## Project Overview

This is coding-agent: a cutting-edge AI coding agent with RAG,
MCP integration, and smart context management. It supports both
large remote models (Claude, GPT-4) and local models (Ollama/MLX).

## Tech Stack

- Language: Python 3.13+
- Package manager: uv
- Async framework: asyncio
- HTTP client: httpx
- Token counting: tiktoken (cl100k_base)
- Code parsing: tree-sitter-languages (optional)
- Database: SQLite (via stdlib)
- Search: ripgrep (preferred) or grep

## Development Environment

- Install: uv sync
- Lint: uv run ruff check src/
- Format: uv run ruff format src/
- Type check: uv run mypy src/ (if configured)
- Test: uv run pytest tests/

## Code Style

- Use Python 3.13+ syntax: X | Y unions, type statements, slots=True
- Use from __future__ import annotations in all files
- All functions and classes must have docstrings (triple double-quotes)
- Use async/await for all I/O operations
- Never use pandas — prefer built-in types and stdlib
- Never hardcode values that users might want to change — put them in config YAML

## Project Structure

- config/ — YAML configuration files (base, large_model, local_model)
- src/coding_agent/ — Main package
  - agent/ — Core loop, planner, verifier
  - context/ — Context window management
  - tools/ — Tool definitions and executors
  - rag/ — Retrieval-Augmented Generation subsystem
  - recovery/ — Loop detection and escape strategies
  - llm/ — LLM client abstractions (remote, local/MLX)
  - memory/ — Cross-session memory store
  - mcp/ — MCP server and client
- skills/ — SKILL.md files for agent capabilities
- .agent/ — Runtime data (index, memory DB, logs) — do not edit manually

## Testing Instructions

- Run all tests: uv run pytest tests/ -v
- Run a single test: uv run pytest tests/test_specific.py -v
- Run with coverage: uv run pytest tests/ --cov=coding_agent

## PR Instructions

- Title format: [area] Description (e.g. [rag] Add AST chunker for Go)
- Run uv run ruff check and uv run pytest before committing
- Keep PRs focused — one concern per PR
- Document any new config keys in the appropriate YAML file

## Security Considerations

- API keys are read from environment variables, never hardcoded
- The filesystem tools reject path traversal (..)
- Git commit is blocked unless auto_commit is explicitly enabled
- MCP server connections are subprocess-isolated
