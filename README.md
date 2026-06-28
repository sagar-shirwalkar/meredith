# Meredith

[![Python](https://img.shields.io/badge/Python-3.13-fbad2b?style=for-the-badge&label=Python&labelColor=gray&logo=python&logoColor=blue)](https://python.org)
[![GitHub tag check runs](https://img.shields.io/github/check-runs/sagar-shirwalkar/meredith/v0.2.9?style=for-the-badge)](https://github.com/sagar-shirwalkar/meredith/actions)
[![OSSF-Scorecard Score](https://img.shields.io/ossf-scorecard/github.com/sagar-shirwalkar/meredith?style=for-the-badge&label=OSSF%20Scorecard)](https://securityscorecards.dev/viewer/?uri=github.com/sagar-shirwalkar/meredith)
[![AGPL-3.0](https://img.shields.io/badge/License-AGPL%20v3-blue?style=for-the-badge)](LICENSE)

<p align="center">
  <picture>
    <img src="assets/meredith.svg" width="400" height="400" alt="Meredith">
  </picture>
</p>

Meredith is an AI coding agent purpose-built for software engineering workflows. It operates a **ReAct loop** (Reason → Act → Observe) with strategic planning, RAG-augmented code understanding, and ACP (Agent Client Protocol) integration for native editor support.

- **Remote models** — any OpenAI-compatible API (OpenAI, Anthropic, Together AI, Fireworks, **Opencode**, Azure OpenAI, etc.)
- **Local models** — Ollama (7–70B) and MLX on Apple Silicon

---

## Features

- **ReAct Loop** — Reason, act, and observe in a tight feedback cycle with strategic planning.
- **RAG** — Tree-sitter AST chunking (with regex fallback) + BM25 retrieval for efficient codebase understanding.
- **ACP Native** — Run as an [Agent Client Protocol](https://agentclientprotocol.com) server for Zed, JetBrains, Neovim, Emacs, and any ACP-aware editor.
- **Smart Context** — Hierarchical context window with per-zone token budgets and automatic compression.
- **Loop Recovery** — Detects repetitive action patterns and applies corrective strategies.
- **Cross-Session Memory** — Learns project conventions, error patterns, and solutions across sessions via SQLite.
- **Skills** — Modular `SKILL.md` files that teach the agent new capabilities on the fly.
- **Dual Profile** — Optimised configurations for both large API models (200k context) and local 7–13B models (32k context).

---

## Quick Start

### 1. Install dependencies & hooks

```bash
make setup                                                      # Install deps, pre-commit hooks, and run lint (also adds MLX extras on Apple Silicon)
```

Or manually:

```bash
uv sync --extra dev                                    # Core + dev dependencies (all platforms)
uv sync --extra dev --extra mlx                        # Apple Silicon: add mlx + mlx-lm
uv run pre-commit install                              # Enable secret-scanning & quality hooks
```

> **Note:** `uv sync` replaces installed extras on each run. To combine dev and mlx extras, pass them together with a single `--extra` flag per extra (e.g. `--extra dev --extra mlx`). Running separate commands will keep only the last one's extras.

### 2. Configure credentials

```bash
export LLM_API_KEY="sk-..."                       # Required: key for your LLM provider (OpenAI, Anthropic, etc.)
export BRAVE_API_KEY="..."                        # Optional: enable Brave web search (or TAVILY_API_KEY / EXA_API_KEY)
```

### 3. Run the agent

```bash
uv run meredith "Add JWT authentication to the login endpoint"   # Execute a task
uv run meredith --profile local_model "Fix the failing test"     # Use a local model
uv run meredith -v "Explain the authentication flow"             # Verbose logging
```

### 4. Start the ACP server (for editor integration)

```bash
uv run python -m coding_agent.acp.server --profile large_model      # ACP stdio server
```

Point your editor at the server command above. See [Publishing to the ACP Registry](#publishing-to-the-acp-registry) for distribution.

---

## Configuration Profiles

| Profile | Provider | Context | Router | Planner | Use Case |
|---|---|---|---|---|---|
| `large_model` | Remote API (OpenAI-compatible) | 200k tokens | Hybrid (LLM + rules) | Tree-of-thought | Complex multi-file tasks |
| `local_model` | Ollama / MLX (7–13B) | 32k tokens | Rules only | Flat | Simple edits, offline use |

Edit `config/base.yaml` for shared defaults and `config/large_model.yaml` or `config/local_model.yaml` for profile-specific overrides.

---

## Project Structure

```
meredith/
├── pyproject.toml                    # Package metadata, dependencies, tool config
├── config/
│   ├── base.yaml                     # Shared defaults (token limits, thresholds, paths)
│   ├── large_model.yaml              # Overrides for remote API models
│   └── local_model.yaml              # Overrides for local Ollama/MLX models
├── src/coding_agent/
│   ├── main.py                       # CLI entry point, argument parsing, wiring
│   ├── config.py                     # YAML loading, merging, validation
│   ├── types.py                      # Shared dataclasses, enums, protocols
│   ├── agent/                        # ReAct loop orchestrator
│   │   ├── core.py                   # Main loop, step orchestration
│   │   ├── planner.py                # Strategic planner (tree-of-thought / flat)
│   │   └── verifier.py               # Post-step verification
│   ├── context/                      # Context window management
│   │   ├── manager.py                # Hierarchical context builder
│   │   ├── budget.py                 # Token budget tracker
│   │   └── compressor.py             # Output truncation and compression
│   ├── tools/                         # Agent tool implementations
│   │   ├── base.py                   # Tool protocol and registry
│   │   ├── router.py                 # LLM-driven + rule-based tool selection
│   │   ├── fs.py                     # File read/edit/write/list
│   │   ├── search.py                 # Code search (ripgrep)
│   │   ├── web.py                    # Web search and fetch
│   │   └── git.py                    # Git operations
│   ├── rag/                          # Retrieval-Augmented Generation
│   │   ├── chunker.py                # AST-aware chunking
│   │   ├── indexer.py                # SQLite-backed index
│   │   └── retriever.py              # BM25 + dense retrieval
│   ├── recovery/                     # Loop detection and escape
│   │   ├── detector.py               # Pattern detection (exact, semantic, stall)
│   │   └── strategies.py             # Recovery interventions
│   ├── llm/                          # LLM client abstractions
│   │   ├── base.py                   # LLM protocol and streaming types
│   │   ├── remote.py                 # OpenAI-compatible API client
│   │   └── local.py                  # Ollama + MLX client
│   ├── memory/                       # Cross-session memory
│   │   └── store.py                  # SQLite memory store
│   └── acp/                          # Agent Client Protocol server
│       └── server.py                 # ACP stdio server for editor integration
├── assets/                           # Project icon and branding assets
│   ├── meredith.svg                  # Primary logo (isometric M, dark bg)
│   ├── meredith-favicon.svg          # Favicon crop (no wordmark/decoration)
│   ├── meredith-light.svg            # Light background variant
│   ├── meredith-mono.svg             # Monochrome / print variant
│   ├── meredith-small.svg            # Tight crop for app icon (512×512)
│   └── logo-variants.md              # Variant specs and generation guide
├── tests/                                 # Test suite (224 tests covering >80% of core modules)
│   ├── __init__.py
│   ├── conftest.py                       # Shared fixtures (config, types, streaming)
│   ├── test_import.py                    # Package import smoke test
│   ├── test_types.py                     # Enums, dataclasses, Plan, ToolSchema
│   ├── test_config.py                    # YAML loading, merging, frozen dataclasses
│   ├── test_llm_base.py                  # Token counting, streaming chunks, tool call parsing
│   ├── test_budget.py                    # TokenBudget zone accounting, estimates
│   ├── test_compressor.py                # Output compression strategies (test, search, file)
│   ├── test_context_manager.py           # Hierarchical context zones, rotation, compression
│   ├── test_tool_base.py                 # ToolRegistry, executor dispatch, schemas
│   ├── test_router.py                    # Pre/post execution rules, availability, diagnostics
│   ├── test_verifier.py                  # Post-step verification checks
│   ├── test_detector.py                  # Loop detection (exact, error, semantic, stall)
│   ├── test_strategies.py                # Recovery interventions
│   ├── test_planner.py                   # FlatPlanner / TreeOfThoughtPlanner parsing
│   ├── test_memory.py                    # MemoryStore SQLite lifecycle, recall, pruning
│   ├── test_chunker.py                   # RegexChunker chunking strategies
│   ├── test_indexer.py                   # Indexer file indexing and search
│   ├── test_retriever.py                 # BM25Retriever scoring and retrieval
│   └── test_main.py                      # CLI argument parsing, client factory
├── .agents/skills/                   # Agent skill definitions (Zed/opencode compatible)
│   ├── agent-handoff/SKILL.md
│   ├── agentic-improvements/SKILL.md
│   ├── code-review/SKILL.md
│   ├── debugging/SKILL.md
│   ├── readme-writing/SKILL.md
│   ├── skill-writing/SKILL.md
│   └── web-browsing/SKILL.md
├── .github/workflows/ci.yml          # CI/CD pipeline
├── AGENTS.md                         # Project instructions for AI agents
└── README.md
```

---

## Skills

Skills are modular `SKILL.md` files that teach the agent specialized capabilities. They are loaded automatically from the following directories (configurable in `config/base.yaml` under `skills.directories`):

- `.agents/skills/` — project-bundled skills (Zed/opencode compatible)
- `.agent/skills/` — per-user overrides (gitignored)

### Installing a skill

1. Create a new directory under `.agents/skills/` with a descriptive name:

```bash
mkdir -p .agents/skills/react-patterns                                     # New skill directory
```

2. Write a `SKILL.md` file with instructions, conventions, and examples the agent should follow.
3. The agent discovers and loads the skill automatically on next startup.

### Discovering skills

Browse the community skill library at [skills.sh](https://www.skills.sh/) for ready-made skills covering React, Go, testing, security, and more. Skills are plain Markdown files — drop them in and they work.

---

## Architecture

The agent operates in a continuous ReAct loop:

1. Plan             Decompose task → ordered subtasks
2. Think            Reason about state and next action
3. Act              Execute tool (read, edit, search, run)
4. Observe          Process tool result
5. Verify           Check step quality (diagnostics, tests)
6. Recover          Detect loops → inject corrective action
7. Repeat           Until all subtasks complete

### Key design decisions

- **Token efficiency** — Every tool output is compressed before entering the context window. RAG provides symbol-level access instead of full file reads.
- **Graceful degradation** — Local models use simpler planning, rule-based tool routing, and more aggressive compression.
- **Safety** — Path traversal is blocked, git commits require explicit consent, and all operations are scoped to the working directory.

---

## Publishing to the ACP Registry

### Zed ACP Registry

The [ACP Registry](https://agentclientprotocol.com/registry) is a curated directory of ACP-compatible agents. To publish meredith:

1. **Fork the registry** at [github.com/agentclientprotocol/registry](https://github.com/agentclientprotocol/registry).
2. **Add your agent definition** to `agents/` (follow the existing entries as a template):

```yaml
# agents/meredith.yml
name: meredith
description: AI coding agent with RAG, smart context, and loop recovery
command: uv
args:
  - run
  - python
  - -m
  - coding_agent.acp.server
  - --profile
  - large_model
version: 0.2.9
```

3. **Add an icon** — use the icon at [`assets/meredith.svg`](assets/meredith.svg).
4. **Open a pull request** to the registry repository.

The registry supports authentication methods, version tracking, and links to source. See the [registry documentation](https://github.com/agentclientprotocol/registry) for full details.

### Opencode ACP Registry

Opencode also maintains an ACP registry. The process is similar:

1. **Visit the Opencode ACP registry** and follow their submission guidelines.
2. **Register your agent** with the same `uv run python -m coding_agent.acp.server` command.
3. **Specify your authentication method** — the registry supports token-based, OAuth, and API key methods.

---

## CI/CD

The project uses GitHub Actions for continuous integration and automated publishing:

| Workflow | Trigger | Actions |
|---|---|---|
| `lint` | Every push/PR | Ruff linting and formatting checks |
| `typecheck` | Every push/PR | Mypy strict mode type checking |
| `test` | Every push/PR | Pytest with coverage |
| `build` | Published release | Build wheel + publish to PyPI |

### Manual release

```bash
# 1. Tag the release
git tag v0.2.9
git push origin v0.2.9

# 2. Create a GitHub Release from the tag
#    The CI pipeline will automatically build and publish to PyPI.
```

The build step requires a `PYPI_TOKEN` secret configured in your GitHub repository settings.

---

## Development

```bash
make setup                                                      # One-shot: install deps, hooks, and lint (also adds MLX extras on Apple Silicon)
```

Or step by step:

```bash
uv sync --extra dev                                    # Core + dev dependencies (all platforms)
uv sync --extra dev --extra mlx                        # Apple Silicon: add mlx + mlx-lm
uv run pre-commit install                              # Enable secret-scanning hooks
make lint                                               # ruff check
make format                                             # ruff format
make typecheck                                          # mypy --strict (requires mypy installed)
make test                                               # pytest -v
uv run pytest tests/ -v --cov=coding_agent                    # Run tests with coverage report
uv run pytest tests/ -v --cov=coding_agent --cov-report=html  # Generate HTML coverage report
make check                                              # lint + typecheck + test (CI equivalent)
make clean                                              # Remove caches and build artifacts
```

---

## License

[AGPL-3.0](LICENSE)
