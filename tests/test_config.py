from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from coding_agent.config import (
    AgentConfig,
    AppConfig,
    BudgetConfig,
    ChunkConfig,
    ContextConfig,
    FsToolConfig,
    GitToolConfig,
    LlmConfig,
    LoggingConfig,
    MemoryConfig,
    RagConfig,
    RecoveryConfig,
    RetrievalConfig,
    RouterConfig,
    SearchToolConfig,
    SkillsConfig,
    StepAllocConfig,
    ToolsConfig,
    WebToolConfig,
    ZoneConfig,
    _build_config,
    _deep_merge,
    _dict_to_zone_configs,
    _load_yaml,
    load_config,
    resolve_path,
)


def test_zone_config_defaults():
    zc = ZoneConfig()
    assert zc.priority == 0
    assert zc.max_tokens == 2000


def test_zone_config_custom():
    zc = ZoneConfig(priority=5, max_tokens=4000)
    assert zc.priority == 5
    assert zc.max_tokens == 4000


def test_context_config_defaults():
    cc = ContextConfig()
    assert cc.max_tokens == 128000
    assert cc.compression_trigger_fraction == 0.15


def test_step_alloc_config_defaults():
    sa = StepAllocConfig()
    assert sa.think == 200
    assert sa.tool_call == 300


def test_budget_config_defaults():
    bc = BudgetConfig()
    assert bc.max_fraction_per_step == 0.10


def test_recovery_config_defaults():
    rc = RecoveryConfig()
    assert rc.loop_detection_window == 6
    assert rc.exact_repetition_threshold == 2


def test_fs_tool_config():
    ft = FsToolConfig(max_read_lines=100, edit_preferred=False)
    assert ft.max_read_lines == 100
    assert ft.edit_preferred is False


def test_search_tool_config_defaults():
    st = SearchToolConfig()
    assert st.backend == "ripgrep"
    assert st.max_results == 30


def test_web_tool_config():
    wt = WebToolConfig(backend="tavily", max_results=10)
    assert wt.backend == "tavily"
    assert wt.timeout_seconds == 15


def test_git_tool_config():
    gt = GitToolConfig(auto_commit=True)
    assert gt.auto_commit is True


def test_router_config_defaults():
    rc = RouterConfig()
    assert rc.strategy == "hybrid"


def test_tools_config_nesting():
    tc = ToolsConfig()
    assert tc.router.strategy == "hybrid"
    assert tc.fs.max_read_lines == 80


def test_chunk_config():
    cc = ChunkConfig(max_lines=100, strategy="regex")
    assert cc.max_lines == 100
    assert cc.strategy == "regex"


def test_retrieval_config():
    rc = RetrievalConfig(top_k=5, bm25_weight=0.5, dense_weight=0.5)
    assert rc.top_k == 5
    assert rc.bm25_weight == 0.5


def test_rag_config_defaults():
    rc = RagConfig()
    assert rc.enabled is True
    assert rc.index_dir == ".agent/index"


def test_memory_config():
    mc = MemoryConfig(store_path="/tmp/test.db", max_entry_tokens=1000)
    assert mc.store_path == "/tmp/test.db"


def test_skills_config():
    sc = SkillsConfig(directories=["skills"])
    assert sc.directories == ["skills"]


def test_logging_config():
    lc = LoggingConfig(level="DEBUG")
    assert lc.level == "DEBUG"
    assert lc.file == ".agent/agent.log"


def test_llm_config_defaults():
    lc = LlmConfig()
    assert lc.provider == "remote"
    assert lc.model == "gpt-4o"
    assert lc.temperature == 0.2


def test_llm_config_local():
    lc = LlmConfig(provider="local", model="codellama:7b", mlx_model_path="/tmp/model")
    assert lc.provider == "local"
    assert lc.mlx_model_path == "/tmp/model"


def test_agent_config_defaults():
    ac = AgentConfig()
    assert ac.max_steps == 50
    assert ac.planner_type == "tree_of_thought"


def test_app_config_defaults():
    ac = AppConfig()
    assert ac.llm.model == "gpt-4o"
    assert ac.agent.max_steps == 50
    assert ac.context.max_tokens == 128000


def test_deep_merge_simple():
    base = {"a": 1, "b": 2}
    override = {"b": 3, "c": 4}
    merged = _deep_merge(base, override)
    assert merged == {"a": 1, "b": 3, "c": 4}


def test_deep_merge_nested():
    base = {"llm": {"model": "gpt-4", "temperature": 0.5}}
    override = {"llm": {"model": "gpt-4o"}}
    merged = _deep_merge(base, override)
    assert merged["llm"]["model"] == "gpt-4o"
    assert merged["llm"]["temperature"] == 0.5


