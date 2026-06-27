"""
MCP (Model Context Protocol) subsystem.

Allows the agent to:
  - Run AS a server (so Zed, Opencode, and other MCP hosts can
    connect to it and use its tools)
  - Connect to external MCP servers (to use additional tools
    provided by the ecosystem)
"""

from coding_agent.mcp.server import MCPServer
from coding_agent.mcp.client import MCPClient

__all__ = [
    "MCPClient",
    "MCPServer",
]
