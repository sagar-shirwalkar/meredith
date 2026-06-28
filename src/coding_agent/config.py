from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

"""
Configuration loader with layered YAML merging.

Resolution order (later wins):
    base.yaml  →
    model-specific YAML  →
    CLI overrides  →
    Environment variables (${VAR} placeholders)

All config values are exposed as a frozen dataclass tree for
type-safe access throughout the codebase.
"""


def _substitute_env_vars(data: Any) -> Any:
    """Recursively substitute ${ENV_VAR} placeholders with environment variable values."""
    if isinstance(data, str):

        def replace(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))

        return re.sub(r"\${([^}]+)}", replace, data)
    elif isinstance(data, dict):
        return {k: _substitute_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_substitute_env_vars(item) for item in data]
    return data


# ──────────────────────────────────────────────────────────────
# Configuration dataclasses — mirror the YAML structure
# ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ZoneConfig:
    priority: int = 0
    max_tokens: int = 2000


@dataclass(frozen=True, slots=True)
class CompressionConfig:
    """Adaptive Context Compaction staged thresholds.

    Each stage triggers at a specific remaining-budget fraction.
    Later stages are more aggressive and expensive.
    """

    stage1_budget_reduction: float = 0.40
    stage2_observation_masking: float = 0.30
    stage3_fast_pruning: float = 0.20
    stage4_aggressive_compression: float = 0.12
    stage5_reversible_collapse: float = 0.08
    stage6_full_llm: float = 0.04

    protected_recency_steps: int = 3
    min_output_length_for_pruning: int = 200
    collapse_serialization_path: str = ".agent/collapse"
    max_rehydration_files: int = 5


@dataclass(frozen=True, slots=True)
class ContextConfig:
    max_tokens: int = 128000
    zones: dict[str, ZoneConfig] = field(default_factory=dict)
    compression_trigger_fraction: float = 0.15
    emergency_fraction: float = 0.05
    compaction: CompressionConfig = field(default_factory=CompressionConfig)


@dataclass(frozen=True, slots=True)
class StepAllocConfig:
    think: int = 200
    tool_call: int = 300
    tool_result: int = 2000
    observation: int = 100


@dataclass(frozen=True, slots=True)
class BudgetConfig:
    step_allocations: StepAllocConfig = field(default_factory=StepAllocConfig)
    max_fraction_per_step: float = 0.10


@dataclass(frozen=True, slots=True)
class RecoveryConfig:
    loop_detection_window: int = 6
    exact_repetition_threshold: int = 2
    semantic_similarity_threshold: float = 0.85
    error_repetition_threshold: int = 2
    stall_steps: int = 4
    max_recovery_attempts: int = 3


@dataclass(frozen=True, slots=True)
class FsToolConfig:
    max_read_lines: int = 80
    edit_preferred: bool = True


@dataclass(frozen=True, slots=True)
class SearchToolConfig:
    backend: str = "ripgrep"
    max_results: int = 30
    context_lines: int = 0


@dataclass(frozen=True, slots=True)
class WebToolConfig:
    backend: str = "brave"
    max_results: int = 8
    timeout_seconds: int = 15


@dataclass(frozen=True, slots=True)
class GitToolConfig:
    auto_commit: bool = False


@dataclass(frozen=True, slots=True)
class RouterConfig:
    strategy: str = "hybrid"
    learned_preferences: bool = True


@dataclass(frozen=True, slots=True)
class ToolsConfig:
    router: RouterConfig = field(default_factory=RouterConfig)
    fs: FsToolConfig = field(default_factory=FsToolConfig)
    search: SearchToolConfig = field(default_factory=SearchToolConfig)
    web: WebToolConfig = field(default_factory=WebToolConfig)
    git: GitToolConfig = field(default_factory=GitToolConfig)


@dataclass(frozen=True, slots=True)
class ChunkConfig:
    max_lines: int = 60
    overlap_lines: int = 5
    strategy: str = "ast"


