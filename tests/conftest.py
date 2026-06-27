from __future__ import annotations

import pytest

from coding_agent.config import AppConfig, load_config
from coding_agent.llm.base import StreamChunk, StreamEvent
from coding_agent.types import (
    Message,
    Role,
    Step,
    ToolCall,
    ToolParameter,
    ToolResult,
    ToolSchema,
)


@pytest.fixture
def app_config() -> AppConfig:
    return load_config(profile="large_model")


@pytest.fixture
def sample_message() -> Message:
    return Message(role=Role.USER, content="Hello, agent!")


@pytest.fixture
def sample_tool_call() -> ToolCall:
    return ToolCall(id="call_abc123", name="read_file", arguments={"path": "test.py"})


@pytest.fixture
def sample_tool_result() -> ToolResult:
    return ToolResult(
        tool_call_id="call_abc123",
        tool_name="read_file",
        output="def foo():\n    pass\n",
        success=True,
    )


@pytest.fixture
def sample_step(sample_tool_call: ToolCall, sample_tool_result: ToolResult) -> Step:
    return Step(
        step_number=1,
        thinking="Let me read the file first.",
        tool_call=sample_tool_call,
        tool_result=sample_tool_result,
    )


@pytest.fixture
def sample_tool_schema() -> ToolSchema:
    return ToolSchema(
        name="test_tool",
        description="A test tool",
        parameters=[
            ToolParameter(name="input", type="str", description="Input value"),
        ],
    )


@pytest.fixture
def stream_chunk_text() -> StreamChunk:
    return StreamChunk(event=StreamEvent.TEXT, content="Hello")


@pytest.fixture
def stream_chunk_tool_start() -> StreamChunk:
    return StreamChunk(
        event=StreamEvent.TOOL_CALL_START,
        tool_call_id="call_1",
        tool_name="read_file",
    )


@pytest.fixture
def stream_chunk_tool_delta() -> StreamChunk:
    return StreamChunk(
        event=StreamEvent.TOOL_CALL_DELTA,
        tool_call_id="call_1",
        tool_arguments_delta='{"path": "',
    )


@pytest.fixture
def stream_chunk_done() -> StreamChunk:
    return StreamChunk(event=StreamEvent.DONE)
