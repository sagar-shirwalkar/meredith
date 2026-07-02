# AGENTS.md — Project Instructions for AI Coding Agents

## Project Overview

This is meredith: a modern AI coding agent with RAG,
ACP (Agent Client Protocol) integration, and smart context
management. It supports both large remote models via any
OpenAI-compatible API (Claude, GPT, Opencode, etc.) and
local models (Ollama on Linux/macOS/Windows, MLX on Apple Silicon).

## Tech Stack

- Language: Python 3.13+
- Package manager: uv
- Async framework: asyncio
- HTTP client: httpx
- Token counting: tiktoken (cl100k_base)
- Code parsing: tree-sitter-languages (optional, no cp313 wheel)
- Database: SQLite (via stdlib)
- Search: ripgrep (preferred) or grep

## Development Environment

- Install: uv sync --extra dev
- Lint: uv run ruff check src/
- Format: uv run ruff format src/
- Type check: uv run mypy src/ (if configured)
- Test: uv run pytest tests/ -v

## Code Style

- Use Python 3.13+ syntax: X | Y unions, type statements, slots=True
- Use from __future__ import annotations in all files
- All functions and classes must have docstrings (triple double-quotes)
- Use async/await for all I/O operations
- Never use pandas — prefer built-in types and stdlib
- Never hardcode values that users might change — put them in config YAML

## Project Structure

- config/ — YAML configuration files (base, large_model, local_model)
- src/coding_agent/ — Main package
  - agent/ — Core loop, planner, verifier
  - context/ — Context window management
  - tools/ — Tool definitions and executors
    - base.py — ToolRegistry, schemas, executor ABC
    - router.py — Pre/post-execution rules, availability
    - fs.py — read_file, write_file, edit_file, list_directory
    - search.py — search_code, find_symbols, get_diagnostics
    - shell.py — run_command (asyncio subprocess)
    - web.py — web_search, web_fetch
    - git.py — git_status, git_diff, git_log, git_commit
  - rag/ — Retrieval-Augmented Generation subsystem
  - recovery/ — Loop detection and escape strategies
  - llm/ — LLM client abstractions (remote, local/MLX)
  - memory/ — Cross-session memory store
  - acp/ — ACP server for editor integration
- scripts/ — Standalone utilities
  - test_tool_calling.py — Validate model tool-calling compatibility
  - compact_checkpoints.py — Prune old checkpoints
- .agents/skills/ — SKILL.md files for agent capabilities
- .agent/ — Runtime data (index, memory DB, logs) — do not edit manually

## 14 Built-in Tools

All tools are registered in `ToolRegistry` and dispatched via `ToolExecutor` subclasses:

| Tool | Executor | Parameters |
|------|----------|------------|
| `read_file` | FsTools | path, start_line?, end_line? |
| `write_file` | FsTools | path, content |
| `edit_file` | FsTools | path, search, replace, regex? |
| `list_directory` | FsTools | path?, recursive? |
| `search_code` | SearchTools | pattern, path?, file_pattern?, regex?, max_results? |
| `find_symbols` | SearchTools | query, path? |
| `get_diagnostics` | SearchTools | path |
| `run_command` | ShellTools | command, cwd?, timeout? |
| `web_search` | WebTools | query, max_results? |
| `web_fetch` | WebTools | url, extract? |
| `git_status` | GitTools | (none) |
| `git_diff` | GitTools | staged?, path?, max_lines? |
| `git_log` | GitTools | n? |
| `git_commit` | GitTools | message |

## Local Models & Tool Calling

Not all Ollama models support tool calling. Models <1B params (e.g. `gemma3:270m`) return HTTP 400. Use the eval harness to test:

```bash
uv run python scripts/test_tool_calling.py --model YOUR_MODEL
```

See `CROSSWALK.md` and `README.md#local-model-guide` for details.

The recommended local profile config is in `config/local_model.yaml`.

## Testing Instructions

