from __future__ import annotations

import pytest

from coding_agent.llm.base import (
    LLMClient,
    StreamChunk,
    StreamEvent,
    UsageStats,
    count_messages_tokens,
    count_tokens,
    parse_tool_calls_from_response,
)
from coding_agent.types import Message, Role, ToolCall


class TestUsageStats:
    def test_defaults(self):
        u = UsageStats()
        assert u.prompt_tokens == 0
        assert u.total_tokens == 0

    def test_addition(self):
        a = UsageStats(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        b = UsageStats(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        c = a + b
        assert c.prompt_tokens == 30
        assert c.completion_tokens == 15
        assert c.total_tokens == 45


class TestStreamChunk:
    def test_text_chunk(self):
        chunk = StreamChunk(event=StreamEvent.TEXT, content="Hello")
        assert chunk.event == StreamEvent.TEXT
        assert chunk.content == "Hello"

    def test_tool_call_start(self):
        chunk = StreamChunk(
            event=StreamEvent.TOOL_CALL_START,
            tool_call_id="call_1",
            tool_name="read_file",
        )
        assert chunk.event == StreamEvent.TOOL_CALL_START

    def test_usage_chunk(self):
        usage = UsageStats(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        chunk = StreamChunk(event=StreamEvent.USAGE, usage=usage)
        assert chunk.usage is not None
        assert chunk.usage.total_tokens == 15


class TestCountTokens:
    def test_empty_string(self):
        assert count_tokens("") == 0

    def test_short_text(self):
        n = count_tokens("Hello, world!")
        assert n > 0

    def test_long_text(self):
        n = count_tokens("Hello, world! " * 100)
        assert n > 10

    def test_code_text(self):
        code = 'def foo(x: int) -> str:\n    """Return string."""\n    return str(x)\n'
        n = count_tokens(code)
        assert n > 5


class TestCountMessagesTokens:
    def test_empty(self):
        assert count_messages_tokens([]) == 0

    def test_single_message(self):
        msgs = [Message(role=Role.USER, content="hello")]
        n = count_messages_tokens(msgs)
        assert n > 0

    def test_with_tool_calls(self):
        tc = ToolCall(id="c1", name="read_file", arguments={"path": "test.py"})
        msgs = [Message(role=Role.ASSISTANT, content="", tool_calls=[tc])]
        n = count_messages_tokens(msgs)
        assert n > 0


class TestParseToolCallsFromResponse:
    def test_empty(self):
        assert parse_tool_calls_from_response({}) == []

    def test_single_call(self):
        deltas = {
            "call_1": {
                "name": "read_file",
                "arguments": '{"path": "test.py"}',
            }
        }
        calls = parse_tool_calls_from_response(deltas)
        assert len(calls) == 1
        assert calls[0].id == "call_1"
        assert calls[0].name == "read_file"
        assert calls[0].arguments == {"path": "test.py"}

    def test_multiple_calls(self):
        deltas = {
            "call_1": {"name": "read_file", "arguments": '{"path": "a.py"}'},
            "call_2": {"name": "search_code", "arguments": '{"pattern": "class"}'},
        }
        calls = parse_tool_calls_from_response(deltas)
        assert len(calls) == 2

    def test_invalid_json_fallback(self):
        deltas = {
            "call_1": {
                "name": "read_file",
                "arguments": '{"path": "test.py", invalid}',
            }
        }
        calls = parse_tool_calls_from_response(deltas)
        assert len(calls) == 1
        assert calls[0].arguments == {"_raw": '{"path": "test.py", invalid}'}

    def test_empty_arguments(self):
        deltas = {
            "call_1": {"name": "read_file", "arguments": ""}
        }
        calls = parse_tool_calls_from_response(deltas)
        assert calls[0].arguments == {}

    def test_whitespace_arguments(self):
        deltas = {
            "call_1": {"name": "read_file", "arguments": "  "}
        }
        calls = parse_tool_calls_from_response(deltas)
        assert calls[0].arguments == {}


class TestLLMClientBase:
    def test_abstract_class(self):
        with pytest.raises(TypeError):
            LLMClient(model="test", temperature=0.0, max_tokens=100)  # type: ignore[abstract]

    def test_count_tokens_method(self):
        class MinimalClient(LLMClient):
            async def chat(self, messages, tools=None, temperature=None, max_tokens=None):
                return Message(role=Role.ASSISTANT, content="")

            def chat_stream(self, messages, tools=None, temperature=None, max_tokens=None):
                return iter([])

            async def close(self):
                pass

        client = MinimalClient(model="test", temperature=0.5, max_tokens=100)
        assert client.count_tokens("hello") > 0
        assert client.model == "test"
        assert client.temperature == 0.5
        assert client.max_tokens == 100

    def test_resolve_params_defaults(self):
        class MinimalClient(LLMClient):
            async def chat(self, messages, tools=None, temperature=None, max_tokens=None):
                return Message(role=Role.ASSISTANT, content="")

            def chat_stream(self, messages, tools=None, temperature=None, max_tokens=None):
                return iter([])

            async def close(self):
                pass

        client = MinimalClient(model="test", temperature=0.3, max_tokens=2000)
        temp, mt = client._resolve_params(None, None)
        assert temp == 0.3
        assert mt == 2000

    def test_resolve_params_overrides(self):
        class MinimalClient(LLMClient):
            async def chat(self, messages, tools=None, temperature=None, max_tokens=None):
                return Message(role=Role.ASSISTANT, content="")

            def chat_stream(self, messages, tools=None, temperature=None, max_tokens=None):
                return iter([])

            async def close(self):
                pass

        client = MinimalClient(model="test", temperature=0.3, max_tokens=2000)
        temp, mt = client._resolve_params(temperature=0.9, max_tokens=100)
        assert temp == 0.9
        assert mt == 100

    def test_new_call_id(self):
        class MinimalClient(LLMClient):
            async def chat(self, messages, tools=None, temperature=None, max_tokens=None):
                return Message(role=Role.ASSISTANT, content="")

            def chat_stream(self, messages, tools=None, temperature=None, max_tokens=None):
                return iter([])

            async def close(self):
                pass

        client = MinimalClient(model="test", temperature=0.0, max_tokens=100)
        cid = client._new_call_id()
        assert cid.startswith("call_")
        assert len(cid) > 5
