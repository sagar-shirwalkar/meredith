from __future__ import annotations

import pytest

from coding_agent.config import RecoveryConfig
from coding_agent.recovery.detector import LoopDetector
from coding_agent.types import (
    LoopType,
    Step,
    ToolCall,
    ToolResult,
)


@pytest.fixture
def detector() -> LoopDetector:
    return LoopDetector(config=RecoveryConfig())


def _make_step(
    step_number: int,
    tool_name: str | None = None,
    args: dict | None = None,
    success: bool = True,
    error: str | None = None,
    output: str = "ok",
) -> Step:
    tc = ToolCall(id=f"c{step_number}", name=tool_name or "", arguments=args or {}) if tool_name else None
    tr = ToolResult(
        tool_call_id=f"c{step_number}",
        tool_name=tool_name or "",
        output=output,
        success=success,
        error=error,
    ) if tool_name else None
    return Step(
        step_number=step_number,
        thinking="thinking",
        tool_call=tc,
        tool_result=tr,
    )


class TestLoopDetector:
    def test_insufficient_history(self, detector: LoopDetector):
        step = _make_step(1, "read_file", {"path": "test.py"})
        result = detector.check(step)
        assert result is None

    def test_exact_repetition_detected(self, detector: LoopDetector):
        """3 identical tool calls should trigger exact repetition (threshold=2)."""
        args = {"path": "test.py"}
        for i in range(1, 5):
            step = _make_step(i, "read_file", args)
            result = detector.check(step)
        # After 4 identical calls, exact_repetition should have fired (threshold=2)
        assert result is not None
        assert result.loop_type == LoopType.EXACT_REPETITION

    def test_exact_repetition_priority_over_stall(self, detector: LoopDetector):
        """Exact repetition fires first (checked first) even though stall also matches."""
        for i in range(1, 6):
            step = _make_step(i, "read_file", {"path": "test.py"})
            result = detector.check(step)
        assert result is not None
        assert result.loop_type == LoopType.EXACT_REPETITION

    def test_error_loop_with_different_args(self, detector: LoopDetector):
        """Different args but same error should fire error_loop (not exact_repetition)."""
        for i in range(1, 5):
            step = _make_step(
                i, "run_command", {"command": f"cmd_{i}"},
                success=False, error="SyntaxError",
            )
            result = detector.check(step)
        assert result is not None
        assert result.loop_type == LoopType.ERROR_LOOP

    def test_error_loop_normalised(self, detector: LoopDetector):
        """Different line numbers but same error should still match."""
        for i in range(1, 5):
            step = _make_step(
                i, "run_command", {"command": f"test_{i}"},
                success=False,
                error=f"line {i * 10}: SyntaxError",
            )
            result = detector.check(step)
        assert result is not None
        assert result.loop_type == LoopType.ERROR_LOOP

    def test_stall_after_reads(self, detector: LoopDetector):
        """4 read-only steps should trigger stall (no progress)."""
        for i in range(1, 10):
            step = _make_step(i, "read_file", {"path": f"file{i}.py"})
            result = detector.check(step)
        # After many unique reads, exact_repetition won't fire, but stall should
        # (last 4 configured stall_steps steps have no progress)
        assert result is not None
        assert result.loop_type == LoopType.STALL

    def test_no_stall_with_edit(self, detector: LoopDetector):
        """Mix of read and edit should not trigger stall."""
        actions = [
            ("read_file", {"path": "test.py"}),
            ("edit_file", {"path": "test.py", "search": "a", "replace": "b"}),
            ("read_file", {"path": "test.py"}),
            ("edit_file", {"path": "test.py", "search": "b", "replace": "c"}),
            ("read_file", {"path": "test.py"}),
            ("edit_file", {"path": "test.py", "search": "c", "replace": "d"}),
        ]
        for i, (name, args) in enumerate(actions, 1):
            step = _make_step(i, name, args, success=True)
            result = detector.check(step)
        assert result is None or result.loop_type != LoopType.STALL

    def test_fingerprint_consistency(self):
        fp1 = LoopDetector._fingerprint("read_file", {"path": "test.py", "start_line": 1})
        fp2 = LoopDetector._fingerprint("read_file", {"path": "test.py", "start_line": 1})
        assert fp1 == fp2

    def test_fingerprint_different_args(self):
        fp1 = LoopDetector._fingerprint("read_file", {"path": "test.py"})
        fp2 = LoopDetector._fingerprint("read_file", {"path": "other.py"})
        assert fp1 != fp2

    def test_normalise_error(self):
        normalised = LoopDetector._normalise_error(
            "Error at line 42 in /home/user/project/file.py: something"
        )
        assert "line N" in normalised
        assert "<file>.py" in normalised

    def test_normalise_error_empty(self):
        assert LoopDetector._normalise_error("") == ""

    def test_args_are_similar(self):
        """Args with >50% jaccard similarity should be similar."""
        steps = [
            _make_step(1, "search_code", {"pattern": "fix login bug with token"}),
            _make_step(2, "search_code", {"pattern": "fix login bug with auth"}),
        ]
        assert LoopDetector._args_are_similar(steps) is True

    def test_args_not_similar(self):
        """Args with <=50% jaccard similarity should not be similar."""
        steps = [
            _make_step(1, "read_file", {"path": "auth.py"}),
            _make_step(2, "run_command", {"command": "npm test"}),
        ]
        assert LoopDetector._args_are_similar(steps) is False

    def test_args_similar_few_steps(self):
        assert LoopDetector._args_are_similar([]) is False
        assert LoopDetector._args_are_similar([_make_step(1, "read_file", {"path": "x"})]) is False
