# Phase 2 Analysis — Meredith Agentic Improvements (2026-07-02)

> **Deliverable for the agentic-improvements skill, Phase 2 (Analyze).**
> This report catalogs the full dependency graph, codebase characterization, and risk profile for the 6 remaining improvement targets. Every subsequent change (Phases 3-6) traces back to this analysis.

---

## 1. Dependency Map

### Module Dependency Graph

```
AgentCore (agent/core.py)
 ├── Planner (agent/planner.py)               ← FlatPlanner / TreeOfThoughtPlanner / HierarchicalPlanner
 ├── Verifier (agent/verifier.py)             ← Rule-based + concurrent (asyncio.create_task)
 ├── ContextManager (context/manager.py)      ← 6-zone context window with zone priorities
 ├── ContextCompactor (context/compactor.py)   ← 6-stage ACC pipeline + rehydration APIs
 ├── ToolRegistry (tools/base.py)             ← Schema definitions + executor discovery
 │    ├── FsTools (tools/fs.py)
 │    ├── SearchTools (tools/search.py)
 │    ├── ShellTools (tools/shell.py)         ← New (prior session fix)
 │    ├── WebTools (tools/web.py)
 │    └── GitTools (tools/git.py)
 ├── ToolRouter (tools/router.py)             ← hybrid | rules_only | llm_only + learned preferences
 │    └── ToolPreferences (tools/preferences.py) ← Per-tool + per-category success tracking
 ├── Retriever (rag/retriever.py)             ← 3-tier cascade (BM25 → Dense → Graph)
 │    ├── Embedder (rag/embedder.py)          ← ONNX MiniLM or numpy_random
 │    ├── Indexer (rag/indexer.py)            ← SQLite-based chunk index
 │    └── GraphEngine (rag/graph.py)          ← AST-derived knowledge graph
 ├── MemoryStore (memory/store.py)            ← SQLite procedural/episodic/semantic
 ├── LoopDetector + LoopRecovery (recovery/)  ← Pattern matching + meta-thinker
 ├── MetaThinker (recovery/meta_thinker.py)   ← Heuristic monitor (no LLM dep)
 └── LLMClient (llm/)
      ├── RemoteLLMClient (llm/remote.py)     ← OpenAI-compatible API
      └── LocalLLMClient (llm/local.py)       ← Ollama + MLX subprocess + TurboQuant
```

### Config Profile Override Chain

```
base.yaml (defaults: 128K ctx, ToT planner, hybrid router, top_k=10)
  ├── large_model.yaml (200K ctx, ToT planner, hybrid router, top_k=15, verifier_concurrent: true)
  ├── local_model.yaml (32K ctx, flat planner, rules_only router, top_k=5, TurboQuant options)
  └── mid_model.yaml (64K ctx, flat planner, hybrid router, top_k=8)
```

### External API Surfaces

| Surface | Transport | Used By |
|---------|-----------|---------|
| OpenAI-compatible `/v1/chat/completions` | HTTP (httpx) | RemoteLLMClient + MLX server |
| Ollama `/api/chat` | HTTP (httpx) | LocalLLMClient (Ollama backend) |
| Ollama `/api/tags` | HTTP (httpx) | `_ollama_is_alive()` probe |
| MLX subprocess `mlx_lm.server` | subprocess (stdio→HTTP) | LocalLLMClient (MLX backend) |
| Brave Search API | HTTP (httpx) | WebTools (optional) |
| Tavily Search API | HTTP (httpx) | WebTools (optional) |

---

## 2. Codebase Characterization

### Size Profile

| Metric | Value |
|--------|-------|
| Total LOC (`src/coding_agent/`) | ~11,900 |
| Total LOC (`tests/`) | ~2,700 |
| Total tests | 264 (all passing) |
| Test runtime | ~0.33s |
| Source modules | 22 |
| Modules with dedicated tests | 5 (budget, compactor, compressor, detector, embedder, graph, meta_thinker, planner, router, strategies, verifier) |

### Module Hotspots (by LOC)

| Module | LOC | Risk Factor |
|--------|-----|-------------|
| `agent/core.py` | 812 | **Highest** — central orchestration, 5/6 gaps touch this file |
| `types.py` | 662 | All data types, changes cascade broadly |
| `rag/indexer.py` | 601 | Complex AST chunking logic |
| `rag/retriever.py` | 600 | 3-tier retrieval cascade |
| `agent/planner.py` | 600 | 3 planner implementations |
| `llm/local.py` | 598 | Dual backend + TurboQuant |

### Test Coverage Gaps

**Modules without dedicated tests** (17 of 22 source modules):

- `agent/core.py` — No tests at all. **Highest risk.**
- `tools/fs.py`, `tools/search.py`, `tools/git.py`, `tools/shell.py`, `tools/web.py`, `tools/base.py` — No unit tests.
- `tools/preferences.py` — No unit tests (used by router tests but not directly tested).
- `llm/remote.py`, `llm/local.py` — No unit tests (require API endpoints).
- `rag/retriever.py` — No standalone tests (tested via integration).
- `memory/store.py` — No unit tests.
- `config.py` — No direct tests (tested indirectly).
- `agents/runner.py`, `main.py` — No tests.

