# mentis-agent

Mentis is an AI coding agent with RAG, MCP integration, and smart context management.
Supports both large remote models (Claude, GPT-4) and local models (Ollama / MLX on Apple Silicon and Linux+CUDA).

## Features

- **ReAct Loop**: Think -> Act -> Observe cycle with strategic planning
- **RAG**: AST-aware code chunking and BM25 retrieval for efficient
  codebase understanding
- **MCP**: Run as a server for Zed/Opencode, or connect to external
  MCP servers
- **Smart Context**: Hierarchical context window with token budgets
  and auto-compression
- **Loop Recovery**: Detects and escapes repetitive action patterns
- **Cross-Session Memory**: Learns project conventions and patterns
  over time
- **Skills**: Modular SKILL.md files that teach the agent new
  capabilities
- **Dual Profile**: Optimised configs for both large API models and
  local 7-13B models

## Poject Structure

```
mentis-agent/
├── pyproject.toml
├── config/
│   ├── base.yaml                 # Shared defaults (token limits, thresholds, paths)
│   ├── large_model.yaml          # Overrides for remote API models (Claude, GPT-4)
│   └── local_model.yaml          # Overrides for local Ollama/MLX 7-13B models
├── src/
│   └── coding_agent/
│       ├── __init__.py            # Package root, version, public API
│       ├── main.py                # CLI entry point, argument parsing, wiring
│       ├── config.py              # YAML load, merge, validation, dataclass mapping
│       ├── types.py               # All shared dataclasses, enums, protocols
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── core.py            # Main ReAct loop, step orchestration
│       │   ├── planner.py         # Strategic planner (tree-of-thought for large, flat for local)
│       │   └── verifier.py        # Post-step verification (diagnostics, test, diff check)
│       ├── context/
│       │   ├── __init__.py
│       │   ├── manager.py         # Hierarchical context window builder
│       │   ├── budget.py          # Token budget tracker with per-zone accounting
│       │   └── compressor.py      # Output truncation, summarization, template compression
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── base.py            # Tool protocol, ToolRegistry, ToolSchema dataclass
│       │   ├── router.py          # LLM-driven + rule-based + learned tool selection
│       │   ├── fs.py              # read_file, edit_file, write_file, list_directory
│       │   ├── search.py          # search_code (ripgrep wrapper), semantic placeholders
│       │   ├── web.py             # web_search, web_fetch
│       │   └── git.py             # git_status, git_diff, git_log, git_commit
│       ├── rag/
│       │   ├── __init__.py
│       │   ├── chunker.py         # AST-aware chunking (tree-sitter optional, regex fallback)
│       │   ├── indexer.py         # SQLite-backed symbol + chunk index builder
│       │   └── retriever.py       # Hybrid BM25 + optional dense retrieval
│       ├── recovery/
│       │   ├── __init__.py
│       │   ├── detector.py        # Loop detection (exact, semantic, error, stall)
│       │   └── strategies.py      # Recovery actions (intervention, replan, divergence)
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── base.py            # LLMProtocol, StreamChunk, UsageStats
│       │   ├── remote.py          # OpenAI-compatible API client (Claude, GPT-4, local /v1)
│       │   └── local.py           # Ollama native API + MLX subprocess fallback
│       ├── memory/
│       │   ├── __init__.py
│       │   └── store.py           # SQLite cross-session memory (conventions, errors, patterns)
│       └── mcp/
│           ├── __init__.py
│           ├── server.py          # Run agent as MCP server (Zed/Opencode integration)
│           └── client.py          # Connect to external MCP servers for additional tools
├── skills/
│   ├── code-review/
│   │   └── SKILL.md
│   └── debugging/
│       └── SKILL.md
├── AGENTS.md                   # Project instructions for agents
└── README.md
```

## Quick Start

### Installation

```bash
uv sync
```

For RAG with AST-aware chunking:

```bash
uv sync --extra rag
```

For MLX support on Apple Silicon:

```bash
uv sync --extra mlx
```

For all optional dependencies:

```bash
uv sync --all-extras
```

For development:

```bash
uv sync --extra dev
```

### Configuration

Set your API key:

```bash
export OPENAI_API_KEY="sk-..."
```

For web search (optional):

```bash
export BRAVE_API_KEY="..."
```

Or:

```bash
export TAVILY_API_KEY="..."
```

### Usage

Run the agent on a task:

```bash
uv run coding-agent "Add JWT authentication to the login endpoint"
```

With a specific profile:

```bash
uv run coding-agent --profile local_model "Fix the failing test in test_auth.py"
```

With a specific working directory:

```bash
uv run coding-agent --profile large_model --working-dir ./myproject "Refactor the user service"
```

Verbose logging:

```bash
uv run coding-agent -v "Explain the authentication flow"
```

Run as an MCP server (for Zed/Opencode):

```bash
uv run python -m coding_agent.mcp.server --profile local_model
```

## Configuration Profiles

```bash
Profile       Model          Context  Router                Planner
------------- -------------- -------- --------------------- ----------------
large_model   Claude/GPT-4   200k     Hybrid (LLM + rules) Tree-of-thought
local_model   Ollama 7-13B   32k      Rules only           Flat
```

Edit config/base.yaml for shared defaults, or the profile-specific
YAML for overrides.

## Architecture

The agent operates in a ReAct loop:

1. **Plan**: Decompose the task into ordered subtasks
2. **Think**: Reason about the current state and next action
3. **Act**: Select and execute a tool (read, edit, search, run, etc.)
4. **Observe**: Process the tool result
5. **Verify**: Check that the step achieved its goal
6. **Recover**: If stuck in a loop, inject corrective interventions
7. **Repeat** until all subtasks are complete

### Key Design Decisions

- **Token efficiency**: Every tool output is compressed before entering the context window. RAG provides symbol-level access instead of full file reads.
- **Graceful degradation**: Local models use simpler planning, rule-based tool routing, and more aggressive compression.
- **Safety**: Path traversal is blocked, git commits require explicit consent, and all operations are scoped to the working directory.

## Development

```bash
uv sync --extra dev
uv run ruff check src/
uv run ruff format src/
uv run pytest tests/ -v
```

## License

MIT
