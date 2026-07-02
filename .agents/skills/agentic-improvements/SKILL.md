---
name: agentic-improvements
description: Upgrade agent architecture with 2025-2026 innovations — analyze, meta-planning, context lifecycle, adaptive caching, graceful degradation, and MEMORY.md patterns.
disable-model-invocation: true
---

# Agentic Improvements

Upgrade this agent system with the latest proven patterns from the 2025-2026 agent literature: impact analysis, multi-stage planning, context lifecycle management, adaptive caching, graceful degradation, and Anthropic-style memory architecture.

**Given:** a running agent codebase with config YAML, tool executors, and LLM integration.
**Produces:** a phased upgrade plan, config changes, and structural improvements.

## Key Principles

### 1. Multi-Stage Planning (Blueprint)

Replace single-shot planning with a hierarchy of plan abstractions. Inspired by TodoEvolve (2026), ReAcTree (2025), and AdaPlan-H (2025):

- **Strategic layer** — high-level goal decomposition (3-7 phases)
- **Tactical layer** — per-phase step sequencing with tool selection
- **Execution layer** — individual tool calls with observation handling
- Each layer re-plans independently when its preconditions change; lower layers re-plan more frequently.

### 2. Context Lifecycle Management (Crosswalk)

A context window has natural phases that must be managed explicitly. Inspired by COMPASS (ACL 2026):

- **Immutable zone** — system prompt, tool schemas (always present, never evicted)
- **Task zone** — current objective and subtask description
- **Working zone** — recent tool call/result pairs (sliding window, compressed oldest entries)
- **Episodic zone** — summarised step history from compressed working entries
- **Semantic zone** — project conventions, AGENTS.md, cross-session memories
- **Scratch zone** — agent's own notes and meta-thinker interventions

Use zone-based compaction: when total tokens exceed threshold, compress the lowest-priority zone first.

### 3. Adaptive Caching (Distill)

Not all retrieval needs full depth. Inspired by AdaCache (ICLR 2026):

- **Confidence-based depth** — when the agent is confident in its path, use shallow/fast retrieval; when uncertain, deepen retrieval
- **Tiered cache** — L1: in-memory recent results (TTL 30s), L2: session-level compressed summaries, L3: persistent RAG index
- **Cache warming** — pre-fetch likely-next chunks based on plan phase

### 4. Graceful Degradation

This codebase already supports model profiles (`config/base.yaml`, `config/large_model.yaml`, `config/local_model.yaml`). Extend the pattern:

<table>
<tr><th>Dimension</th><th>Large Model</th><th>Small/Local Model</th></tr>
<tr><td>Planner</td><td>tree_of_thought</td><td>flat / rule-based</td></tr>
<tr><td>Context</td><td>128K-200K tokens</td><td>8K-32K tokens</td></tr>
<tr><td>Router</td><td>hybrid (LLM + rules)</td><td>rules_only</td></tr>
<tr><td>RAG top_k</td><td>10-15</td><td>3-5</td></tr>
<tr><td>Max steps</td><td>50-80</td><td>20-30</td></tr>
<tr><td>Concurrent verifier</td><td>yes</td><td>no</td></tr>
<tr><td>Verification</td><td>self-critique + structured eval</td><td>structured eval only</td></tr>
</table>

### 5. Cross-Session Memory (Crosswalk)

Adopt the Anthropic MEMORY.md tripartite architecture:

- **Procedural memory** — always loaded: AGENTS.md, config conventions, tool definitions
- **Episodic memory** — temporal retrieval: recent sessions, checkpoint summaries (keyed by timestamp)
- **Semantic memory** — similarity retrieval: learned patterns, project conventions, recurring solutions

## Leading Words

These words surface the right strategy at the right moment:

| Word | Phase | Purpose |
|------|-------|---------|
| **Analyze** | Analyze | Impact analysis, dependency mapping, codebase characterization before committing to a plan |
| **Blueprint** | Blueprint | Meta-planning, architecture design, capability roadmap |
| **Distill** | Adapt | Graceful degradation, compression, simplification for resource constraints |
| **Crosswalk** | Crosswalk | Memory management, cross-session continuity, checkpoint recovery |
| **Compact** | Distill | Staged context compaction — progressive reduction from cheap masking through LLM summarization |
| **Fuse** | Crosswalk | Three-tier hybrid retrieval fusion (BM25 + dense + graph) with RRF combining |
| **Zoom** | Blueprint | Coarse-to-fine hierarchical search — graph zoom for structural code queries |
| **Bridge** | Crosswalk | CROSSWALK.md session bridging — structured relay between sessions |

## Skill Phases

### Phase 1: Vision (What are we trying to improve?)

**Trigger:** user asks for improvement / upgrade / future-proofing.

