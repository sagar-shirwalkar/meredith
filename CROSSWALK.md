# CROSSWALK.md — Session Bridge

## Active Work
- **Current phase**: Phase 3 (Blueprint) + Phase 4 (Adapt) complete — 4 of 6 targets implemented.
- **Completed**: Hierarchical planner enabled (P3), non-tool graceful degradation (P1), ACC thresholds for 32K (P4), TurboQuant enabled by default.
- **Remaining**: Stage 5/6 rehydration wiring (P2), tool preference auto-save (P5).
- **Uncommitted changes**: `text_mode_parser.py`, config changes, handoff docs.

## Session History (Last 4)
- **[2026-07-02] Phase 2 (Analyze) complete — all 6 agentic-improvement targets assessed and documented**:
  - Loaded context from handoff doc at `.agent/handoff/2026-07-02-agentic-review-handoff.md`, MEMORY.md, CROSSWALK.md
  - Verified all 6 gaps against actual source code by reading `agent/core.py`, `context/compactor.py`, `tools/preferences.py`, `tools/router.py`, `tools/base.py`, `config.py`, `config/*.yaml`, `agent/planner.py`, `llm/local.py`, `tests/` structure
  - Confirmed: Non-tool graceful degradation (P1), Stage 5/6 rehydration (P2), Hierarchical planner unused (P3), ACC threshold tuning for 32K (P4), Tool preference auto-save (P5), and noted TurboQuant disabled-by-default as an enhancement
  - Wrote comprehensive Phase 2 analysis at `.agents/skills/agentic-improvements/references/ANALYSIS_FINDINGS.md` with impact analysis, dependency mapping, codebase characterization, risk catalog, and separate priority matrices for small-local vs large-remote models
  - Key finding: All 6 targets are independent — no ordering constraints
  - Produced handoff doc at `.agent/handoff/2026-07-02-phase2-analysis-handoff.md`
- **[2026-07-02] Previous session — Analysis of all 6 agentic-improvement items**:
  - Traced TurboQuant wiring end-to-end: ✅ functional via MLX subprocess
  - Verified auto-detect tool capability: ✅ functional, but non-tool fallback is **broken** (agent exits instead of operating text-only)
  - Confirmed stage 6 caller wiring: ⚠️ partial — rehydration APIs exist but never called
  - Confirmed TreeOfThought planner: ✅ functional
  - Confirmed concurrent verification: ✅ functional
  - Confirmed tool learned preferences: ✅ needs auto-save wiring
  - Discovered: HierarchicalPlanner exists but **no config profile uses it**
  - Updated handoff doc, README caveats, agentic-improvements skill docs
- [2026-07-02] Previous session — Onboarded user's local Ollama setup:
  - Fixed 4 bugs blocking local model usage (see below)
  - Discovered and fixed `run_command` missing executor (real latent bug)
  - Built `scripts/test_tool_calling.py` — validates 14 tools against any Ollama model
  - Updated README with Local Model Guide, tool list, test harness docs
  - Updated AGENTS.md with new structure
- [2026-06-28] Research round 1+2: COMPASS, TurboQuant, AdaCache, ACC, lightweight RAG, graph RAG, Claude Code architecture; created 4 reference .md files; updated skill files; created CROSSWALK.md
- [2026-06-28] Implementation: ACC compactor, Three-Tier RAG (embedder/graph/retriever/indexer), Meta-Thinker, TurboQuant config; all 224 tests pass, lint clean, mypy clean

## Bugs Fixed Previous Session

### 1. Planner: `KeyError: '\n "goal"'` in planner prompt
- **Root cause**: `_FLAT_PLANNER_PROMPT` in `src/coding_agent/agent/planner.py` contained bare `{`/`}` in the JSON example template. Python's `str.format()` interpreted them as replacement fields.
- **Fix**: Escaped all literal braces to `{{`/`}}` (matching the already-correct `_STRATEGIC_PROMPT`)
- **File**: `src/coding_agent/agent/planner.py` lines 39-49

### 2. Model not found: `404` from Ollama `/api/chat`
- **Root cause**: Model `qwen3-coder:14b` in `config/local_model.yaml` was not installed in the user's Ollama
- **Fix**: Switched to an installed model
- **Lesson**: Older Ollama (pre-0.3) doesn't auto-pull. Check `ollama list` before configuring.

### 3. Model too small: `400` from Ollama — "does not support tools"
- **Root cause**: `gemma3:270m-it-q8_0` (270M params) doesn't support Ollama's `tool_calls`
- **Fix**: Switched to `qwen3.5:9b-mlx` (9B, tool-capable)
- **Lesson**: Models <1B almost never support tool calling. Always verify with `scripts/test_tool_calling.py`.

