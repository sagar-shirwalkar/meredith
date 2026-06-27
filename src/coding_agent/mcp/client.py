"""
MCP Client: connects to external MCP servers to discover and
use their tools.

This allows the coding agent to integrate with any MCP-compatible
tool server (filesystem, database, browser automation, etc.)
without hardcoding their tools.

The client:
  1. Connects to an MCP server (stdio or SSE transport)
  2. Discovers available tools via tools/list
  3. Wraps them in our ToolSchema format
  4. Forwards tool calls from the agent to the server

Usage in config (future enhancement — for now, servers are
configured programmatically or via CLI flags).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from coding_agent.types import ToolCall, ToolParameter, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class MCPClient:
    """
    Client that connects to an external MCP server and proxies
    its tools to the coding agent.

    Supports the stdio transport (launches the server as a
    subprocess) and will support SSE in the future.
    """

    def __init__(self, server_command: list[str], name: str = "external") -> None:
        """
        Initialise the MCP client.

        Args:
            server_command: Command to launch the MCP server
                            (e.g. ["npx", "@modelcontextprotocol/server-filesystem", "/tmp"])
            name: Human-readable name for this server connection.
        """
        self.server_command = server_command
        self.name = name
        self._process: asyncio.subprocess.Process | None = None
        self._tools: list[ToolSchema] = []
        self._tool_map: dict[str, dict[str, Any]] = {}
        self._msg_id = 0
        self._initialized = False

    # ── Lifecycle ─────────────────────────────────────────────

    async def connect(self) -> None:
        """
        Launch the server subprocess and perform the MCP handshake.

        After connecting, the available tools are discovered and
        can be retrieved via get_tools().
        """
        logger.info("Connecting to MCP server: %s", " ".join(self.server_command))

        self._process = await asyncio.create_subprocess_exec(
            *self.server_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Send initialize request
        init_response = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "coding-agent", "version": "0.1.0"},
        })

        if "error" in init_response:
            raise RuntimeError(
                f"MCP server initialization failed: {init_response['error']}"
            )

        # Send initialized notification
        await self._send_notification("notifications/initialized", {})
        self._initialized = True

        # Discover tools
        await self._discover_tools()

        logger.info(
            "Connected to MCP server '%s': %d tools available",
            self.name, len(self._tools),
        )

    async def disconnect(self) -> None:
        """Shut down the server subprocess."""
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None
            logger.info("Disconnected from MCP server '%s'", self.name)

    # ── Tool discovery ────────────────────────────────────────

    async def _discover_tools(self) -> None:
        """
        Query the server for available tools and convert them
        to our ToolSchema format.
        """
        response = await self._send_request("tools/list", {})

        if "error" in response:
            logger.error("Failed to list tools from '%s': %s", self.name, response["error"])
            return

        tools_data = response.get("result", {}).get("tools", [])

        for tool_data in tools_data:
            name = tool_data.get("name", "")
            description = tool_data.get("description", "")
            input_schema = tool_data.get("inputSchema", {})

            # Convert JSON Schema properties to ToolParameter list
            parameters = self._schema_to_parameters(input_schema)

            schema = ToolSchema(
                name=name,
                description=description,
                parameters=parameters,
                use_when=f"Provided by external MCP server: {self.name}",
                token_cost_hint="medium",
            )

            self._tools.append(schema)
            self._tool_map[name] = tool_data

    @staticmethod
    def _schema_to_parameters(input_schema: dict[str, Any]) -> list[ToolParameter]:
        """Convert a JSON Schema object to a list of ToolParameter."""
        properties = input_schema.get("properties", {})
        required = set(input_schema.get("required", []))

        params: list[ToolParameter] = []
        for prop_name, prop_schema in properties.items():
            json_type = prop_schema.get("type", "string")
            # Map JSON Schema types to our simple type strings
            type_map = {
                "string": "str",
                "integer": "int",
                "number": "float",
                "boolean": "bool",
                "array": "list[str]",
                "object": "dict",
            }
            py_type = type_map.get(json_type, "str")

            params.append(ToolParameter(
                name=prop_name,
                type=py_type,
                description=prop_schema.get("description", ""),
                required=prop_name in required,
                enum=prop_schema.get("enum"),
            ))

        return params

    # ── Tool execution ────────────────────────────────────────

    async def call_tool(self, call: ToolCall) -> ToolResult:
        """
        Forward a tool call to the MCP server.

        Args:
            call: The ToolCall from the agent.

        Returns:
            ToolResult with the server's response.
        """
        if not self._initialized:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output="MCP server not connected",
                success=False,
                error="not_connected",
            )

        response = await self._send_request("tools/call", {
            "name": call.name,
            "arguments": call.arguments,
        })

        if "error" in response:
            error_msg = response["error"].get("message", str(response["error"]))
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                output=f"MCP tool error: {error_msg}",
                success=False,
                error=error_msg,
            )

        result_data = response.get("result", {})
        content_items = result_data.get("content", [])
        is_error = result_data.get("isError", False)

        # Combine all text content items
        output_parts: list[str] = []
        for item in content_items:
            if item.get("type") == "text":
                output_parts.append(item.get("text", ""))

        output = "\n".join(output_parts)

        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            output=output,
            success=not is_error,
            error=output if is_error else None,
        )

    # ── Public accessors ──────────────────────────────────────

    def get_tools(self) -> list[ToolSchema]:
        """Return the list of tools discovered from this server."""
        return list(self._tools)

    def has_tool(self, name: str) -> bool:
        """Check if a tool is available on this server."""
        return name in self._tool_map

    # ── Transport layer ───────────────────────────────────────

    async def _send_request(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the response."""
        if not self._process or not self._process.stdin or not self._process.stdout:
            return {"error": {"code": -32000, "message": "Server process not running"}}

        self._msg_id += 1
        msg_id = self._msg_id

        request = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }

        # Write the request
        request_bytes = (json.dumps(request) + "\n").encode("utf-8")
        self._process.stdin.write(request_bytes)
        await self._process.stdin.drain()

        # Read the response
        try:
            response_line = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=30
            )
        except asyncio.TimeoutError:
            return {"error": {"code": -32000, "message": "Server response timeout"}}

        if not response_line:
            return {"error": {"code": -32000, "message": "Server closed connection"}}

        try:
            return json.loads(response_line.decode("utf-8"))
        except json.JSONDecodeError as exc:
            return {"error": {"code": -32700, "message": f"Invalid JSON response: {exc}"}}

    async def _send_notification(
        self,
        method: str,
        params: dict[str, Any],
    ) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or not self._process.stdin:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        notification_bytes = (json.dumps(notification) + "\n").encode("utf-8")
        self._process.stdin.write(notification_bytes)
        await self._process.stdin.drain()