1. Identify pain points in current agent behavior:
   - Context overflow / lost information
   - Planning loop detection / recovery
   - Model cost / latency
   - Missing capabilities (ACP, memory, checkpointing)
2. Catalog existing config (base.yaml, large_model.yaml, local_model.yaml):
   - Context zone sizes and priorities
   - Planner type
   - Recovery thresholds
   - RAG parameters
3. Establish improvement vectors (pick 1-3):
   - Impact analysis (Analyze)
   - Multi-stage planning (Blueprint)
   - Context lifecycle management (Crosswalk)
   - Adaptive caching (Distill)
   - Graceful degradation (Distill)
   - Cross-session memory (Crosswalk)

**Deliverable:** vision statement with 1-3 improvement vectors and expected outcomes.

### Phase 2: Analyze (Impact & Dependency Mapping)

**Trigger:** Analyze leading word or "impact analysis", "dependency mapping", "trace".

Before planning any change, map the territory:

1. **Impact analysis** — trace all paths from a proposed change:
   - Every file that imports or references the target
   - Every config key that depends on the target
   - Every test that exercises the target
2. **Dependency mapping** — characterize the architecture:
   - Module dependency graph (who depends on whom)
   - External API surfaces and contracts
   - Config profiles and their override chains
3. **Codebase characterization** — quantify the landscape:
   - LOC per module, cyclomatic complexity hotspots
   - Test coverage gaps in target areas
   - Convention consistency (naming, patterns, imports)
4. **Risk catalog** — flag high-risk areas:
   - Circular dependencies
   - Modules with no tests
   - Recently churned files with high bug density
   - Deprecated APIs still in use

5. **Reference completed analysis** — See `references/ANALYSIS_FINDINGS.md` for an example Phase 2 deliverable applied to the Meredith codebase. It documents implementation status of 6 improvement targets, gaps discovered, and priority ordering.

**Deliverable:** analysis report with impact graph, dependency map, and risk catalog. Every proposed change in subsequent phases traces back to this analysis.

### Phase 3: Blueprint (Multi-Stage Planning)

**Trigger:** Blueprint leading word or "planning improvements".

1. Assess current planner (`config.*.yaml:agent.planner_type`)
2. Design planning hierarchy:
   ```
   Strategic Plan (meta)
     ├── Phase 1: Discover & Explore
     │     └── Tactical Plan
     │           ├── Step 1: grep for pattern X
     │           ├── Step 2: read relevant files
     │           └── Step 3: synthesize findings
     ├── Phase 2: Implement
     │     └── Tactical Plan
     │           ├── Step 1: edit file A
     │           └── Step 2: edit file B
     └── Phase 3: Verify
           └── Tactical Plan
                 ├── Step 1: run tests
                 └── Step 2: run linter
   ```
3. Implement:
   - `agent/planner.py` — hierarchical planner with strategy/tactical layers
   - `plan_types.py` — `StrategicPlan`, `TacticalPlan`, `PlanPhase` types
   - Phase transition: success → next phase, failure → retry/re-plan current phase, loop → escalate

**Deliverable:** multi-stage planner implementation with phase lifecycle.

### Phase 4: Adapt (Graceful Degradation)

**Trigger:** Distill leading word or resource constraints (small model, low budget, slow response).

1. Detect current resource tier from active config profile
2. Apply tier-appropriate constraints:
   - **Tier 1 (Large model):** 128K+ tokens, ToT planner, hybrid router, verifier concurrent
   - **Tier 2 (Mid model):** 64K tokens, flat planner, hybrid router, no concurrent verifier
   - **Tier 3 (Small model):** 8-32K tokens, rules-only router, aggressive compression, RAG top_k=3-5
3. Verify graceful fallback paths exist:
   - When LLM call times out → degrade to simpler prompt / fewer candidates
   - When context budget is critical → emergency compression of semantic zone
   - When RAG returns low confidence → fall back to grep-only search

5. **Advanced: Adaptive Context Compaction (ACC)** — 5-tier staged compaction:
   - **Tier 1 (Budget Reduction):** cap tool outputs per-zone, every turn
   - **Tier 2 (Observation Masking):** replace older tool results with compact reference pointers
   - **Tier 3 (Fast Pruning):** drop low-value (<200 char) tool outputs within retention window
   - **Tier 4 (Aggressive Compression):** shrink retention window, trigger cache-aware dual-path
   - **Tier 5 (Full LLM Summarization):** serialized non-lossy, LLM summarization, post-compaction rehydration
6. See `references/CLAUDE_CODE_ARCH.md` for reference implementation details

**Deliverable:** updated config profiles, graceful fallback chains, and staged compaction pipeline.

### Phase 5: Crosswalk (Memory & Continuity)

**Trigger:** Crosswalk leading word or "memory", "checkpoint", "cross-session", "resume".

