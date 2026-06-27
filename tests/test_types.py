from __future__ import annotations

from coding_agent.types import (
    AgentState,
    CodeChunk,
    ContextItem,
    LoopDetection,
    LoopType,
    Message,
    Plan,
    RecoveryAction,
    Role,
    SearchResult,
    Severity,
    Step,
    SubTask,
    Symbol,
    SymbolKind,
    TaskStatus,
    ToolCall,
    ToolParameter,
    ToolResult,
    ToolSchema,
    ZoneName,
    _python_type_to_json,
)


def test_role_enum():
    assert Role.SYSTEM == "system"
    assert Role.USER == "user"
    assert Role.ASSISTANT == "assistant"
    assert Role.TOOL == "tool"


def test_task_status_enum():
    assert TaskStatus.PENDING == "pending"
    assert TaskStatus.COMPLETED == "completed"


def test_loop_type_enum():
    assert LoopType.EXACT_REPETITION == "exact_repetition"
    assert LoopType.STALL == "stall"


def test_severity_enum():
    assert Severity.HIGH == "high"
    assert Severity.LOW == "low"


def test_symbol_kind_enum():
    assert SymbolKind.FUNCTION == "function"
    assert SymbolKind.CLASS == "class"


def test_zone_name_enum():
    assert ZoneName.IMMUTABLE == "immutable"
    assert ZoneName.TASK == "task"
    assert ZoneName.WORKING == "working"


def test_message_creation():
    msg = Message(role=Role.USER, content="test")
    assert msg.role == Role.USER
    assert msg.content == "test"
    assert msg.timestamp > 0
    assert msg.tool_calls is None
    assert msg.tool_call_id is None


def _test_message_token_estimate_prose():
    msg = Message(role=Role.USER, content="hello world how are you doing today")
    estimate = msg.token_estimate()
    assert estimate > 0


def _test_message_token_estimate_code():
    msg = Message(role=Role.USER, content="def foo(x: int) -> str: return str(x)")
    estimate = msg.token_estimate()
    assert estimate > 0


def test_message_token_estimate_empty():
    msg = Message(role=Role.USER, content="")
    assert msg.token_estimate() == 0


def test_message_with_tool_calls():
    tc = ToolCall(id="call_1", name="read_file", arguments={"path": "test.py"})
    msg = Message(role=Role.ASSISTANT, content="", tool_calls=[tc])
    assert msg.tool_calls is not None
    assert len(msg.tool_calls) == 1


def test_tool_parameter_defaults():
    tp = ToolParameter(name="test", type="str", description="A test param")
    assert tp.required is True
    assert tp.default is None
    assert tp.enum is None


def test_tool_parameter_optional():
    tp = ToolParameter(
        name="test", type="int", description="Optional", required=False, default=42
    )
    assert tp.required is False
    assert tp.default == 42


def test_tool_schema_to_openai_dict():
    schema = ToolSchema(
        name="my_tool",
        description="Does something",
        parameters=[
            ToolParameter(name="input", type="str", description="Input"),
            ToolParameter(name="flag", type="bool", description="Flag", required=False),
            ToolParameter(name="choice", type="str", description="Pick one", enum=["a", "b"]),
        ],
    )
    result = schema.to_openai_dict()
    assert result["type"] == "function"
    fn = result["function"]
    assert fn["name"] == "my_tool"
    assert "input" in fn["parameters"]["properties"]
    assert "input" in fn["parameters"]["required"]
    assert "flag" not in fn["parameters"]["required"]
    assert fn["parameters"]["properties"]["choice"]["enum"] == ["a", "b"]


def test_tool_schema_to_openai_dict_no_params():
    schema = ToolSchema(name="empty", description="No params", parameters=[])
    result = schema.to_openai_dict()
    assert result["function"]["parameters"]["properties"] == {}
    assert result["function"]["parameters"]["required"] == []


def test_tool_call_creation():
    tc = ToolCall(id="call_1", name="search_code", arguments={"pattern": "def foo"})
    assert tc.id == "call_1"
    assert tc.name == "search_code"


def test_tool_result_creation():
    tr = ToolResult(
        tool_call_id="call_1",
        tool_name="search_code",
        output="Found 3 matches",
        success=True,
        token_count=10,
        duration_seconds=0.5,
    )
    assert tr.success is True
    assert tr.error is None
    assert tr.token_count == 10


def test_tool_result_defaults():
    tr = ToolResult(tool_call_id="c1", tool_name="t", output="out")
    assert tr.success is True
    assert tr.error is None
    assert tr.token_count == 0
    assert tr.duration_seconds == 0.0


def test_subtask_creation():
    st = SubTask(id=1, description="Do something", files=["src/main.py"])
    assert st.status == TaskStatus.PENDING
    assert st.result_summary == ""


def test_plan_creation():
    st1 = SubTask(id=1, description="Step 1")
    st2 = SubTask(id=2, description="Step 2", files=["file2.py"])
    plan = Plan(goal="Test goal", subtasks=[st1, st2], dependencies={2: [1]})
    assert plan.current_subtask is None
    assert plan.current_subtask_idx == -1


