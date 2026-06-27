from __future__ import annotations

import pytest

from coding_agent.agent.verifier import VerificationResult, Verifier
from coding_agent.config import AppConfig
from coding_agent.types import AgentState, Step, ToolCall, ToolResult


@pytest.fixture
def verifier() -> Verifier:
    return Verifier(config=AppConfig())


@pytest.fixture
def state() -> AgentState:
    return AgentState(task="test")


@pytest.mark.asyncio
async def test_tool_success_passes(verifier: Verifier, state: AgentState):
    tc = ToolCall(id="c1", name="read_file", arguments={"path": "test.py"})
    tr = ToolResult(tool_call_id="c1", tool_name="read_file", output="content", success=True)
    step = Step(step_number=1, thinking="", tool_call=tc, tool_result=tr)
    result = await verifier.verify(step, state)
    assert result.passed is True


@pytest.mark.asyncio
async def test_tool_failure_detected(verifier: Verifier, state: AgentState):
    tc = ToolCall(id="c1", name="edit_file", arguments={"path": "test.py"})
    tr = ToolResult(
        tool_call_id="c1", tool_name="edit_file", output="error",
        success=False, error="file not found",
    )
    step = Step(step_number=1, thinking="", tool_call=tc, tool_result=tr)
    result = await verifier.verify(step, state)
    assert result.passed is False
    assert "file not found" in result.message


@pytest.mark.asyncio
async def test_edit_sanity_same_search_replace(verifier: Verifier, state: AgentState):
    tc = ToolCall(id="c1", name="edit_file", arguments={"search": "foo", "replace": "foo"})
    tr = ToolResult(tool_call_id="c1", tool_name="edit_file", output="ok", success=True)
    step = Step(step_number=1, thinking="", tool_call=tc, tool_result=tr)
    result = await verifier.verify(step, state)
    assert result.passed is False
    assert "no effect" in result.message


@pytest.mark.asyncio
async def test_write_sanity_short_content(verifier: Verifier, state: AgentState):
    tc = ToolCall(id="c1", name="write_file", arguments={"path": "test.py", "content": "x"})
    tr = ToolResult(tool_call_id="c1", tool_name="write_file", output="ok", success=True)
    step = Step(step_number=1, thinking="", tool_call=tc, tool_result=tr)
    result = await verifier.verify(step, state)
    assert result.passed is False
    assert "too short" in result.message


@pytest.mark.asyncio
async def test_write_sanity_good_content(verifier: Verifier, state: AgentState):
    # Use a path that won't trigger diagnostics (no file extension check for non-code files)
    tc = ToolCall(
        id="c1", name="write_file",
        arguments={"path": "test.md", "content": "def foo():\n    pass\n"},
    )
    tr = ToolResult(tool_call_id="c1", tool_name="write_file", output="ok", success=True)
    step = Step(step_number=1, thinking="", tool_call=tc, tool_result=tr)
    result = await verifier.verify(step, state)
    assert result.passed is True


@pytest.mark.asyncio
async def test_read_efficiency_warning(verifier: Verifier, state: AgentState):
    tc = ToolCall(id="c1", name="read_file", arguments={"path": "test.py"})
    tr = ToolResult(tool_call_id="c1", tool_name="read_file", output="content", success=True)
    for i in range(3):
        prev_tc = ToolCall(id=f"c{i}", name="read_file", arguments={"path": "test.py"})
        prev_tr = ToolResult(tool_call_id=f"c{i}", tool_name="read_file", output="c", success=True)
        state.steps.append(Step(step_number=i, thinking="", tool_call=prev_tc, tool_result=prev_tr))
    step = Step(step_number=4, thinking="", tool_call=tc, tool_result=tr)
    result = await verifier.verify(step, state)
    assert result.passed is True  # warning only
    assert "multiple times" in result.message


@pytest.mark.asyncio
async def test_no_tool_call_step(verifier: Verifier, state: AgentState):
    step = Step(step_number=1, thinking="just thinking")
    result = await verifier.verify(step, state)
    assert result.passed is True


@pytest.mark.asyncio
async def test_no_tool_result(verifier: Verifier, state: AgentState):
    tc = ToolCall(id="c1", name="read_file", arguments={"path": "test.py"})
    step = Step(step_number=1, thinking="", tool_call=tc)
    result = await verifier.verify(step, state)
    assert result.passed is True


def test_verification_result_creation():
    vr = VerificationResult(passed=True, message="OK", checks=["check1"], issues=[])
    assert vr.passed is True
    assert vr.message == "OK"