1. Check existing memory architecture (see `memory/` directory):
   - If no MEMORY.md exists, create one with procedural/episodic/semantic sections
   - If checkpoint.json exists, validate schema and add compaction script
2. Implement cross-session memory flow:
   ```
   Session start → load procedural memory (AGENTS.md, config)
                  → load relevant episodic memories (recent sessions)
                  → load semantic memories (learned patterns)
   Session end   → save episodic summary
                  → update semantic index with new patterns
   ```
3. Add checkpoint compaction:
   - Script that prunes checkpoints > N days old
   - Merges consecutive checkpoints into compressed summaries
   - Rebuilds semantic index from episodic summaries

4. **Advanced: CROSSWALK.md session bridging** (if CROSSWALK.md exists):
   - Read at session start → update Active Work section
   - Write at session boundaries (phase complete, decision made)
   - Write at session end → final state + next action directive
   - Archive older entries to `.agent/handoff/archive/` to keep file under ~2000 tokens
   - Atomic writes (temp file + rename) to prevent partial-write corruption
5. **Advanced: Three-Tier Hybrid RAG fusion:**
   - Tier 1 (BM25) — fast keyword, always on, no GPU
   - Tier 2 (Dense) — ONNX MiniLM + FAISS + BM25 RRF fusion
   - Tier 3 (Structural Graph) — AST-derived knowledge graph, BFS from seed hits
   - Adaptive-k: dynamic top-k based on similarity distribution
   - Cascade: Tier 1 → confidence check → Tier 2 → confidence check → Tier 3
6. See `references/CLAUDE_CODE_ARCH.md` for memory architecture details
7. See `references/GRAPH_RAG.md` for AST graph patterns
8. See `references/LIGHTWEIGHT_RAG.md` for lightweight RAG stack

**Deliverable:** MEMORY.md, CROSSWALK.md, checkpoint.json schema, compaction script, and three-tier RAG pipeline.

### Phase 6: Reckon (Verification & Iteration)

**Trigger:** end of improvement cycle, or user asks "verify", "validate".

1. Run the full test suite and lint:
   ```
   uv run ruff check src/
   uv run ruff format src/ --check
   uv run pytest tests/ -v
   ```
2. Review against goals from Phase 1 vision statement
3. Identify regressions or new pain points
4. If iteration needed → loop back to Phase 1 with updated vision
5. If complete → write improvement summary

**Deliverable:** improvement report with metrics, test results, and recommendations.

## Reference Files

These files ship with the skill and provide deeper context:

- [INNOVATIONS.md](references/INNOVATIONS.md) — Survey of 2025-2026 agent innovations (Orchard, COMPASS, TodoEvolve, AdaPlan-H, ReAcTree, MPO, AdaCache, TurboQuant, ZoomRAG, Claude Code ACC, PyCodeKG, VelociRAG)
- [STRATEGIES.md](references/STRATEGIES.md) — Detailed patterns for tool selection, planning, context management, ACC pipeline, three-tier RAG, and CROSSWALK.md
- [CLAUDE_CODE_ARCH.md](references/CLAUDE_CODE_ARCH.md) — Reference: Claude Code's 5-tier compaction pipeline and 7-layer memory architecture
- [LIGHTWEIGHT_RAG.md](references/LIGHTWEIGHT_RAG.md) — Reference: four lightweight RAG approaches (VelociRAG, SwiftRAG, MiniRAG, Adaptive-k)
- [GRAPH_RAG.md](references/GRAPH_RAG.md) — Reference: AST-derived code graphs (PyCodeKG, ZoomRAG, GraphRAG-MCP, CodeGraph)
- [TURBOQUANT.md](references/TURBOQUANT.md) — Reference: MLX TurboQuant ecosystem for Apple Silicon KV cache + weight compression
- [ANALYSIS_FINDINGS.md](references/ANALYSIS_FINDINGS.md) — Completed Phase 2 analysis for Meredith: implementation status of 6 improvement targets, gaps discovered with file-level locations, and priority ordering

Supporting directories:

- `assets/` — JSON schemas, diagrams, config templates
- `scripts/` — Compaction, analysis, and automation scripts

## Anti-Patterns

- **Over-engineering early** — don't add multi-stage planning until single-stage shows concrete failures
- **Static tier assignment** — tier should be dynamic based on current budget, not hardcoded to model name
- **Analysis paralysis** — the Analyze phase exists to enable action, not delay it. Set a time budget per analysis task; stop when you have enough to make a decision
- **Cache without eviction** — adaptive caching must include TTL and eviction, or stale data poisons decisions
- **Memory without compaction** — cross-session memory grows unbounded; compaction is not optional
- **Graceful degradation without testing** — fallback paths are the most buggy paths; test each one explicitly