def test_deep_merge_list_replaces():
    base = {"items": [1, 2, 3]}
    override = {"items": [4, 5]}
    merged = _deep_merge(base, override)
    assert merged["items"] == [4, 5]


def test_load_yaml_nonexistent(tmp_path: Path):
    result = _load_yaml(tmp_path / "nonexistent.yaml")
    assert result == {}


def test_load_yaml_valid(tmp_path: Path):
    f = tmp_path / "test.yaml"
    f.write_text("key: value\nnum: 42")
    result = _load_yaml(f)
    assert result == {"key": "value", "num": 42}


def test_load_yaml_not_dict(tmp_path: Path):
    f = tmp_path / "list.yaml"
    f.write_text("- one\n- two")
    result = _load_yaml(f)
    assert result == {}


def test_dict_to_zone_configs():
    raw = {
        "immutable": {"priority": 0, "max_tokens": 4000},
        "working": {"priority": 2, "max_tokens": 8000},
    }
    zones = _dict_to_zone_configs(raw)
    assert zones["immutable"].priority == 0
    assert zones["immutable"].max_tokens == 4000
    assert zones["working"].max_tokens == 8000


def test_dict_to_zone_configs_invalid_value():
    raw = {"custom": "not_a_dict"}
    zones = _dict_to_zone_configs(raw)
    assert zones == {}


def test_build_config_empty():
    cfg = _build_config({})
    assert cfg.llm.model == "gpt-4o"
    assert cfg.agent.max_steps == 50
    assert cfg.rag.enabled is True


def test_build_config_full():
    raw: dict[str, Any] = {
        "llm": {"model": "claude-opus-4", "provider": "remote", "temperature": 0.1},
        "agent": {"max_steps": 25, "planner_type": "flat"},
        "context": {"max_tokens": 64000, "zones": {"working": {"priority": 2, "max_tokens": 5000}}},
        "budget": {"max_fraction_per_step": 0.2, "step_allocations": {"think": 500}},
        "recovery": {"loop_detection_window": 10},
        "tools": {"fs": {"max_read_lines": 200}, "router": {"strategy": "rules_only"}},
        "rag": {"enabled": False, "chunk": {"max_lines": 80}},
        "memory": {"store_path": "/tmp/mem.db"},
        "skills": {"directories": ["skills"]},
        "logging": {"level": "DEBUG"},
    }
    cfg = _build_config(raw)
    assert cfg.llm.model == "claude-opus-4"
    assert cfg.agent.max_steps == 25
    assert cfg.context.max_tokens == 64000
    assert cfg.budget.max_fraction_per_step == 0.2
    assert cfg.budget.step_allocations.think == 500
    assert cfg.recovery.loop_detection_window == 10
    assert cfg.tools.fs.max_read_lines == 200
    assert cfg.tools.router.strategy == "rules_only"
    assert cfg.rag.enabled is False
    assert cfg.rag.chunk.max_lines == 80
    assert cfg.memory.store_path == "/tmp/mem.db"


def test_config_frozen():
    cfg = AppConfig()
    with pytest.raises(AttributeError):
        cfg.llm = LlmConfig()  # type: ignore[misc]


def test_resolve_path(tmp_path: Path):
    cfg = AppConfig(agent=AgentConfig(working_directory=str(tmp_path)))
    result = resolve_path(cfg, "subdir/file.txt")
    assert result == (tmp_path / "subdir/file.txt").resolve()


def test_load_config_returns_app_config():
    cfg = load_config()
    assert isinstance(cfg, AppConfig)
    assert cfg.llm.model is not None


def test_load_config_with_overrides():
    cfg = load_config(overrides={"llm": {"model": "custom-model"}})
    assert cfg.llm.model == "custom-model"


def test_load_config_with_custom_dir(tmp_path: Path):
    base = tmp_path / "base.yaml"
    base.write_text(yaml.dump({"llm": {"model": "base-model"}}))

    profile = tmp_path / "test_profile.yaml"
    profile.write_text(yaml.dump({"llm": {"temperature": 0.5}}))

    cfg = load_config(profile="test_profile", config_dir=tmp_path)
    assert cfg.llm.model == "base-model"
    assert cfg.llm.temperature == 0.5


def test_zone_config_is_frozen():
    zc = ZoneConfig(priority=1, max_tokens=2000)
    with pytest.raises(AttributeError):
        zc.priority = 5  # type: ignore[misc]