### Convention Consistency

- All files use `from __future__ import annotations` ✅
- All functions and classes have docstrings ✅
- Type hints are comprehensive ✅
- Import ordering follows consistent pattern ✅
- One lint issue: unused `import os` in `agent/core.py` line 3

---

## 3. Impact Analysis — Per Target

### 3a. Small/Local Model Targets

#### Target L1: Non-tool graceful degradation (P1 — Critical)

| Dimension | Detail |
|-----------|--------|
| **What** | When `check_tool_support()` returns False, agent does zero work |
| **Root cause** | `_execute_step()` line 592: `if not tool_calls: return None`; main loop line 411-414 treats None as "done" |
| **Files affected** | `agent/core.py` lines 526-593 (existing), + new file `tools/text_mode_parser.py` (~50 lines) |
| **Imports affected** | `agent/core.py` will import from new module |
| **Config affected** | None — text mode parser is always-on fallback |
| **Tests affected** | Core loop behavior changes when `_tools_enabled=False` |
| **Effort** | ~50 lines new code + ~5 lines wiring in core.py |
| **Payoff** | **Unlocks 0.5B-7B models** that don't support tool calling — expands local model range dramatically |
| **Risk** | Low — new code path only activates when tools are disabled; existing behavior unchanged |

#### Target L2: ACC threshold tuning for 32K (P4 — Low)

| Dimension | Detail |
|-----------|--------|
| **What** | Compaction thresholds tuned for 200K context; at 32K, stage6 fires at 1280 tokens |
| **Root cause** | `config/base.yaml` has no `compaction:` section; `CompressionConfig` defaults assume 200K |
| **Files affected** | `config/local_model.yaml` only |
| **Config keys** | `context.compaction.stage1_budget_reduction` through `stage6_full_llm` |
| **Tests affected** | None (config change only) |
| **Effort** | ~5 lines of YAML |
| **Payoff** | ACC pipeline works correctly for local model context limits |
| **Risk** | Very low — config-only change with no code impact |

#### Target L3: TurboQuant enabled by default (Mid — Enhancement)

| Dimension | Detail |
|-----------|--------|
| **What** | `turboquant.enabled: false` in `local_model.yaml`; user must enable manually |
| **Files affected** | `config/local_model.yaml` line 20 |
| **Effort** | 1 line YAML change |
| **Payoff** | Instantly enables KV cache + weight compression for MLX users |
| **Risk** | Low — only affects MLX backend path; harmless if MLX not installed |
| **Caveat** | Should document requirement of TurboQuant-patched `mlx-lm` |

### 3b. Large/Remote Model Targets

#### Target L4: Hierarchical planner enablement (P3 — Medium)

| Dimension | Detail |
|-----------|--------|
| **What** | `HierarchicalPlanner` class exists and is wired but no profile uses it |
| **Root cause** | `large_model.yaml` line 16: `planner_type: "tree_of_thought"` instead of `"hierarchical"` |
| **Files affected** | `config/large_model.yaml` line 16 only |
| **Config keys** | `agent.planner_type` |
| **Tests affected** | None (test coverage for HierarchicalPlanner exists in `test_planner.py`) |
| **Effort** | 1-line YAML change |
| **Payoff** | Unlocks strategic/tactical 2-phase planning for large models — 3-7 phases with per-phase replanning |
| **Risk** | Very low — HierarchicalPlanner has test coverage, builds on existing Plan types |

#### Target L5: Stage 5/6 rehydration wiring (P2 — High)

| Dimension | Detail |
|-----------|--------|
| **What** | `prepare_rehydration()` / `restore_rehydration()` exist with tests but are never called |
| **Root cause** | `AgentCore.run()` lines 397-407 calls `compactor.compact()` but never prep/restore |
| **Files affected** | `agent/core.py` lines 397-407 (2 insertion points) |
| **Imports affected** | None (rehydration APIs already available via `self._compactor`) |
| **Tests affected** | Core loop behavior change near compaction; test_compactor already covers the APIs |
| **Effort** | ~15 lines in `AgentCore.run()` |
| **Payoff** | Prevents silent data loss after deep compaction — plan state, modified files, skills context survive |
| **Risk** | Very low — APIs are tested; core loop change is additive |

#### Target L6: Tool preference auto-save (P5 — Low)

| Dimension | Detail |
|-----------|--------|
| **What** | `ToolPreferences.save()` only called by `reset()`, never by agent core |
| **Root cause** | `agent/core.py` line 619-624 records results but never calls `save()` |
| **Files affected** | `agent/core.py` + `tools/preferences.py` (optional: add counter to save trigger) |
| **Config keys** | `tools.router.learned_preferences` (already exists) |
| **Tests affected** | None (additive change) |
| **Effort** | ~10 lines: counter in core.py, periodic save every N steps |
| **Payoff** | Learned preferences persisted across crashes; warm-start from previous sessions |
| **Risk** | Low — save() uses atomic write (temp file + rename); IO is non-blocking |

---

## 4. Risk Catalog

### Immediate Risks (Blockers)