- Run all tests: uv run pytest tests/ -v (264+ tests)
- Run a single test: uv run pytest tests/test_specific.py -v
- Run with coverage: uv run pytest tests/ --cov=coding_agent
- Test tool-calling: uv run python scripts/test_tool_calling.py --list-models

## PR Instructions

- Title format: [area] Description (e.g. [rag] Add AST chunker for Go)
- Run uv run ruff check src/ and uv run pytest tests/ -v before committing
- Keep PRs focused — one concern per PR
- Document any new config keys in the appropriate YAML file

## Security Considerations

### Credential Management
- API keys are read from environment variables (e.g. `LLM_API_KEY`, `BRAVE_API_KEY`), never from source code, config files, or `.env` files within the project tree.
- The LLM client factory reads `api_key_env` from config and resolves it at runtime from the process environment — keys never appear in logs, dumps, or context windows.
- Git credentials used by the git tool are inherited from the host environment (git-credential-osxkeychain, etc.), never stored or forwarded by the agent.
- The memory store (SQLite) does not persist authentication tokens, session keys, or credentials of any kind.

### PII / Sensitive Data Protection
- Tool outputs (file contents, git diffs, search results, web responses) are **not automatically scrubbed** — the agent may process sensitive data present in the working directory. This is by design (the agent needs file contents to do its job).
- However, the context compressor may truncate long outputs, which provides a natural volume-based limit on how much raw data enters the LLM context window at once.
- The cross-session memory store explicitly excludes any content containing email addresses, API keys, tokens, or secrets patterns (`sk-...`, `ghp_...`, `-----BEGIN.*KEY-----`). See `memory/store.py:save_session`.
- All log files are written to `.agent/agent.log` (gitignored) and are local-only. Logs do not contain environment variable values or full API responses.

### Prompt Injection Mitigation
- Tool outputs are presented to the LLM as `TOOL`-role messages, which most frontier models treat as system-controlled rather than user-controlled content.
- The system prompt instructs the agent to treat file contents as data, not instructions. No tool output is ever interpreted as a directive to the agent loop itself.
- Web-fetched content is stripped of script tags and rendered to plain text before entering the context window.

### File System Safety
- All file operations (`read_file`, `edit_file`, `write_file`, `list_directory`) are scoped to the configured `working_directory`. Path traversal sequences (`..`) are explicitly rejected.
- The `write_file` and `edit_file` tools refuse to create symlinks outside the working tree.
- File writes are validated for encoding (UTF-8) before proceeding; binary files are not written through the agent tools.
- The `run_command` tool enforces a configurable timeout (default 120s) to prevent runaway processes.

### Subprocess & Shell Safety
- Shell commands are executed via `asyncio.create_subprocess_shell` with no shell injection surface — the entire command string is user-provided and passed to the shell directly. This is an accepted risk of the `run_command` tool; the agent is trusted within the working directory.
- The ACP server communicates exclusively over stdio (not TCP), eliminating network-based attack surface for editor integration.

### Data at Rest
- The RAG index and memory store are SQLite databases stored in `.agent/` (gitignored). They contain file paths, code chunks, and agent observations — not credentials.
- Users should ensure `.agent/` is excluded from backups that leave their security boundary.

### Supply Chain
- Dependencies are pinned to minor/major ranges (e.g. `httpx>=0.27,<1`) and managed via `uv.lock` for reproducible builds.
- The build process uses Hatchling (pure Python, no compiled extensions in the toolchain).
- CI runs `uv run ruff check`, `uv run mypy --strict`, and `uv run pytest --cov` on every PR to catch regressions.

### Rate Limiting & Resource Protection
- The `web_fetch` and `web_search` tools have configurable timeouts (default 15s) and result limits.
- The agent loop has a hard cap at `max_steps` (default 50) to prevent runaway token consumption.
- The context budget system prevents any single step from consuming more than 10% of the remaining budget.
