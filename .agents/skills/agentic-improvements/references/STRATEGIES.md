# STRATEGIES — Tool, Planning, and Context Patterns

> Reference file for the agentic-improvements skill.
> Detailed patterns for implementing the improvements outlined in SKILL.md.

---

## 1. Tool Selection Strategies

### Strategy Matrix

| Strategy | How It Works | Best For | Config Key |
|----------|-------------|----------|------------|
| `rules_only` | Hardcoded routing rules (if pattern X → use grep) | Small models (< 30B) | `tools.router.strategy` |
| `hybrid` | LLM proposes tools, rules filter/rank | Large models | `tools.router.strategy` |
| `llm_only` | Full LLM responsibility for tool choice | Frontier models | `tools.router.strategy` |

### Implementation Pattern

```python
# router.py — Tool routing with graceful degradation
class ToolRouter:
    def __init__(self, config: RouterConfig):
        self.strategy = config.strategy
        self.preferences = config.learned_preferences

    async def select(self, task: str, context: Context) -> ToolName:
        if self.strategy == "rules_only":
            return self._rule_based(task)
        elif self.strategy == "hybrid":
            candidates = await self._llm_propose(task)
            return self._filter_by_rules(candidates, context)
        else:  # llm_only
            return await self._llm_select(task)
```

### Learning Preferences

Track tool-usage patterns to improve routing over time:

```yaml
tools:
  router:
    learned_preferences: true
    preference_store: ".agent/tool_preferences.json"
```

Store per-task-type success rates and adjust routing weights accordingly.

---

## 2. Planning Strategies

### Strategy Stack

```yaml
agent:
  planner_type: tree_of_thought  # tree_of_thought | flat | hierarchical
  planner_model: null            # null = same model, or specify cheaper model
  verifier_concurrent: true      # Run verifier alongside executor
```

### Flat Planner (small models)

```
Task → Step 1 → Step 2 → ... → Step N → Done
  └── every step is a tool call with full context
```

### Tree of Thought (large models)

```
Task → Branch A → Step A1 → Step A2 → ...
     → Branch B → Step B1 → Step B2 → ...
     └── verifier evaluates branches, picks best
```

### Hierarchical Planner (new)

```
Task → Strategic Plan (3-7 phases)
        ├── Phase 1: Discover
        │     └── Tactical Plan
        │           ├── Step 1: search
        │           └── Step 2: read
        ├── Phase 2: Implement
        │     └── Tactical Plan
        │           ├── Step 1: edit
        │           └── Step 2: verify
        └── Phase 3: Verify
              └── Tactical Plan
                    └── Run tests
```

### Phase Lifecycle

```
[ACTIVE] → success → [COMPLETE]
    ↓ failure
[RETRY] → retries < max → [ACTIVE]
    ↓ retries >= max
[RECOVERY] → escalate → [ACTIVE] (with intervention)
    ↓ escalate fails
[ABORTED]
```

---

## 3. Context Management Strategies

### Zone Architecture

```
┌─────────────────────────────────────────────┐
│ IMMUTABLE (priority 0) — always present     │
│ System prompt + tool schemas + AGENTS.md    │
├─────────────────────────────────────────────┤
│ TASK (priority 1) — current objective       │
│ "Implement function X in file Y"            │
├─────────────────────────────────────────────┤
│ WORKING (priority 2) — sliding window       │
│ Recent tool calls + results (last N)        │
├─────────────────────────────────────────────┤
│ EPISODIC (priority 3) — compressed history  │
│ Summarized earlier steps                    │
├─────────────────────────────────────────────┤
│ SEMANTIC (priority 4) — project knowledge   │
│ Conventions, patterns, cross-session memory │
├─────────────────────────────────────────────┤
│ SCRATCH (priority 5) — agent notes          │
│ Meta-thinker interventions, scratchpad      │
└─────────────────────────────────────────────┘
```

### Compression Chain

```
Working zone exceeds budget
  → Compress oldest entries into episodic summary
  → If still over budget, compress two oldest episodic entries
  → If still over budget, truncate semantic zone
  → If still over budget (EMERGENCY), truncate scratch
  → If still over budget, truncate task description
```

### KV Cache Compression (TurboQuant-style)

For agents on constrained hardware, KV cache compression is the difference between 32K and 128K context on the same GPU.

```yaml
context:
  max_tokens: 128000        # Target context (was 32000)
  kv_cache:
    compression: turboquant_4bit_nc  # vLLM dtype, ~2.6-3.1× compression
    # Alternatives:
    #   fp8              → 2×, no quality loss, Hopper/Blackwell only
    #   turboquant_3bit_nc → 3.5-4×, 15-25pt quality drop on hard tasks
    #   turboquant_4bit_nc → 2.6-3.1×, ~1pt from FP8 (sweet spot)
```

**When to apply:**
- Local model profile (`local_model.yaml`): 32K → 96K effective context with `turboquant_4bit_nc`
- Mid-tier GPU (RTX 4090, 48GB): 128K+ inference feasible without FP8 attention
- Apple Silicon: MLX-INT4 + TurboQuant enables 64K+ on M-series

