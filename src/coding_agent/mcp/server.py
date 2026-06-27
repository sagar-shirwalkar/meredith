"""
MCP Server: exposes the coding agent's tools over the
Model Context Protocol so that editors like Zed and Opencode
can invoke them.

Implements the MCP stdio transport.  The server reads JSON-RPC
messages from stdin and writes responses to stdout.

Protocol reference:
  - initialize    → server info + capabilities
  - tools/list    → list available tools
  - tools/call    → execute a tool
  - resources/list → list readable resources (files, etc.)
  - resources/read → read a resource

Usage (standalone):
    python -m coding_agent.mcp.server --profile local_model

Usage (from Zed/Opencode settings):
    Point the editor's MCP configuration to this script.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from coding_agent.config import load_config
from coding_agent.tools.base import ToolRegistry
from coding_agent.types import ToolCall

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# MCP protocol types
# ──────────────────────────────────────────────────────────────

_MCP_VERSION = "2024-11-05"

_SERVER_INFO = {
    "name": "coding-agent",
    "version": "0.1.0",
}

_CAPABILITIES = {
    "tools": {"listChanged": False},
    "resources": {"subscribe": False, "listChanged": False},
}


# ──────────────────────────────────────────────────────────────
# MCP Server implementation
# ──────────────────────────────────────────────────────────────


class MCPServer:
    """
    MCP server that exposes the agent's tools over stdio JSON-RPC.

    This is a lightweight implementation — it handles the core
    protocol messages needed for editor integration but does not
    implement the full MCP spec (e.g. no sampling, no logging).
    """

    def __init__(self, profile: str = "large_model") -> None:
        self.profile = profile
        self._config = load_config(profile)
        self._registry = ToolRegistry(self._config)
        self._initialized = False

    async def start(self) -> None:
        """Set up the tool registry and start the message loop."""
        await self._registry.setup()
        logger.info("MCP server ready: %d tools registered", len(self._registry.schemas))
        await self._message_loop()

    async def _message_loop(self) -> None:
        """
        Main loop: read JSON-RPC messages from stdin, dispatch
        to handlers, and write responses to stdout.
        """
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_event_loop())

        while True:
            try:
                line = await reader.readline()
                if not line:
                    break

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                try:
                    message = json.loads(line_str)
                except json.JSONDecodeError:
                    await self._write_error(writer, None, -32700, "Parse error")
                    continue

                response = await self._handle_message(message)

                if response is not None:
                    response_bytes = (json.dumps(response) + "\n").encode("utf-8")
                    writer.write(response_bytes)
                    await writer.drain()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Error in message loop: %s", exc)

    async def _handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Route a JSON-RPC message to the appropriate handler."""
        method = message.get("method", "")
        params = message.get("params", {})
        msg_id = message.get("id")

        if method == "initialize":
            self._initialized = True
            return self._success_response(msg_id, {
                "protocolVersion": _MCP_VERSION,
                "capabilities": _CAPABILITIES,
                "serverInfo": _SERVER_INFO,
            })

        if not self._initialized:
            return self._error_response(msg_id, -32002, "Server not initialized")

        if method == "notifications/initialized":
            # Client acknowledgment — no response needed
            return None

        if method == "tools/list":
            return self._handle_tools_list(msg_id)

        if method == "tools/call":
            return await self._handle_tools_call(msg_id, params)

        if method == "resources/list":
            return self._handle_resources_list(msg_id)

        if method == "resources/read":
            return await self._handle_resources_read(msg_id, params)

        if method == "ping":
            return self._success_response(msg_id, {})

        return self._error_response(msg_id, -32601, f"Method not found: {method}")

    # ── Handler: tools/list ───────────────────────────────────

    def _handle_tools_list(self, msg_id: Any) -> dict[str, Any]:
        """Return the list of available tools in MCP format."""
        tools = []
        for schema in self._registry.schemas.values():
            input_schema = schema.to_openai_dict().get("function", {}).get("parameters", {})
            tools.append({
                "name": schema.name,
                "description": schema.description,
                "inputSchema": input_schema,
            })

        return self._success_response(msg_id, {"tools": tools})

    # ── Handler: tools/call ───────────────────────────────────

    async def _handle_tools_call(
        self,
        msg_id: Any,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool call and return the result."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if not tool_name:
            return self._error_response(msg_id, -32602, "Missing tool name")

        call = ToolCall(
            id=f"mcp_{msg_id}",
            name=tool_name,
            arguments=arguments,
        )

        result = await self._registry.execute(call)

        # Format result for MCP
        content_items = []
        if result.success:
            content_items.append({
                "type": "text",
                "text": result.output,
            })
        else:
            content_items.append({
                "type": "text",
                "text": f"Error: {result.error or result.output}",
            })

        return self._success_response(msg_id, {
            "content": content_items,
            "isError": not result.success,
        })

    # ── Handler: resources/list ───────────────────────────────

    def _handle_resources_list(self, msg_id: Any) -> dict[str, Any]:
        """
        Return the list of readable resources.

        Exposes the project's AGENTS.md and SKILL.md files as
        resources that the editor can read.
        """
        from pathlib import Path

        resources = []
        workdir = Path(self._config.agent.working_directory).resolve()

        # AGENTS.md
        agents_md = workdir / "AGENTS.md"
        if agents_md.exists():
            resources.append({
                "uri": f"file://{agents_md}",
                "name": "AGENTS.md",
                "description": "Project instructions for the AI agent",
                "mimeType": "text/markdown",
            })

        # Skills
        for skill_dir in self._config.skills.directories:
            skills_path = workdir / skill_dir
            if skills_path.exists():
                for skill_md in skills_path.rglob("SKILL.md"):
                    rel = skill_md.relative_to(workdir)
                    resources.append({
                        "uri": f"file://{skill_md}",
                        "name": str(rel),
                        "description": f"Agent skill: {skill_md.parent.name}",
                        "mimeType": "text/markdown",
                    })

        return self._success_response(msg_id, {"resources": resources})

    # ── Handler: resources/read ───────────────────────────────

    async def _handle_resources_read(
        self,
        msg_id: Any,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Read a resource by URI."""
        uri = params.get("uri", "")

        if not uri.startswith("file://"):
            return self._error_response(msg_id, -32602, f"Unsupported URI scheme: {uri}")

        from pathlib import Path
        file_path = Path(uri[7:])

        if not file_path.exists():
            return self._error_response(msg_id, -32602, f"Resource not found: {uri}")

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            return self._error_response(msg_id, -32603, f"Cannot read resource: {exc}")

        return self._success_response(msg_id, {
            "contents": [{
                "uri": uri,
                "mimeType": "text/markdown",
                "text": content,
            }],
        })

    # ── JSON-RPC helpers ──────────────────────────────────────

    @staticmethod
    def _success_response(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        """Build a successful JSON-RPC response."""
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": result,
        }

    @staticmethod
    def _error_response(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        """Build an error JSON-RPC response."""
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }

    @staticmethod
    async def _write_error(
        writer: asyncio.StreamWriter,
        msg_id: Any,
        code: int,
        message: str,
    ) -> None:
        """Write an error response to the output stream."""
        response = MCPServer._error_response(msg_id, code, message)
        writer.write((json.dumps(response) + "\n").encode("utf-8"))
        await writer.drain()


# ──────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────


def main() -> None:
    """Run the MCP server as a standalone process."""
    import argparse

    parser = argparse.ArgumentParser(description="Coding Agent MCP Server")
    parser.add_argument(
        "--profile", "-p",
        default="large_model",
        choices=["large_model", "local_model"],
        help="Configuration profile",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    server = MCPServer(profile=args.profile)
    asyncio.run(server.start())


if __name__ == "__main__":
    main()