| Risk | Severity | Detail |
|------|----------|--------|
| Non-tool graceful degradation breakage | **Critical** | Agent with tools-unsupported model does zero work. No error message, no fallback. |
| Rehydration data loss | **High** | After stages 5-6 compaction, all plan state, file lists, and skills context are silently lost. |

### Architectural Risks

| Risk | Severity | Detail |
|------|----------|--------|
| `agent/core.py` churn concentration | **Medium** | Largest file (812L) is also the most frequently modified. 5/6 gaps touch it. Each change risks regression. |
| No tests for core.py | **Medium** | The most critical file has zero dedicated tests. All gap fixes lack safety net. |
| `CompressionConfig` defaults vs. profile gap | **Low** | Defaults embedded in Python class, not sourced from base.yaml. Profile YAML overrides work correctly now, but the dual-source pattern could cause confusion. |

### Technical Debt

| Item | Impact |
|------|--------|
| `HierarchicalPlanner` built, tested, wired, but never activated | Strategic planning unavailable for no good reason |
| ACC rehydration APIs complete for 2+ cycles but never connected | Engineering effort already sunk; missing 15 lines |
| `ToolPreferences.save()` has atomic write support but is never called | Persistence mechanism exists but unused |
| Unused `import os` in `agent/core.py` line 3 | Lint fix: one line deletion |

---

## 5. Priority Matrix — Small Local vs. Large Remote

### Small/Local Models (config/local_model.yaml — 32K ctx, <9B params)

| Target | Priority | Effort | Risk | Payoff | Impact |
|--------|----------|--------|------|--------|--------|
| **L1: Non-tool graceful degradation** | P1 | ~55 lines | Low | **Enables all models <1B-7B** | Expands usable model range 5x |
| **L2: ACC threshold tuning for 32K** | P4 | ~5 lines YAML | Very Low | Makes ACC work at local scales | Quality-of-life for compaction |
| **L3: Enable TurboQuant by default** | Enhancement | 1 line YAML | Very Low | Memory savings for MLX users | ~2x context on same hardware |

### Large/Remote Models (config/large_model.yaml — 200K ctx, frontier models)

| Target | Priority | Effort | Risk | Payoff | Impact |
|--------|----------|--------|------|--------|--------|
| **L4: Hierarchical planner enablement** | P3 | 1 line YAML | Very Low | Strategic planning unlocks complex tasks | Biggest one-line win in the project |
| **L5: Stage 5/6 rehydration wiring** | P2 | ~15 lines | Very Low | Prevents silent data loss | Safety net for deep compaction |
| **L6: Tool preference auto-save** | P5 | ~10 lines | Low | Persistence across sessions/crashes | Reliability improvement |

### Combined View (Highest payoff first)

| Rank | Target | Lines | Model Tier | Risk | Why Now |
|------|--------|-------|------------|------|---------|
| **1** | Non-tool graceful degradation | ~55 | Local | Low | Unblocks all small models; core experience fix |
| **2** | Stage 5/6 rehydration | ~15 | Both | Very Low | Prevents silent data loss; APIs are ready |
| **3** | Hierarchical planner enablement | 1 | Large | Very Low | One-line change for strategic planning |
| **4** | ACC threshold tuning for 32K | ~5 | Local | Very Low | Makes compaction effective at local scale |
| **5** | Tool preference auto-save | ~10 | Both | Low | Gradual reliability improvement |
| **6** | Enable TurboQuant by default | 1 | Local | Very Low | Free memory improvement for MLX users |

---

## 6. Key Dependencies for Implementation

### Implementation Order Dependencies

```
1. Non-tool graceful degradation (no deps)
     ├── Creates: tools/text_mode_parser.py
     └── Modifies: agent/core.py

2. Stage 5/6 rehydration wiring (no deps)
     └── Modifies: agent/core.py (different section — no conflict with #1)

3. Hierarchical planner enablement (no deps)
     └── Modifies: config/large_model.yaml

4. ACC threshold tuning (no deps)
     └── Modifies: config/local_model.yaml

5. Tool preference auto-save (no deps)
     └── Modifies: agent/core.py + tools/preferences.py

6. Enable TurboQuant by default (no deps)
     └── Modifies: config/local_model.yaml
```

**All 6 targets are independent** — no ordering constraints. They can be implemented in any sequence, or in parallel.

---

## 7. Verification Plan

| Target | Verification |
|--------|-------------|
| Non-tool graceful degradation | Run with `_tools_enabled=False` forced; verify agent executes read_file/write_file/edit_file via text commands |
| Stage 5/6 rehydration | Mock compactor with empty messages; verify plan state + files appear in post-compaction context |
| Hierarchical planner | Load large_model.yaml; verify `self._planner` is `HierarchicalPlanner` instance |
| ACC thresholds at 32K | Verify `CompressionConfig` values from local_model.yaml overrides |
| Tool preference auto-save | Set learned_preferences=true; run 5+ steps; verify `.agent/tool_preferences.json` exists with data |
| TurboQuant | Verify `--kv-bits` flag in MLX subprocess args when `turboquant.enabled: true` |
