from __future__ import annotations

import asyncio

import pytest

from coding_agent.config import AppConfig
from coding_agent.tools.base import ToolRegistry
from coding_agent.types import ToolCall, ToolSchema


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry(config=AppConfig())
    asyncio.run(reg.setup())
    return reg


class TestToolRegistry:
    def test_setup_registers_tools(self, registry: ToolRegistry):
        assert len(registry.schemas) > 0
        assert "read_file" in registry.schemas
        assert "edit_file" in registry.schemas
        assert "write_file" in registry.schemas
        assert "search_code" in registry.schemas
        assert "git_status" in registry.schemas
        assert "web_search" in registry.schemas

    def test_setup_is_idempotent(self, registry: ToolRegistry):
        count = len(registry.schemas)
        asyncio.run(registry.setup())
        assert len(registry.schemas) == count

    def test_execute_known_tool(self, registry: ToolRegistry):
        call = ToolCall(id="c1", name="list_directory", arguments={"path": "."})
        result = asyncio.run(registry.execute(call))
        assert result.success is True
        assert result.tool_name == "list_directory"

    def test_execute_unknown_tool(self, registry: ToolRegistry):
        call = ToolCall(id="c1", name="nonexistent_tool", arguments={})
        result = asyncio.run(registry.execute(call))
        assert result.success is False
        assert "unknown" in result.error

    def test_available_tool_names(self, registry: ToolRegistry):
        names = registry.available_tool_names()
        assert "read_file" in names
        assert sorted(names) == names

    def test_get_schemas_for_names(self, registry: ToolRegistry):
        schemas = registry.get_schemas_for_names(["read_file", "edit_file"])
        assert len(schemas) == 2
        assert isinstance(schemas[0], ToolSchema)

    def test_get_schemas_for_names_skips_unknown(self, registry: ToolRegistry):
        schemas = registry.get_schemas_for_names(["read_file", "nonexistent"])
        assert len(schemas) == 1