### 4. Missing executor: `run_command` registered nowhere
- **Root cause**: Schema existed but no `ToolExecutor` subclass registered it
- **Fix**: Created `src/coding_agent/tools/shell.py` with `ShellTools` executor
- **File**: `src/coding_agent/tools/shell.py` (new)

### 5. Missing final response output (minor)
- **Fix**: Added `final_response` property to `AgentCore`

### 6. httpx shutdown race (cosmetic)
- **Fix**: Replaced `async with` with `build_request()` + `send(stream=True)` in `_ollama_stream()`

## Deep-Dive: 6-Item Workplan Status (This Session)

| Item | Code Exists? | Wired? | Tested? | Notes |
|------|-------------|--------|---------|-------|
| TurboQuant wiring | ✅ `TurboQuantConfig`, MLX flags | ✅ `_start_mlx()` passes flags | ⚠️ Unit | Only fires for MLX backend (not Ollama) |
| Auto-detect tool capability | ✅ `check_tool_support()` | ✅ Agent core startup | ❌ E2E | Non-tool fallback broken — agent exits |
| Stage 6 caller | ✅ APIs, caller, summarizer | ⚠️ Rehydration never wired | ❌ E2E | `prepare_rehydration`/`restore_rehydration` uncalled |
| TreeOfThought Planner | ✅ `TreeOfThoughtPlanner` | ✅ `planner_type` config | ✅ Unit | Parallel branch eval works |
| Concurrent Verification | ✅ Background task | ✅ Loop integration | ✅ Unit | Replan chaining not connected |
| Tool Learned Preferences | ✅ `ToolPreferences` | ✅ Router ranking + recording | ✅ Unit | Never auto-saved mid-session |

## New Findings

### Gaps discovered during review

| Gap | File(s) | Impact | Fix |
|-----|---------|--------|-----|
| Non-tool graceful degradation | `agent/core.py` | Agent does zero work when model lacks tool support | ~50 lines: text-mode parser |
| Stage 5/6 rehydration wiring | `agent/core.py` + `context/compactor.py` | Plan state lost after deep compaction | ~15 lines: 2 calls in run loop |
| Hierarchical planner unused | `config/large_model.yaml` | Strategic planning never activated | 1-line config change |
| ACC thresholds at 32K | `config/local_model.yaml` | Compaction fires too late for local models | ~5 lines YAML thresholds |
| Preference store auto-save | `agent/core.py` + `tools/preferences.py` | Learned preferences lost on crash | ~10 lines periodic save |

### Verified working correctly
- TurboQuant: `TurboQuantConfig` → `LocalLLMClient.__init__` → `_start_mlx()` with `--kv-bits/--weight-bits/--sink-tokens/--layer-adaptive`
- Auto-detect: Probe uses `/api/chat` with minimal tool schema → catches 400/"does not support tools"
- ACC stage 6: `_llm_summarize()` method exists, `stage_full_llm()` async wrapper works, two-phase CoT prompt in place
- ToT planner: 3-branch parallel generation with scoring function (subtask count + dependency coverage + files specified)
- Concurrent verifier: Background task created per step, result collected next loop iteration
- Learned preferences: Recorded every step, weights computed from rolling 20-entry window

## Key Decisions (This Session)
- **Gaps documented as findings, not bugs** — all 6 items have code, they're missing integration wiring
- **Priority ordering**: Non-tool graceful degradation first (unlocks models without tool support), then rehydration wiring (prevents silent data loss), then hierarchical planner (config change)
- **ACC thresholds need profile-specific values** — don't move global defaults; override in `local_model.yaml`
- **Handoff doc placed at `.agent/handoff/`** — gitignored, structured for automated reads

## Open Questions
- **Non-tool mode scope**: Should text-mode parser cover all 14 tools, or a common subset (read/edit/write/search/run)?
- **Cache awareness for ACC**: Current compaction is budget-driven only. Could be smarter by checking whether the prompt cache is hot (Claude Code pattern) — but that's provider-specific.
- **Concurrent verifier → replan**: Should failed concurrent verification auto-trigger planner.replan()? Currently it just injects a warning message.

## Next Actions
1. Implement text-mode parser for non-tool graceful degradation
2. Wire stage 5/6 rehydration in agent core run loop
3. Enable hierarchical planner via `large_model.yaml` config change
4. Tune ACC thresholds for local model 32K profile
5. Wire periodic ToolPreferences.save()