**Constraint:** TurboQuant compresses the KV cache during inference, not the agent's prompt context. The agent's working context window (system prompt + tool calls) is unaffected; the benefit is longer generation without OOM on long-horizon tasks.

### Adaptive Cache (AdaCache-style)

```yaml
rag:
  cache:
    strategy: adaptive
    tiers:
      l1:  # In-memory, TTL 30s
        max_entries: 20
        ttl_seconds: 30
      l2:  # Session-level, compressed
        max_entries: 50
        ttl_seconds: 300
      l3:  # Persistent RAG index
        max_entries: 1000
    confidence_threshold: 0.7  # Above this → use L1/L2 only
```

---

## 4. Graceful Degradation Chain

```
┌──────────────────────────────────────────────────┐
│ 1. Primary config (e.g., large_model.yaml)       │
│    → 200K context, ToT planner, hybrid router    │
├──────────────────────────────────────────────────┤
│ 2. Degrade to mid config                         │
│    → 64K context, flat planner, hybrid router    │
│    Trigger: LLM timeout > 3s, context > 80% full │
├──────────────────────────────────────────────────┤
│ 3. Degrade to small config                       │
│    → 32K context, rules-only router, RAG top_k=5 │
│    Trigger: repeated timeouts, context > 95% full│
├──────────────────────────────────────────────────┤
│ 4. Emergency mode                                │
│    → 8K context, single-step, no RAG, no verifier│
│    Trigger: model unreachable, budget exhausted  │
└──────────────────────────────────────────────────┘
```

### Implementation

```python
# config.py — Dynamic tier selection
class AgentConfig:
    def select_tier(self, context: RuntimeContext) -> ConfigProfile:
        if context.model_unreachable:
            return self.emergency_profile
        if context.context_usage > 0.95 or context.repeated_timeouts > 3:
            return self.small_profile
        if context.context_usage > 0.80 or context.avg_llm_latency > 3.0:
            return self.mid_profile
        return self.large_profile
```

---

## 5. Cross-Session Memory Pattern

### MEMORY.md Structure

```markdown
# MEMORY.md — Cross-Session Agent Memory

## Procedural (always loaded)
- AGENTS.md conventions
- Tool definitions and usage patterns
- Project-specific idioms

## Episodic (by timestamp)
- [2026-06-27] Session: Implemented RAG chunker
- [2026-06-26] Session: Fixed loop detection bug
- ...

## Semantic (by similarity)
- Pattern: When modifying test files, first check conftest.py for fixtures
- Pattern: API client follows httpx async pattern
- Rule: Never hardcode API keys; use env vars
```

### Checkpoint Schema (checkpoint.json)

```json
{
  "format_version": 1,
  "session_id": "abc-123-def",
  "created_at": "2026-06-27T10:30:00Z",
  "task": "Implement RAG chunker",
  "current_phase": "implementation",
  "completed_phases": ["research"],
  "context_summary": "Selected 3 chunking strategies, eliminated regex-only",
  "key_findings": [
    "AST chunking preserves structure better than line-based",
    "Tree-sitter missing Go grammar — need fallback"
  ],
  "file_states": {
    "modified": ["src/coding_agent/rag/chunker.py"],
    "created": [],
    "deleted": []
  }
}
```

### Compaction Script

```python
# scripts/compact_checkpoints.py
"""Prune and merge old checkpoints."""
import json
from pathlib import Path
from datetime import datetime, timedelta

MAX_AGE_DAYS = 14
CHECKPOINT_DIR = Path(".agent/checkpoints")

def compact():
    now = datetime.now()
    for f in sorted(CHECKPOINT_DIR.glob("*.json")):
        cp = json.loads(f.read_text())
        age = now - datetime.fromisoformat(cp["created_at"])
        if age > timedelta(days=MAX_AGE_DAYS):
            # Move to compressed archive
            archive = CHECKPOINT_DIR / "archive" / f.name
            archive.parent.mkdir(exist_ok=True)
            f.rename(archive)
```

---

## 6. Testing Patterns for Agent Improvements

### What to Test

| Component | Test Type | Example |
|-----------|-----------|---------|
| Planner | Unit | `test_flat_plan_generation` |
| Router | Unit | `test_rule_based_routing` |
| Context compression | Unit | `test_zone_compaction_orders` |
| Graceful degradation | Integration | `test_fallback_chain_on_timeout` |
| Memory persistence | Integration | `test_save_and_load_episodic` |
| ACP protocol | Integration | `test_acp_tool_call_roundtrip` |

### Test Fixture Pattern

```python
# tests/conftest.py — Agent test fixtures
@pytest.fixture
def config_small():
    return AgentConfig.from_yaml("config/local_model.yaml")

@pytest.fixture
def config_large():
    return AgentConfig.from_yaml("config/large_model.yaml")

@pytest.fixture
def mock_llm_small():
    """Simulate a small model: slow, limited output."""
    ...

@pytest.fixture
def mock_llm_large():
    """Simulate a large model: fast, rich output."""
    ...
```