@dataclass(frozen=True, slots=True)
class DenseConfig:
    enabled: bool = True
    dimension: int = 384
    backend: str = "numpy_random"  # "numpy_random" | "onnx"


@dataclass(frozen=True, slots=True)
class GraphConfig:
    enabled: bool = True
    max_depth: int = 2
    max_expansion: int = 10


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    top_k: int = 10
    bm25_weight: float = 0.7
    dense_weight: float = 0.3
    confidence_threshold: float = 0.7
    rrf_k: int = 60


@dataclass(frozen=True, slots=True)
class RagConfig:
    enabled: bool = True
    index_dir: str = ".agent/index"
    chunk: ChunkConfig = field(default_factory=ChunkConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    dense: DenseConfig = field(default_factory=DenseConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    reindex_on_startup: bool = False


@dataclass(frozen=True, slots=True)
class MemoryConfig:
    store_path: str = ".agent/memory.db"
    max_entry_tokens: int = 500


@dataclass(frozen=True, slots=True)
class SkillsConfig:
    directories: list[str] = field(
        default_factory=lambda: ["skills", ".agents/skills", ".agent/skills"]
    )


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    level: str = "INFO"
    file: str = ".agent/agent.log"


@dataclass(frozen=True, slots=True)
class TurboQuantConfig:
    enabled: bool = False
    kv_bits: int = 3
    weight_bits: int = 4
    sink_tokens: int = 128
    layer_adaptive: bool = True


@dataclass(frozen=True, slots=True)
class LlmConfig:
    provider: str = "remote"
    model: str = "gpt-4o"
    api_base: str = "https://api.openai.com/v1"
    key_var: str = "LLM_API_KEY"
    ollama_base: str = "http://localhost:11434"
    mlx_model_path: str | None = None
    mlx_fallback: bool = False
    temperature: float = 0.2
    max_response_tokens: int = 4096
    streaming: bool = True
    turboquant: TurboQuantConfig = field(default_factory=TurboQuantConfig)


@dataclass(frozen=True, slots=True)
class AgentConfig:
    max_steps: int = 50
    step_timeout_seconds: int = 120
    checkpoint_every_n_steps: int = 3
    working_directory: str = "."
    planner_type: str = "tree_of_thought"
    planner_model: str | None = None
    verifier_concurrent: bool = True


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Root configuration object — immutable after loading."""

    llm: LlmConfig = field(default_factory=LlmConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    recovery: RecoveryConfig = field(default_factory=RecoveryConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    rag: RagConfig = field(default_factory=RagConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


# ──────────────────────────────────────────────────────────────
# Loader
# ──────────────────────────────────────────────────────────────

_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*. Lists are replaced, not appended."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning an empty dict if it doesn't exist."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data = data if isinstance(data, dict) else {}
    # Substitute environment variable placeholders
    return _substitute_env_vars(data)


def _dict_to_zone_configs(raw: dict[str, Any]) -> dict[str, ZoneConfig]:
    """Convert the nested zone dicts into ZoneConfig instances."""
    result: dict[str, ZoneConfig] = {}
    for name, vals in raw.items():
        if isinstance(vals, dict):
            result[name] = ZoneConfig(
                priority=vals.get("priority", 0),
                max_tokens=vals.get("max_tokens", 2000),
            )
    return result


def _build_config(raw: dict[str, Any]) -> AppConfig:
    """Walk the merged dict and construct the frozen AppConfig tree."""

    llm_raw = raw.get("llm", {})
    turbo_raw = llm_raw.get("turboquant", {})
    agent_raw = raw.get("agent", {})
    context_raw = raw.get("context", {})
    compaction_raw = context_raw.get("compaction", {})
    budget_raw = raw.get("budget", {})
    recovery_raw = raw.get("recovery", {})
    tools_raw = raw.get("tools", {})
    rag_raw = raw.get("rag", {})
    memory_raw = raw.get("memory", {})
    skills_raw = raw.get("skills", {})
    logging_raw = raw.get("logging", {})

    # Check for environment variable overrides for LLM settings
    # These allow users to customize settings without modifying committed files
    env_model = os.environ.get("MEREDITH_LLM_MODEL")
    if env_model:
        llm_raw["model"] = env_model

    env_api_base = os.environ.get("MEREDITH_LLM_API_BASE")
    if env_api_base:
        llm_raw["api_base"] = env_api_base

    env_provider = os.environ.get("MEREDITH_LLM_PROVIDER")
    if env_provider:
        llm_raw["provider"] = env_provider

    # Build nested objects bottom-up
    step_alloc = StepAllocConfig(**budget_raw.get("step_allocations", {}))

    router_raw = tools_raw.get("router", {})
    router_cfg = RouterConfig(
        strategy=router_raw.get("strategy", "hybrid"),
        learned_preferences=router_raw.get("learned_preferences", True),
    )

    chunk_raw = rag_raw.get("chunk", {})
    chunk_cfg = ChunkConfig(
        max_lines=chunk_raw.get("max_lines", 60),
        overlap_lines=chunk_raw.get("overlap_lines", 5),
        strategy=chunk_raw.get("strategy", "ast"),
    )

    retrieval_raw = rag_raw.get("retrieval", {})
    retrieval_cfg = RetrievalConfig(
        top_k=retrieval_raw.get("top_k", 10),
        bm25_weight=retrieval_raw.get("bm25_weight", 0.7),
        dense_weight=retrieval_raw.get("dense_weight", 0.3),
        confidence_threshold=retrieval_raw.get("confidence_threshold", 0.7),
        rrf_k=retrieval_raw.get("rrf_k", 60),
    )

    dense_raw = rag_raw.get("dense", {})
    dense_cfg = DenseConfig(
        enabled=dense_raw.get("enabled", True),
        dimension=dense_raw.get("dimension", 384),
        backend=dense_raw.get("backend", "numpy_random"),
    )

    graph_raw = rag_raw.get("graph", {})
    graph_cfg = GraphConfig(
        enabled=graph_raw.get("enabled", True),
        max_depth=graph_raw.get("max_depth", 2),
        max_expansion=graph_raw.get("max_expansion", 10),
    )

    zones_raw = context_raw.get("zones", {})
    zones_cfg = _dict_to_zone_configs(zones_raw)

    compaction_cfg = CompressionConfig(
        stage1_budget_reduction=compaction_raw.get("stage1_budget_reduction", 0.40),
        stage2_observation_masking=compaction_raw.get("stage2_observation_masking", 0.30),
        stage3_fast_pruning=compaction_raw.get("stage3_fast_pruning", 0.20),
        stage4_aggressive_compression=compaction_raw.get("stage4_aggressive_compression", 0.12),
        stage5_reversible_collapse=compaction_raw.get("stage5_reversible_collapse", 0.08),
        stage6_full_llm=compaction_raw.get("stage6_full_llm", 0.04),
        protected_recency_steps=compaction_raw.get("protected_recency_steps", 3),
        min_output_length_for_pruning=compaction_raw.get("min_output_length_for_pruning", 200),
        collapse_serialization_path=compaction_raw.get(
            "collapse_serialization_path",
            ".agent/collapse",
        ),
        max_rehydration_files=compaction_raw.get("max_rehydration_files", 5),
    )

    return AppConfig(
        llm=LlmConfig(
            provider=llm_raw.get("provider", "remote"),
            model=llm_raw.get("model", "gpt-4o"),
            api_base=llm_raw.get("api_base", "https://api.openai.com/v1"),
            key_var=llm_raw.get("key_var", "LLM_API_KEY"),
            ollama_base=llm_raw.get("ollama_base", "http://localhost:11434"),
            mlx_model_path=llm_raw.get("mlx_model_path"),
            mlx_fallback=llm_raw.get("mlx_fallback", False),
            temperature=llm_raw.get("temperature", 0.2),
            max_response_tokens=llm_raw.get("max_response_tokens", 4096),
            streaming=llm_raw.get("streaming", True),
            turboquant=TurboQuantConfig(
                enabled=turbo_raw.get("enabled", False),
                kv_bits=turbo_raw.get("kv_bits", 3),
                weight_bits=turbo_raw.get("weight_bits", 4),
                sink_tokens=turbo_raw.get("sink_tokens", 128),
                layer_adaptive=turbo_raw.get("layer_adaptive", True),
            ),
        ),
        agent=AgentConfig(
            max_steps=agent_raw.get("max_steps", 50),
            step_timeout_seconds=agent_raw.get("step_timeout_seconds", 120),
            checkpoint_every_n_steps=agent_raw.get("checkpoint_every_n_steps", 3),
            working_directory=agent_raw.get("working_directory", "."),
            planner_type=agent_raw.get("planner_type", "tree_of_thought"),
            planner_model=agent_raw.get("planner_model"),
            verifier_concurrent=agent_raw.get("verifier_concurrent", True),
        ),
        context=ContextConfig(
            max_tokens=context_raw.get("max_tokens", 128000),
            zones=zones_cfg,
            compression_trigger_fraction=context_raw.get("compression_trigger_fraction", 0.15),
            emergency_fraction=context_raw.get("emergency_fraction", 0.05),
            compaction=compaction_cfg,
        ),
        budget=BudgetConfig(
            step_allocations=step_alloc,
            max_fraction_per_step=budget_raw.get("max_fraction_per_step", 0.10),
        ),
        recovery=RecoveryConfig(
            loop_detection_window=recovery_raw.get("loop_detection_window", 6),
            exact_repetition_threshold=recovery_raw.get("exact_repetition_threshold", 2),
            semantic_similarity_threshold=recovery_raw.get("semantic_similarity_threshold", 0.85),
            error_repetition_threshold=recovery_raw.get("error_repetition_threshold", 2),
            stall_steps=recovery_raw.get("stall_steps", 4),
            max_recovery_attempts=recovery_raw.get("max_recovery_attempts", 3),
        ),
        tools=ToolsConfig(
            router=router_cfg,
            fs=FsToolConfig(**tools_raw.get("fs", {})),
            search=SearchToolConfig(**tools_raw.get("search", {})),
            web=WebToolConfig(**tools_raw.get("web", {})),
            git=GitToolConfig(**tools_raw.get("git", {})),
        ),
        rag=RagConfig(
            enabled=rag_raw.get("enabled", True),
            index_dir=rag_raw.get("index_dir", ".agent/index"),
            chunk=chunk_cfg,
            retrieval=retrieval_cfg,
            dense=dense_cfg,
            graph=graph_cfg,
            reindex_on_startup=rag_raw.get("reindex_on_startup", False),
        ),
        memory=MemoryConfig(**memory_raw),
        skills=SkillsConfig(
            directories=skills_raw.get("directories", ["skills", ".agent/skills"]),
        ),
        logging=LoggingConfig(**logging_raw),
    )


def load_config(
    profile: str = "large_model",
    config_dir: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> AppConfig:
    """
    Load and merge configuration layers.

    Args:
        profile: Name of the model-specific YAML (without .yaml extension).
                 e.g. "large_model" → config/large_model.yaml
        config_dir: Directory containing base.yaml and profile YAMLs.
                    Defaults to <project_root>/config/.
        overrides: Optional dict applied last (e.g. from CLI flags).

    Returns:
        Frozen AppConfig instance.
    """
    cfg_dir = config_dir or _CONFIG_DIR

    # Layer 1: base defaults
    base = _load_yaml(cfg_dir / "base.yaml")

    # Layer 2: profile overrides
    profile_data = _load_yaml(cfg_dir / f"{profile}.yaml")

    # Layer 3: CLI overrides
    cli_overrides = overrides or {}

    # Merge all layers
    merged = _deep_merge(base, _deep_merge(profile_data, cli_overrides))

    return _build_config(merged)


def resolve_path(config: AppConfig, relative_path: str) -> Path:
    """Resolve a path relative to the agent's working directory."""
    workdir = Path(config.agent.working_directory).resolve()
    return workdir / relative_path
