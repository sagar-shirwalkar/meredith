# Meredith

[![Python](https://img.shields.io/badge/Python-3.13-fbad2b?style=for-the-badge&label=Python&labelColor=gray&logo=python&logoColor=blue)](https://python.org)
[![GitHub tag check runs](https://img.shields.io/github/check-runs/sagar-shirwalkar/meredith/v0.3.0?style=for-the-badge)](https://github.com/sagar-shirwalkar/meredith/actions)
[![OSSF-Scorecard Score](https://img.shields.io/ossf-scorecard/github.com/sagar-shirwalkar/meredith?style=for-the-badge&label=OSSF%20Scorecard)](https://securityscorecards.dev/viewer/?uri=github.com/sagar-shirwalkar/meredith)
[![AGPL-3.0](https://img.shields.io/badge/License-AGPL%20v3-blue?style=for-the-badge)](LICENSE)

<p align="center">
  <picture>
    <img src="assets/meredith.svg" width="400" height="400" alt="Meredith">
  </picture>
</p>

Meredith is an AI coding agent for software engineering workflows. It operates a **ReAct loop** (Reason → Act → Observe) with strategic planning, three-tier hybrid RAG for codebase understanding, adaptive context compaction to stay within token budgets, and ACP (Agent Client Protocol) integration for native editor support.

- **Remote models** — any OpenAI-compatible API (OpenAI, Anthropic, Together AI, Fireworks, Opencode, Azure OpenAI, etc.)
- **Local models** — Ollama (7–70B) and MLX on Apple Silicon, with optional TurboQuant for KV cache + weight compression

---

## Features

- **ReAct Loop** — Reason, act, and observe in a tight feedback cycle with strategic planning.
- **Three-Tier Hybrid RAG** — BM25 keyword search → dense semantic retrieval (ONNX MiniLM or deterministic numpy) → AST-derived code graph. Cascade short-circuits when confidence thresholds are met; results fused via RRF.
- **Adaptive Context Compaction (ACC)** — 6-stage progressive pipeline: budget reduction, observation masking, fast pruning, aggressive compression, reversible collapse (serialization), and LLM summarization. Stages 1-4 handle 95%+ of cases without invoking the model.
- **Meta-Thinker** — Heuristic loop monitor that evaluates goal progress, context health, and behavioral quality every step. Emits CONTINUE/INTERRUPT/COMPLETED/FALLBACK signals. No LLM call per step — zero latency overhead.
- **ACP Native** — Run as an [Agent Client Protocol](https://agentclientprotocol.com) server for Zed, JetBrains, Neovim, Emacs, and any ACP-aware editor.
- **Smart Context** — 6-zone hierarchical context window with per-zone token budgets, automatic compression, and tier degradation (LARGE → MID → SMALL) when budget runs low.
- **Loop Recovery** — 4-mode loop detection (exact, semantic, error, stall) with meta-thinker-guided corrective strategies.
- **Cross-Session Memory** — Learns project conventions, error patterns, and solutions across sessions via SQLite, with structured CROSSWALK.md session bridging.
- **Checkpoint & Resume** — JSON-serialized agent state saved every N steps; can be loaded across sessions.
- **Multi-Stage Planning** — Hierarchical planner with strategic/tactical layers and phase lifecycle (active → retry → recovery → aborted).
- **TurboQuant** — MLX KV cache + weight quantization for Apple Silicon (configurable bits, sink tokens, layer-adaptive).
- **Skills** — Modular `SKILL.md` files that teach the agent new capabilities on the fly.
- **Triple Profile** — Optimised configurations for large API models (200K), mid-range (64K), and local 7-13B (32K).

---

## Quick Start

**Prerequisites:** Python 3.13+, [uv](https://docs.astral.sh/uv/)

```bash
make setup
```

This installs dependencies, sets up pre-commit hooks, and runs lint. On Apple Silicon it also pulls MLX extras.

Then set your API key and run:

```bash
export LLM_API_KEY="sk-..."           # Required: key for your LLM provider
uv run meredith "Add JWT authentication to the login endpoint"
```

Output (varies by task):
```
✓  Phase 1: Analyze — 3 files identified
✓  Phase 2: Implement — edited src/auth.py, src/middleware.py
✓  Phase 3: Verify — 2 tests pass, lint clean
```

---

## Installation

**Recommended** — via uv:

```bash
git clone https://github.com/sagar-shirwalkar/meredith
cd meredith
make setup
```

<details>
<summary>Manual installation</summary>

```bash
uv sync --extra dev                          # Core + dev deps
uv sync --extra dev --extra mlx              # Apple Silicon: add mlx + mlx-lm
uv run pre-commit install                    # Enable secret-scanning hooks
```
</details>

**Credentials:**

| Variable | Required | Source |
|---|---|---|
| `LLM_API_KEY` | Yes | Your LLM provider's dashboard |
| `BRAVE_API_KEY` | No | [Brave Search API](https://brave.com/search/api/) |
| `TAVILY_API_KEY` | No | [Tavily](https://tavily.com/) |
| `EXA_API_KEY` | No | [Exa](https://exa.ai/) |

---

## Usage

### Execute a task

```bash
uv run meredith "Fix the failing test in tests/test_auth.py"
uv run meredith --profile local_model "Explain the authentication flow"     # Local model
uv run meredith -v "Refactor the database layer"                            # Verbose logging
```

### Start the ACP server (for editor integration)

```bash
uv run python -m coding_agent.acp.server --profile large_model
```

Point your editor at that command. See [Publishing to the ACP Registry](#publishing-to-the-acp-registry) for distribution.

---

## Configuration Profiles

| Profile | Provider | Context | Router | Planner | RAG Depth | Max Steps | Use Case |
|---|---|---|---|---|---|---|---|
| `large_model` | Remote API (OpenAI-compatible) | 200K tokens | Hybrid (LLM + rules) | Tree-of-thought | Full 3-tier | 80 | Complex multi-file tasks |
| `mid_model` | Remote API | 64K tokens | Hybrid (LLM + rules) | Flat | 2-tier (BM25 + dense) | 50 | Moderate tasks, constrained budget |
| `local_model` | Ollama / MLX (7–13B) | 32K tokens | Rules only | Flat | BM25 only | 30 | Simple edits, offline use |

**TurboQuant** (Apple Silicon only): set `turboquant.kv_bits`, `turboquant.weight_bits`, and `turboquant.sink_tokens` in `config/local_model.yaml` to reduce memory usage of local MLX models. Layer-adaptive quantization (`layer_adaptive: true`) assigns more bits to attention layers.

---

## Project Structure

```
meredith/
├── pyproject.toml                    # Package metadata, dependencies, tool config
├── config/
│   ├── base.yaml                     # Shared defaults (token limits, thresholds, paths)
│   ├── large_model.yaml              # Overrides for remote API models (200K tokens)
│   ├── mid_model.yaml                # Overrides for moderate-budget remote models (64K tokens)
│   └── local_model.yaml              # Overrides for local Ollama/MLX models (32K tokens)
├── src/coding_agent/
│   ├── main.py                       # CLI entry point, argument parsing, wiring
│   ├── config.py                     # YAML loading, merging, validation
│   ├── types.py                      # Shared dataclasses, enums, protocols
│   ├── agent/                        # ReAct loop orchestrator
│   │   ├── core.py                   # Main loop, step orchestration (ACC + Meta-Thinker integrated)
│   │   ├── planner.py                # Strategic planner (tree-of-thought / flat)
│   │   └── verifier.py               # Post-step verification
│   ├── context/                      # Context window management
│   │   ├── manager.py                # Hierarchical context builder
│   │   ├── budget.py                 # Token budget tracker
│   │   ├── compressor.py             # Output truncation and compression (legacy)
│   │   └── compactor.py              # 6-stage ACC pipeline (new)
│   ├── tools/                         # Agent tool implementations
│   │   ├── base.py                   # Tool protocol and registry
│   │   ├── router.py                 # LLM-driven + rule-based tool selection
│   │   ├── fs.py                     # File read/edit/write/list
│   │   ├── search.py                 # Code search (ripgrep)
│   │   ├── web.py                    # Web search and fetch
│   │   └── git.py                    # Git operations
│   ├── rag/                          # Retrieval-Augmented Generation
│   │   ├── chunker.py                # AST-aware chunking with edge extraction
│   │   ├── embedder.py               # Dense embedder (numpy_default + ONNX MiniLM)
│   │   ├── graph.py                  # AST CodeGraph with BFS expansion
│   │   ├── indexer.py                # SQLite-backed index (chunks + embeddings + graph edges)
│   │   └── retriever.py              # Three-tier cascade (BM25 → dense+RRF → graph+RRF)
│   ├── recovery/                     # Loop detection and escape
│   │   ├── detector.py               # Pattern detection (exact, semantic, stall)
│   │   ├── strategies.py             # Recovery interventions
│   │   └── meta_thinker.py           # Heuristic loop monitor (new)
│   ├── llm/                          # LLM client abstractions
│   │   ├── base.py                   # LLM protocol and streaming types
│   │   ├── remote.py                 # OpenAI-compatible API client
│   │   └── local.py                  # Ollama + MLX client (with TurboQuant flags)
│   ├── memory/                       # Cross-session memory
│   │   └── store.py                  # SQLite memory store
│   └── acp/                          # Agent Client Protocol server
│       └── server.py                 # ACP stdio server for editor integration
├── scripts/                          # Standalone utility scripts
│   └── compact_checkpoints.py        # Prune old / merge consecutive checkpoints
├── MEMORY.md                         # Cross-session memory architecture & compaction docs
├── CROSSWALK.md                      # Session bridge for cross-session continuity
├── assets/                           # Project icon and branding assets
│   ├── meredith.svg                  # Primary logo (isometric M, dark bg)
│   ├── meredith-favicon.svg          # Favicon crop (no wordmark/decoration)
│   ├── meredith-light.svg            # Light background variant
│   ├── meredith-mono.svg             # Monochrome / print variant
│   ├── meredith-small.svg            # Tight crop for app icon (512×512)
│   └── logo-variants.md              # Variant specs and generation guide
├── tests/                                 # Test suite (224+ tests covering >80% of core modules)
│   ├── __init__.py
│   ├── conftest.py                       # Shared fixtures (config, types, streaming)
│   ├── test_import.py                    # Package import smoke test
│   ├── test_types.py                     # Enums, dataclasses, Plan, ToolSchema
│   ├── test_config.py                    # YAML loading, merging, frozen dataclasses
│   ├── test_llm_base.py                  # Token counting, streaming chunks, tool call parsing
│   ├── test_budget.py                    # TokenBudget zone accounting, estimates
│   ├── test_compressor.py                # Output compression strategies
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
│   ├── test_retriever.py                 # BM25 retriever scoring and retrieval
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

```bash
mkdir -p .agents/skills/react-patterns          # Create skill directory
# Write SKILL.md with instructions, conventions, and examples
# The agent discovers and loads it automatically on next startup
```

Browse community skills at [skills.sh](https://www.skills.sh/).

---

## Architecture

The agent operates in a continuous ReAct loop:

1. **Plan** — Decompose task → ordered subtasks (flat, tree-of-thought, or hierarchical)
2. **Think** — Reason about state and next action
3. **Act** — Execute tool (read, edit, search, run)
4. **Meta-Think** — Heuristic monitor evaluates goal progress, context health, behavioral quality
5. **Observe** — Process tool result
6. **Compact** — ACC pipeline stages tool outputs as context budget tightens (stages 1-6)
7. **Verify** — Check step quality (diagnostics, tests)
8. **Recover** — Detect loops → inject corrective action
9. **Repeat** — Until all subtasks complete

### Adaptive Context Compaction (ACC)

The context window is managed as 6 zones with natually ordered priority. When total tokens exceed the threshold, compaction progresses through stages:

| Stage | Action | Cost | LLM Call |
|---|---|---|---|
| 1. BudgetReduction | Cap tool outputs per-zone | Cheap | No |
| 2. ObservationMasking | Replace old results with reference pointers | Cheap | No |
| 3. FastPruning | Drop low-value (<200 char) outputs | Cheap | No |
| 4. AggressiveCompression | Shrink retention window | Medium | No |
| 5. ReversibleCollapse | Serialize and byte-shrink | Medium | No |
| 6. FullLLMSummarization | LLM-compress remaining content | Expensive | Yes |

Stages 1-4 handle 95%+ of compaction needs without invoking the model. Stage 5 is fully reversible (deserialization restores exact state). Stage 6 is async and used only when all cheaper stages are exhausted.

### Three-Tier Hybrid RAG

Retrieval uses a cascade architecture inspired by ZoomRAG and VelociRAG:

```
Query → BM25 (Tier 1) → confidence ≥ threshold? → Dense + RRF (Tier 2) → confidence ≥ threshold? → Graph + RRF (Tier 3) → Results
```

- **Tier 1 (BM25)** — Fast keyword search over AST-chunked code. Always on, no dependencies.
- **Tier 2 (Dense)** — Semantic similarity via numpy_random (zero deps, deterministic) or ONNX MiniLM. Fused with BM25 results via Reciprocal Rank Fusion (RRF).
- **Tier 3 (Graph)** — AST-derived knowledge graph (CALLS, IMPORTS, INHERITS, CONTAINS edges). BFS expansion from seed vector hits. Captures structural relationships BM25 and dense similarity miss.
- **Adaptive-k** — Adjusts top-k dynamically based on similarity distribution.

Each tier runs only if the previous tier's confidence is below threshold. This minimises cost while ensuring thorough retrieval for ambiguous or structural queries.

### Meta-Thinker

A lightweight heuristic monitor runs after every step, evaluating:

- **Goal progress** — Is the agent moving toward the stated goal?
- **Context health** — Is the context window degrading (budget pressure, stale observations)?
- **Behavioral quality** — Is the agent repeating actions, oscillating, or stuck?

Emits one of four signals: `CONTINUE` (normal), `INTERRUPT` (deviating — inject system message), `COMPLETED` (goal satisfied — terminate early), `FALLBACK` (degraded — switch to simpler strategy). All signals are heuristic-derived; no LLM call is made.

### Key design decisions

- **Token efficiency** — Every tool output is compressed before entering the context window. RAG provides symbol-level access instead of full file reads.
- **Cheaper-first compaction** — ACC runs the cheapest effective stage first, not the most thorough. The model is only invoked for compaction when all other options are exhausted.
- **Cascade, not ensemble** — The three RAG tiers cascade with confidence gating rather than always running in parallel. Cheaper tiers satisfy most queries.
- **Graceful degradation** — Local models use simpler planning, rule-based tool routing, and BM25-only RAG.
- **Safety** — Path traversal is blocked, git commits require explicit consent, and all operations are scoped to the working directory.

---

## Capabilities Deep Dive

### Hierarchical Planning

Meredith supports three planner modes, selectable per config profile:

| Planner | Strategy | When Used |
|---|---|---|
| **Flat** | Linear subtask decomposition | Simple edits, local models, budget-constrained runs |
| **Tree-of-Thought** | Multi-branch exploration with scoring | Complex multi-file tasks via `large_model` |
| **Hierarchical** | Two-phase (strategic plan → tactical phases) | Mid-budget runs where structure matters more than branching |

The hierarchical planner decomposes goals into phases with lifecycle tracking (`PENDING → ACTIVE → COMPLETED | FAILED → RETRY | ABORTED`). Phases that fail get automatic replan with failure context injected. The phase index persists to checkpoints, so interrupted sessions resume at the right phase.

### Runtime Tiers

When context budget runs critically low, the agent degrades automatically rather than crashing:

1. **LARGE** (default) — Full model config, 200K context, tree-of-thought planner, hybrid router, full 3-tier RAG
2. **MID** at ≤10% budget — 64K effective context, flat planner, hybrid router, 2-tier RAG, constrained step budget
3. **SMALL** at ≤5% budget — 32K effective context, flat planner, rules-only router, BM25-only RAG, minimal step budget

Tier transitions inject a constraint message into the agent's system prompt so it adapts its behavior. The `_apply_tier()` method adjusts step budget, planner selection, RAG depth, and router strategy without touching the frozen config.

### TurboQuant (Apple Silicon)

For local MLX models, TurboQuant reduces memory usage via:

- **KV cache quantization** — `turboquant.kv_bits` (default: 8) reduces the memory footprint of the key-value cache
- **Weight quantization** — `turboquant.weight_bits` (default: 4) compresses model weights
- **Sink attention** — `turboquant.sink_tokens` (default: 4) reserves tokens with full precision for attention sinks
- **Layer-adaptive** — `turboquant.layer_adaptive: true` assigns more bits to attention layers, fewer to FFN layers

Configure in `config/local_model.yaml`. Requires an MLX fork with TurboQuant support — see `TURBOQUANT.md` reference for compatible forks.

### Checkpoint & Resume

Agent state is checkpointed to `.agent/checkpoints/{session_id}.json` after every N steps (default 5). Each checkpoint contains:

- All completed steps (thought + tool call + result + verification)
- Current plan (active phase, remaining subtasks)
- Files modified set
- Token usage statistics

The `compact_checkpoints.py` script prunes abandoned sessions (<5 steps) and merges consecutive entries, keeping the checkpoint directory lean. Sessions can be resumed by passing `--session <id>` to the CLI.

### Cross-Session Memory

The SQLite-backed memory store (`.agent/memory.db`) persists three memory types:

- **Procedural** — Project conventions, build commands, testing patterns
- **Episodic** — Past errors, solutions, and debugging narratives
- **Semantic** — Facts about the codebase learned across sessions

Memories are deduplicated by content hash and pruned by recency (default: keep 200). Sensitive data (emails, API keys, SSH keys) is excluded during save via regex filtering.

**Session bridging:** `CROSSWALK.md` at project root provides structured forward-directed handoff between sessions — read at session start, written at boundaries, archived when too large.

### Phase Lifecycle

The hierarchical planner tracks work as phases through a lifecycle:

```
PENDING → ACTIVE → COMPLETED
                  → FAILED → RETRY (with failure context)
                          → ABORTED (after max retries)
```

Each phase encapsulates its own flat plan of subtasks. When a phase fails mid-execution, the planner injects the failure context into the tactical LLM call and replans only the remaining phases, keeping already-completed work intact.

---

## Roadmap

### Near-term

- **ACC stage 6 integration** — Wire async LLM summarization into the compaction pipeline (currently logs a warning with pass-through)
- **Tests for new components** — Unit tests for compactor, embedder, graph retriever, meta-thinker, and three-tier cascade
- **RAG cascade tuning** — Benchmark and set optimal confidence thresholds and RRF k values
- **Dense retriever re-index** — Auto-detect and re-index embeddings for existing databases on startup
- **Meta-Thinker telemetry** — Surface INTERRUPT/FALLBACK signals in logs and session summaries

### Medium-term

- **LLM-assisted checkpoint summarization** — Use the mid-tier model to write human-readable summaries of completed phases
- **Phase dependency graph** — Allow phases to declare dependencies and run in topological order (or parallel where independent)
- **Planner ensemble** — Run flat + hierarchical planners in parallel and pick the best plan by LLM scoring
- **Multi-session memory indexing** — Cross-reference episodic memories from different sessions to detect recurring failure patterns
- **Web-based checkpoint viewer** — Visual timeline of agent actions across sessions

### Future

- **Autonomous tool discovery** — Agent explores new codebases and builds its own toolchain selections
- **Multi-agent orchestration** — Decompose tasks across specialized sub-agents with a coordinating planner
- **Self-hosted ACP relay** — Run the ACP server with WebSocket transport for remote editor integration

---

## Publishing to the ACP Registry

### Zed ACP Registry

The [ACP Registry](https://agentclientprotocol.com/registry) is a curated directory of ACP-compatible agents. To publish meredith:

1. **Fork the registry** at [github.com/agentclientprotocol/registry](https://github.com/agentclientprotocol/registry).
2. **Add your agent definition** to `agents/` (follow the existing entries as a template):

```yaml
# agents/meredith.yml
name: meredith
description: AI coding agent with three-tier RAG, adaptive context compaction, and loop recovery
command: uv
args:
  - run
  - python
  - -m
  - coding_agent.acp.server
  - --profile
  - large_model
version: 0.3.0
```

3. **Add an icon** — use the icon at [`assets/meredith.svg`](assets/meredith.svg).
4. **Open a pull request** to the registry repository.

The registry supports authentication methods, version tracking, and links to source. See the [registry documentation](https://github.com/agentclientprotocol/registry) for full details.

### Opencode ACP Registry

Opencode also maintains an ACP registry. Follow their submission guidelines with the same `uv run python -m coding_agent.acp.server` command.

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
git tag v0.3.0
git push origin v0.3.0
# Create a GitHub Release from the tag; CI publishes to PyPI.
```

Requires a `PYPI_TOKEN` secret in your GitHub repository settings.

---

## Development

`make setup` is the one-shot command — it installs dependencies, pre-commit hooks, and runs lint. No manual `uv sync` needed.

```bash
make setup           # First time: install deps, hooks, and lint
make lint            # Ruff check
make test            # Pytest (all 224+ tests)
make check           # lint + typecheck + test (CI equivalent)
make clean           # Remove caches and build artifacts
```

---

## License

[AGPL-3.0](LICENSE)
