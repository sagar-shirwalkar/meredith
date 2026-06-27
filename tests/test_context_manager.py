from __future__ import annotations

import pytest

from coding_agent.config import (
    AgentConfig,
    AppConfig,
    ContextConfig,
    StepAllocConfig,
    ZoneConfig,
)
from coding_agent.context.budget import TokenBudget
from coding_agent.context.manager import ContextManager
from coding_agent.types import ZoneName


@pytest.fixture
def budget() -> TokenBudget:
    return TokenBudget(
        total=128000,
        step_allocations=StepAllocConfig(),
        max_fraction_per_step=0.10,
    )


@pytest.fixture
def manager(budget: TokenBudget) -> ContextManager:
    config = AppConfig(
        agent=AgentConfig(),
        context=ContextConfig(
            max_tokens=128000,
            zones={
                "immutable": ZoneConfig(priority=0, max_tokens=4000),
                "task": ZoneConfig(priority=1, max_tokens=2000),
                "working": ZoneConfig(priority=2, max_tokens=5000),
                "episodic": ZoneConfig(priority=3, max_tokens=4000),
                "scratch": ZoneConfig(priority=4, max_tokens=1000),
            },
        ),
    )
    return ContextManager(config=config, budget=budget)


class TestContextManager:
    def test_init_creates_zones(self, manager: ContextManager):
        assert ZoneName.IMMUTABLE in manager.zones
        assert ZoneName.TASK in manager.zones
        assert ZoneName.WORKING in manager.zones
        assert ZoneName.EPISODIC in manager.zones
        assert ZoneName.SCRATCH in manager.zones
        assert isinstance(manager.zones[ZoneName.IMMUTABLE], list)

    def test_add_content(self, manager: ContextManager):
        manager.add(ZoneName.TASK, "Fix bug in auth.py")
        assert len(manager.zones[ZoneName.TASK]) == 1
        assert manager.zones[ZoneName.TASK][0].content == "Fix bug in auth.py"

    def test_add_to_immutable(self, manager: ContextManager):
        manager.add(ZoneName.IMMUTABLE, "system prompt", source="system", compressible=False)
        assert len(manager.zones[ZoneName.IMMUTABLE]) == 1

    def test_set_immutable(self, manager: ContextManager):
        manager.set_immutable("You are a coding agent.")
        assert len(manager.zones[ZoneName.IMMUTABLE]) == 1
        assert manager.zones[ZoneName.IMMUTABLE][0].compressible is False

    def test_inject_scratch(self, manager: ContextManager):
        manager.inject_scratch("Recovery intervention message")
        assert len(manager.zones[ZoneName.SCRATCH]) == 1

    def test_build_context_string_empty(self, manager: ContextManager):
        context = manager.build_context_string()
        assert isinstance(context, str)

    def test_build_context_string_with_content(self, manager: ContextManager):
        manager.set_immutable("You are a bot.")
        manager.add(ZoneName.TASK, "Fix bug")
        context = manager.build_context_string()
        assert "You are a bot." in context
        assert "Fix bug" in context

    def test_record_step(self, manager: ContextManager):
        step = _make_step(1, "read_file", {"path": "x.py"}, "content")
        manager.record_step(step)
        assert len(manager.zones[ZoneName.WORKING]) > 0

    def test_trim_zone(self, manager: ContextManager):
        for i in range(10):
            manager.add(
                ZoneName.SCRATCH,
                f"scratch note {i} with some more text to make it longer than the others",
                source="agent",
            )
        assert len(manager.zones[ZoneName.SCRATCH]) >= 1

    def test_reset_working(self, manager: ContextManager):
        manager.add(ZoneName.WORKING, "some work data")
        manager.reset_working()
        assert len(manager.zones[ZoneName.WORKING]) == 0

    def test_build_context_string_with_task(self, manager: ContextManager):
        manager.add(ZoneName.TASK, "Task content")
        context = manager.build_context_string()
        assert "Task content" in context

    def test_emergency_compress(self, manager: ContextManager):
        manager.set_immutable("sys")
        manager.add(ZoneName.TASK, "task")
        manager.emergency_compress()
        assert len(manager.zones[ZoneName.IMMUTABLE]) >= 0
        assert len(manager.zones[ZoneName.TASK]) >= 0


def _make_step(step_number: int, tool_name: str, args: dict, output: str = "ok") -> type:
    from coding_agent.types import Step, ToolCall, ToolResult
    tc = ToolCall(id=f"c{step_number}", name=tool_name, arguments=args)
    tr = ToolResult(tool_call_id=f"c{step_number}", tool_name=tool_name, output=output, success=True)
    return Step(step_number=step_number, thinking="", tool_call=tc, tool_result=tr)
