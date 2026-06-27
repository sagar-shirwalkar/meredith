# INNOVATIONS — 2025-2026 Agent Research Survey

> Reference file for the agentic-improvements skill.
> Items marked ⚠️ are pre-print or have limited replication evidence.
> Items marked ✅ have strong empirical support across multiple evaluations.

---

## 1. Orchard — Microsoft's Open-Source Agentic Modeling Framework ✅

**Source:** Microsoft Research, 2026.
**Venue:** Open-source release (Apache 2.0).

Orchard is a framework for training and composing agentic models from diverse, heterogeneous demonstrations. Key claims:

- **SWE-bench Verified 67.5% at 30B parameters** — competitive with much larger models
- **GUI agent from 0.4K trajectories** — extreme data efficiency via compositional training
- **Modular architecture** — separates perception, reasoning, and action into composable modules
- **Open-source** — Apache 2.0, enabling community extension

**Relevance:** If this project were to train/fine-tune its own agent model, Orchard provides the composition framework. For now, the key insight is the **modular separation** of perception/reasoning/action — a pattern we can adopt at the architectural level without training.

**Risk/Reward:** ✅ Low risk — Apache 2.0, Microsoft-supported. High reward if we ever train custom models.

---

## 2. COMPASS — Context-Organized Multi-Agent Planning ✅

**Source:** ACL 2026.
**Venue:** ACL 2026 (main conference).

COMPASS separates the agent into three specialized components:

1. **Main Agent** — tactical reasoning, tool use (ReAct-style)
2. **Meta-Thinker** — monitors progress, issues strategic interventions
3. **Context Manager** — maintains concise, stage-appropriate progress briefs

**Key results:**
- Up to +20% accuracy on GAIA, BrowseComp, Humanity's Last Exam
- Test-time scaling matches DeepResearch-level performance
- Context management can be delegated to a smaller model (post-training pipeline)

**Relevance:** Directly applicable. The Meta-Thinker + Context Manager separation is a lightweight addition to the existing single-agent loop in `src/coding_agent/agent/`. The context zone system in `base.yaml` maps naturally to the Context Manager role.

**Risk/Reward:** ✅ Low risk — well-tested, modular, ACL-published. High reward for long-horizon tasks.

---

## 3. TodoEvolve — Learning to Architect Planning Systems ⚠️

**Source:** arXiv preprint, February 2026.
**Venue:** Pre-print, under review.

TodoEvolve autonomously synthesizes and revises task-specific planning architectures:

- **PlanFactory** — modular design space for planning paradigms (topology, initialization, adaptation, navigation)
- **Todo-14B** — trained via Impedance-Guided Preference Optimization (IGPO)
- **Multi-objective** — balances performance, stability, and token-efficiency

**Key results:**
- Surpasses hand-crafted planning modules across 5 agentic benchmarks
- Maintains economical API costs and runtime overhead

**Relevance:** The PlanFactory modular design space is the key architectural insight. Instead of hardcoding a single planner type, design a composable planning system where topology and adaptation strategy are configurable parameters.

**Risk/Reward:** ⚠️ Medium risk — pre-print, unverified reproduction. Medium reward — the modular design pattern is sound even if the training approach isn't replicated.

---

## 4. AdaPlan-H — Self-Adaptive Hierarchical Planning ⚠️

**Source:** arXiv preprint, 2026.
**Venue:** Pre-print.

Inspired by progressive refinement theory from cognitive science:

- **Coarse-to-fine** — starts with a global plan, progressively expands details based on task complexity
- **Adaptive granularity** — simple tasks get flat plans, complex tasks get deep hierarchies
- **Imitation learning + capability enhancement** — optimization procedures

**Key results:**
- Outperforms single-level planning in effectiveness
- Reduces token wastage from overplanning

**Relevance:** The adaptive hierarchy is the key insight. Integrate with the existing `planner_type` config: add `granularity: auto` that adjusts hierarchy depth based on task complexity.

**Risk/Reward:** ⚠️ Medium risk — pre-print, limited evaluation domains. Medium reward — the progressive refinement pattern is well-established in cognitive science.

---

## 5. ReAcTree — Hierarchical LLM Agent Trees ✅

**Source:** arXiv preprint, November 2025.
**Venue:** Pre-print, code released.

Decomposes complex goals into manageable subgoals via a dynamically constructed tree:

- **Agent nodes** — handle individual subgoals (reason, act, expand tree)
- **Control flow nodes** — coordinate execution strategies
- **Dual memory** — episodic (subgoal-level examples) + working (environment-specific observations)

**Key results:**
- WAH-NL: 61% goal success rate with Qwen 2.5 72B (ReAct: 31%)
- Consistent improvement across diverse LLMs

**Relevance:** The agent tree + control flow node pattern is directly applicable to the agent loop. The dual memory system (episodic + working) maps to the existing context zones.

**Risk/Reward:** ✅ Low risk — code released, reproducible results. High reward for complex multi-step tasks.

---

## 6. MPO — Meta Plan Optimization ✅

**Source:** EMNLP 2025 Findings.
**Venue:** EMNLP 2025 (Findings volume).

MPO enhances agent planning via explicit high-level guidance (meta plans):

- **Meta plans** — high-level general guidance, not step-by-step instructions
- **Continuous optimization** — meta plans refined based on task execution feedback
- **Plug-and-play** — works with any existing agent framework

**Key results:**
- Significant improvement over baselines on representative tasks
- Enhances generalization to unseen scenarios

**Relevance:** The meta-plan concept aligns with the Strategic layer in our planning hierarchy. The continuous optimization feedback loop is the key mechanism to add.

