from __future__ import annotations

import asyncio

import pytest

from coding_agent.config import (
    AppConfig,
    RouterConfig,
    ToolsConfig,
)
from coding_agent.tools.base import ToolRegistry
from coding_agent.tools.router import ToolRouter
from coding_agent.types import AgentState, ToolCall, ToolResult


@pytest.fixture
def config() -> AppConfig:
    return AppConfig()


@pytest.fixture
def registry(config: AppConfig) -> ToolRegistry:
    reg = ToolRegistry(config=config)
    asyncio.run(reg.setup())
    return reg


@pytest.fixture
def router(config: AppConfig, registry: ToolRegistry) -> ToolRouter:
    return ToolRouter(config=config, registry=registry)


@pytest.fixture
def state() -> AgentState:
    return AgentState(task="Fix the bug in auth.py")


class TestToolRouter:
    def test_get_available_tools_base(self, router: ToolRouter, state: AgentState):
        tools = router.get_available_tools(state)
        assert "read_file" in tools
        assert "edit_file" in tools
        assert "search_code" in tools

    def test_get_available_tools_rules_only_exploration(self, state: AgentState):
        """Early steps (<5) should include exploration tools even in rules_only."""
        config = AppConfig(tools=ToolsConfig(router=RouterConfig(strategy="rules_only")))
        reg = ToolRegistry(config=config)
        asyncio.run(reg.setup())
        router = ToolRouter(config=config, registry=reg)
        tools = router.get_available_tools(state)
        assert "find_symbols" in tools  # step_count=0 < 5
        assert "web_search" not in tools  # only added when task mentions search

    def test_get_available_tools_rules_only_web_search(self, state: AgentState):
        config = AppConfig(tools=ToolsConfig(router=RouterConfig(strategy="rules_only")))
        reg = ToolRegistry(config=config)
        asyncio.run(reg.setup())
        router = ToolRouter(config=config, registry=reg)
        state.task = "search for documentation"
        tools = router.get_available_tools(state)
        assert "web_search" in tools

    def test_get_available_tools_rules_only_later_steps(self):
        config = AppConfig(tools=ToolsConfig(router=RouterConfig(strategy="rules_only")))
        reg = ToolRegistry(config=config)
        asyncio.run(reg.setup())
        router = ToolRouter(config=config, registry=reg)
        state = AgentState(task="Fix bug")
        from coding_agent.types import Step
        for i in range(10):
            state.steps.append(Step(step_number=i, thinking=""))
        tools = router.get_available_tools(state)
        assert "find_symbols" not in tools

    def test_pre_execute_read_file_defaults(self, router: ToolRouter):
        call = ToolCall(id="c1", name="read_file", arguments={"path": "test.py"})
        result = router.pre_execute(call)
        assert result.arguments.get("start_line") == 1
        assert result.arguments.get("end_line") == 80

    def test_pre_execute_read_file_adjusts_end(self, router: ToolRouter):
        call = ToolCall(id="c1", name="read_file", arguments={"path": "test.py", "start_line": 10})
        result = router.pre_execute(call)
        assert result.arguments["end_line"] == 10 + 80 - 1

    def test_pre_execute_read_file_clamp(self, router: ToolRouter):
        call = ToolCall(
            id="c1", name="read_file",
            arguments={"path": "test.py", "start_line": 10, "end_line": 200},
        )
        result = router.pre_execute(call)
        assert result.arguments["end_line"] <= 10 + 80 - 1

    def test_pre_execute_run_command_default_timeout(self, router: ToolRouter):
        call = ToolCall(id="c1", name="run_command", arguments={"command": "echo hello"})
        result = router.pre_execute(call)
        assert result.arguments.get("timeout") == 120

    def test_pre_execute_run_command_preserves_timeout(self, router: ToolRouter):
        call = ToolCall(
            id="c1", name="run_command",
            arguments={"command": "echo hello", "timeout": 30},
        )
        result = router.pre_execute(call)
        assert result.arguments["timeout"] == 30

    def test_pre_execute_search_code_sets_max(self, router: ToolRouter):
        call = ToolCall(id="c1", name="search_code", arguments={"pattern": "def"})
        result = router.pre_execute(call)
        assert result.arguments.get("max_results") == 30

    def test_pre_execute_unknown_passthrough(self, router: ToolRouter):
        call = ToolCall(id="c1", name="nonexistent", arguments={"a": 1})
        result = router.pre_execute(call)
        assert result.arguments == call.arguments

    def test_post_execute_command_large_output(self, router: ToolRouter):
        """Large output (>6000 chars or >80 lines) should be truncated."""
        long_output = "\n".join(f"line {i} " + "x" * 50 for i in range(200))
        result = ToolResult(
            tool_call_id="c1", tool_name="run_command",
            output=long_output, success=True,
        )
        call = ToolCall(id="c1", name="run_command", arguments={"command": "test"})
        truncated = router.post_execute(call, result)
        assert "lines omitted" in truncated.output

    def test_post_execute_command_short_output(self, router: ToolRouter):
        result = ToolResult(
            tool_call_id="c1", tool_name="run_command",
            output="short output", success=True,
        )
        call = ToolCall(id="c1", name="run_command", arguments={"command": "test"})
        unchanged = router.post_execute(call, result)
        assert unchanged.output == "short output"

    def test_should_auto_run_diagnostics_python(self, router: ToolRouter):
        call = ToolCall(id="c1", name="edit_file", arguments={"path": "test.py"})
        assert router.should_auto_run_diagnostics(call) is True

    def test_should_auto_run_diagnostics_not_edit(self, router: ToolRouter):
        call = ToolCall(id="c1", name="read_file", arguments={"path": "test.py"})
        assert router.should_auto_run_diagnostics(call) is False

    def test_should_auto_run_diagnostics_non_python(self, router: ToolRouter):
        call = ToolCall(id="c1", name="edit_file", arguments={"path": "test.js"})
        assert router.should_auto_run_diagnostics(call) is False

    def test_pre_execute_search_code_clamps_high(self, router: ToolRouter):
        call = ToolCall(id="c1", name="search_code", arguments={"pattern": "def", "max_results": 100})
        result = router.pre_execute(call)
        # max * 2 = 60, so it should clamp
        assert result.arguments["max_results"] <= 60