def test_plan_advance():
    st1 = SubTask(id=1, description="Step 1")
    st2 = SubTask(id=2, description="Step 2")
    plan = Plan(goal="Test", subtasks=[st1, st2])
    next_st = plan.advance()
    assert next_st is not None
    assert next_st.id == 1
    assert next_st.status == TaskStatus.IN_PROGRESS
    assert plan.current_subtask_idx == 0


def test_plan_advance_all_done():
    st1 = SubTask(id=1, description="Step 1", status=TaskStatus.COMPLETED)
    plan = Plan(goal="Test", subtasks=[st1])
    next_st = plan.advance()
    assert next_st is None


def test_plan_advance_dependency_not_met():
    st1 = SubTask(id=1, description="Step 1")
    st2 = SubTask(id=2, description="Step 2")
    plan = Plan(goal="Test", subtasks=[st1, st2], dependencies={2: [1]})
    # st1 has no dependency, should be returned
    next_st = plan.advance()
    assert next_st is not None
    assert next_st.id == 1
    st1.status = TaskStatus.COMPLETED
    next_st = plan.advance()
    assert next_st is not None
    assert next_st.id == 2


def test_plan_current_subtask():
    st = SubTask(id=1, description="Step 1")
    plan = Plan(goal="Test", subtasks=[st])
    assert plan.current_subtask is None
    plan.advance()
    assert plan.current_subtask is not None
    assert plan.current_subtask.id == 1


def test_step_creation():
    tc = ToolCall(id="c1", name="read_file", arguments={"path": "test.py"})
    tr = ToolResult(tool_call_id="c1", tool_name="read_file", output="content")
    step = Step(step_number=1, thinking="Let me read", tool_call=tc, tool_result=tr)
    assert step.step_number == 1
    assert step.summary().startswith("Step 1:")


def test_step_summary_no_tool():
    step = Step(step_number=1, thinking="Just thinking")
    assert "reasoning" in step.summary()


def test_step_arg_summary():
    tc = ToolCall(id="c1", name="read_file", arguments={"path": "/long/path/to/file.py"})
    tr = ToolResult(tool_call_id="c1", tool_name="read_file", output="ok")
    step = Step(step_number=1, thinking="", tool_call=tc, tool_result=tr)
    summary = step.summary()
    assert "read_file" in summary


def test_agent_state_creation():
    state = AgentState(task="Fix the bug")
    assert state.task == "Fix the bug"
    assert state.step_count == 0
    assert state.files_modified == set()
    assert state.last_error is None


def test_agent_state_record_step():
    state = AgentState(task="Test")
    tc = ToolCall(id="c1", name="read_file", arguments={})
    tr = ToolResult(tool_call_id="c1", tool_name="read_file", output="ok", token_count=50)
    step = Step(step_number=1, thinking="", tool_call=tc, tool_result=tr)
    state.record_step(step)
    assert state.step_count == 1
    assert state.total_tokens_used == 50


def test_agent_state_record_step_error():
    state = AgentState(task="Test")
    tc = ToolCall(id="c1", name="edit_file", arguments={"path": "x.py"})
    tr = ToolResult(
        tool_call_id="c1", tool_name="edit_file", output="error",
        success=False, error="file not found",
    )
    step = Step(step_number=1, thinking="", tool_call=tc, tool_result=tr)
    state.record_step(step)
    assert state.last_error == "file not found"


def test_loop_detection_creation():
    ld = LoopDetection(
        loop_type=LoopType.EXACT_REPETITION,
        severity=Severity.HIGH,
        message="Repeated action",
    )
    assert ld.loop_type == LoopType.EXACT_REPETITION


def test_recovery_action():
    ra = RecoveryAction(inject_message="Try something else", force_think=True)
    assert ra.inject_message == "Try something else"
    assert ra.force_think is True
    assert ra.max_retries == -1


def test_symbol_creation():
    sym = Symbol(
        name="my_func",
        kind=SymbolKind.FUNCTION,
        file_path="src/main.py",
        line_start=10,
        line_end=20,
        signature="def my_func(x: int) -> str",
    )
    assert sym.name == "my_func"
    assert sym.docstring == ""


def test_code_chunk_creation():
    chunk = CodeChunk(
        file_path="src/main.py",
        line_start=1,
        line_end=10,
        content="def foo():\n    pass",
    )
    assert chunk.symbol_name is None
    assert chunk.token_frequencies == {}


def test_search_result_creation():
    sr = SearchResult(
        content="def foo(): pass",
        file_path="src/main.py",
        line_start=1,
        line_end=1,
        score=0.95,
    )
    assert sr.source == "bm25"


def test_context_item_creation():
    ci = ContextItem(content="Some content", source="tool_result", token_count=50)
    assert ci.compressible is True
    assert ci.timestamp > 0


def test_context_item_not_compressible():
    ci = ContextItem(
        content="System prompt", source="system", token_count=100, compressible=False
    )
    assert ci.compressible is False


def test_python_type_to_json():
    assert _python_type_to_json("str") == "string"
    assert _python_type_to_json("int") == "integer"
    assert _python_type_to_json("bool") == "boolean"
    assert _python_type_to_json("list[str]") == "array"
    assert _python_type_to_json("dict") == "object"
    assert _python_type_to_json("unknown") == "string"


def test_step_default_timestamp():
    step = Step(step_number=1, thinking="test")
    assert step.timestamp > 0
    assert step.tool_call is None
    assert step.tool_result is None