**Risk/Reward:** ✅ Low risk — EMNLP-published, well-scoped technique. Medium reward — meta-plan optimization is a natural fit for the existing planner.

---

## 7. AdaCache — Adaptive Caching for LLM Agents ✅

**Source:** ICLR 2026.
**Venue:** ICLR 2026 (main conference).

AdaCache introduces confidence-based adaptive retrieval depth:

- **Confidence estimator** — predicts whether shallow retrieval is sufficient
- **Adaptive depth** — low confidence → deep/hierarchical retrieval; high confidence → fast/single-pass
- **TTFT reduction** — reduces time-to-first-token while preserving quality

**Key results:**
- Significant latency reduction without quality degradation
- Works with existing RAG pipelines as a drop-in module

**Relevance:** Directly applicable to the RAG pipeline in `src/coding_agent/rag/`. The confidence estimator pattern can be added as a pre-retrieval step.

**Risk/Reward:** ✅ Low risk — ICLR-published, drop-in module. High reward for latency-sensitive applications.

---

## 8. Anthropic MEMORY.md Pattern ✅

**Source:** Anthropic documentation + GitHub discussion.
**Status:** Community-adopted pattern, not a published paper.

Three-tier memory architecture:

- **Procedural** — always loaded: AGENTS.md, config conventions, system prompts
- **Episodic** — temporal retrieval: session summaries keyed by timestamp
- **Semantic** — similarity retrieval: learned patterns, project conventions, recurring solutions

Plus:
- **checkpoint.json** — per-task checkpoint for >24h session persistence
- **Compaction script** — prunes old checkpoints, merges consecutive entries

**Relevance:** Directly applicable. The existing `memory/` module already has the SQLite store; add the MEMORY.md file and checkpoint.json schema.

**Risk/Reward:** ✅ Low risk — community-proven pattern, no dependencies. High reward for cross-session continuity.

---

## 9. Zed ACP Integration ✅

**Source:** Zed editor, 2025-2026.
**Status:** Production, open standard (Apache 2.0).

The Agent Client Protocol (ACP) enables any agent to integrate with any editing environment:

- **Real-time editing** — agents edit files with syntax highlighting
- **Multi-file context** — full codebase awareness
- **Any agent, any editor** — Claude, Codex, OpenCode, Gemini CLI all speak ACP
- **ACP Registry** — centralized agent distribution (launched Jan 2026)

**Relevance:** The existing ACP server in `src/coding_agent/acp/` should be maintained and tested for compatibility with the latest ACP spec. The registry model also provides a distribution channel.

**Risk/Reward:** ✅ Low risk — production, open standard. Maintains compatibility with Zed ecosystem.

---

## 10. TurboQuant — Near-Optimal KV Cache Compression ✅

**Source:** Google Research, ICLR 2026.
**Venue:** ICLR 2026 (main conference). arXiv:2504.19874.

TurboQuant is a data-oblivious vector quantization framework that compresses LLM KV caches to ~3 bits per coordinate with zero accuracy loss:

- **Two-stage design** — PolarQuant (rotation + Lloyd-Max scalar quantization) captures most compression; QJL (1-bit residual correction) removes inner-product bias
- **6× memory reduction** — KV cache drops from FP16 to 2.5-3.5 bits per value
- **Up to 8× speedup** — attention logit computation on H100 GPUs (4-bit mode; end-to-end closer to 1.5-2× per co-author clarification)
- **Data-oblivious** — no training, no fine-tuning, no dataset-specific calibration. Works on any model out of the box
- **Provably near-optimal** — within ≈2.7× of the information-theoretic distortion bound

**Component papers:**
- **PolarQuant** (AISTATS 2026) — random rotation + polar coordinate transform removes per-block normalization overhead
- **Quantized Johnson-Lindenstrauss / QJL** (arXiv:2406.03482) — 1-bit transform giving unbiased inner product estimates

**Community adoption:**
- vLLM merged `turboquant_4bit_nc` and `turboquant_3bit_nc` KV cache dtypes (May 2026)
- Community PyTorch and Triton implementations available
- MLX integration for Apple Silicon

**Relevance:** Two direct applications for agent systems:
1. **Long-context inference** — TurboQuant enables agents to sustain 128K+ token contexts on consumer hardware (RTX 4090, Apple Silicon) by compressing the KV cache 3-6×. This directly impacts the context window budget — local-model agents (currently 32K in `local_model.yaml`) could double or triple their effective context without hardware upgrades.
2. **Vector search compression** — the same algorithm serves as a drop-in replacement for Product Quantization in RAG pipelines. Data-oblivious means zero indexing time (no k-means training), making it ideal for dynamic codebase indexing.

**Risk/Reward:** ✅ Low risk — ICLR-published, vLLM-merged, community implementations available. High reward for agents running on constrained hardware.

---

## Summary: Innovation Adoption Map

| Innovation | Apply To | Priority | Risk |
|------------|----------|----------|------|
| COMPASS | Agent loop (Meta-Thinker + Context Manager) | High | Low |
| MEMORY.md | Memory module (procedural/episodic/semantic) | High | Low |
| TurboQuant | Context budget (KV cache compression for long-context on constrained hardware) | High | Low |
| AdaCache | RAG pipeline (confidence-based retrieval) | Medium | Low |
| ReAcTree | Planning (agent tree + control flow) | Medium | Low |
| MPO | Planning (meta-plan optimization loop) | Medium | Low |
| AdaPlan-H | Planning (adaptive granularity) | Low | Medium |
| TodoEvolve | Planning (composable planning modules) | Low | Medium |
| Orchard | Future: custom agent training | Low | Low |
| Zed ACP | ACP server (maintain compatibility) | Ongoing | Low |
