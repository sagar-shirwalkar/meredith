from __future__ import annotations

from coding_agent.config import AppConfig
from coding_agent.recovery.strategies import LoopRecovery
from coding_agent.types import (
    AgentState,
    LoopDetection,
    LoopType,
    Severity,
    Step,
    ToolCall,
    ToolResult,
)


def _make_detection(
    loop_type: LoopType = LoopType.EXACT_REPETITION,
    severity: Severity = Severity.HIGH,
) -> LoopDetection:
    return LoopDetection(
        loop_type=loop_type,
        severity=severity,
        message="Test loop",
    )


def _make_state(steps: int = 0) -> AgentState:
    state = AgentState(task="Fix the authentication bug")
    for i in range(steps):
        tc = ToolCall(id=f"c{i}", name="read_file", arguments={"path": "test.py"})
        tr = ToolResult(tool_call_id=f"c{i}", tool_name="read_file", output="ok", success=True)
        state.steps.append(Step(step_number=i, thinking="", tool_call=tc, tool_result=tr))
    return state


def test_recover_exact_repetition():
    config = AppConfig()
    recovery = LoopRecovery(llm=None, config=config)  # type: ignore[arg-type]

    # We can call _recover_exact_repetition directly since it doesn't use LLM
    detection = _make_detection(LoopType.EXACT_REPETITION)
    state = _make_state(3)
    action = recovery._recover_exact_repetition(detection, state)

    assert action.inject_message is not None
    assert "CRITICAL" in action.inject_message
    assert action.force_think is True
    assert action.force_user_intervention is True


def test_recover_semantic_loop():
    config = AppConfig()
    recovery = LoopRecovery(llm=None, config=config)  # type: ignore[arg-type]

    detection = _make_detection(LoopType.SEMANTIC_LOOP, Severity.MEDIUM)
    state = _make_state(5)
    # Add repeated actions to the detection
    tc = ToolCall(id="c0", name="search_code", arguments={"pattern": "foo"})
    tr = ToolResult(tool_call_id="c0", tool_name="search_code", output="ok", success=True)
    detection.repeated_actions = [
        Step(step_number=i, thinking="", tool_call=tc, tool_result=tr)
        for i in range(4)
    ]

    action = recovery._recover_semantic_loop(detection, state)
    assert action.inject_message is not None
    assert action.force_think is True
    assert "similar approaches" in action.inject_message


def test_summarise_recent_actions():
    state = _make_state(4)
    summary = LoopRecovery._summarise_recent_actions(state, max_steps=3)
    assert "read_file" in summary
    assert "ok" in summary


def test_summarise_recent_actions_empty():
    state = _make_state(0)
    summary = LoopRecovery._summarise_recent_actions(state)
    assert summary == "(no recent actions)"


def test_summarise_state():
    state = _make_state(3)
    state.files_modified.add("test.py")
    state.last_error = "SyntaxError"
    summary = LoopRecovery._summarise_state(state)
    assert "Fix the authentication bug" in summary
    assert "Steps taken: 3" in summary
    assert "test.py" in summary
    assert "SyntaxError" in summary
