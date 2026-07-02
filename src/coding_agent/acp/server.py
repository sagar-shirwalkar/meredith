"""
ACP server: exposes the coding agent over the Agent Client Protocol.

Replaces the previous MCP server. Uses the official `agent-client-protocol`
Python SDK to communicate with ACP-aware editors (Zed, JetBrains, Neovim, etc.).

Usage (standalone):
    python -m coding_agent.acp.server --profile local_model

The server registers as an ACP agent. When the editor sends a prompt,
the coding agent's ReAct loop runs and streams status updates back
to the editor via `session/update` notifications.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from acp import (
    PROTOCOL_VERSION,
    Agent,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    run_agent,
    text_block,
    update_agent_message,
)
from acp.interfaces import Client
from acp.schema import (
    AgentCapabilities,
    AudioContentBlock,
    AuthenticateResponse,
    ClientCapabilities,
    CloseSessionResponse,
    EmbeddedResourceContentBlock,
    ForkSessionResponse,
    HttpMcpServer,
    ImageContentBlock,
    Implementation,
    ListSessionsResponse,
    LoadSessionResponse,
    McpServerStdio,
    ResourceContentBlock,
    ResumeSessionResponse,
    SetSessionConfigOptionResponse,
    SetSessionModelResponse,
    SetSessionModeResponse,
    SseMcpServer,
    TextContentBlock,
)

from coding_agent.agent.core import AgentCore
from coding_agent.config import load_config
from coding_agent.main import create_llm_client

logger = logging.getLogger(__name__)


class CodingAgentServer(Agent):
    """
    ACP-compatible agent server wrapping the coding agent's AgentCore.

    Each `prompt` call spawns a fresh AgentCore with the user's text
    as the task, executes the full ReAct loop, and streams a summary
    back to the editor.
    """

    _conn: Client

    def __init__(self, profile: str = "large_model") -> None:
        self._profile = profile
        self._config = load_config(profile)

    def on_connect(self, conn: Client) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_capabilities=AgentCapabilities(),
            agent_info=Implementation(
                name="meredith",
                title="meredith",
                version="0.3.3",
            ),
        )

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        session_id = uuid4().hex
        logger.info("New ACP session: %s (cwd=%s)", session_id, cwd)
        return NewSessionResponse(session_id=session_id)

    async def prompt(
        self,
        prompt: list[
            TextContentBlock
            | ImageContentBlock
            | AudioContentBlock
            | ResourceContentBlock
            | EmbeddedResourceContentBlock
        ],
        session_id: str,
        message_id: str | None = None,
        **kwargs: Any,
    ) -> PromptResponse:
        user_text = self._extract_text(prompt)
        if not user_text:
            user_text = "(no text provided)"

        logger.info("ACP prompt on session %s: %.80s", session_id, user_text)

        llm = create_llm_client(self._config)
        async with AgentCore(self._config, llm, user_text) as agent:
            success = await agent.run()

        summary = self._build_summary(agent, success)
        if self._conn:
            chunk = update_agent_message(text_block(summary))
            await self._conn.session_update(
                session_id=session_id,
                update=chunk,
                source="coding_agent",
            )

        return PromptResponse(stop_reason="end_turn", user_message_id=message_id)

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        logger.info("Cancel requested for session %s", session_id)

    async def load_session(
        self,
        cwd: str,
        session_id: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> LoadSessionResponse | None:
        return None

    async def list_sessions(
        self,
        additional_directories: list[str] | None = None,
        cursor: str | None = None,
        cwd: str | None = None,
        **kwargs: Any,
    ) -> ListSessionsResponse:
        return ListSessionsResponse(sessions=[])

    async def set_session_mode(
        self, mode_id: str, session_id: str, **kwargs: Any
    ) -> SetSessionModeResponse | None:
        return None

    async def set_session_model(
        self, model_id: str, session_id: str, **kwargs: Any
    ) -> SetSessionModelResponse | None:
        return None

    async def set_config_option(
        self, config_id: str, session_id: str, value: str | bool, **kwargs: Any
    ) -> SetSessionConfigOptionResponse | None:
        return None

    async def authenticate(self, method_id: str, **kwargs: Any) -> AuthenticateResponse | None:
        return None

    async def fork_session(
        self,
        cwd: str,
        session_id: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> ForkSessionResponse:
        return ForkSessionResponse(session_id=session_id)

    async def resume_session(
        self,
        cwd: str,
        session_id: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> ResumeSessionResponse:
        return ResumeSessionResponse()

    async def close_session(self, session_id: str, **kwargs: Any) -> CloseSessionResponse | None:
        return None

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        pass

    # ── Helpers ────────────────────────────────────────────────

    @staticmethod
    def _extract_text(
        prompt: list[
            TextContentBlock
            | ImageContentBlock
            | AudioContentBlock
            | ResourceContentBlock
            | EmbeddedResourceContentBlock
        ],
    ) -> str:
        parts: list[str] = []
        for block in prompt:
            if isinstance(block, dict):
                text = block.get("text", "")
            else:
                text = getattr(block, "text", "") or ""
            if text:
                parts.append(text)
        return "\n".join(parts)

    @staticmethod
    def _build_summary(agent: AgentCore, success: bool) -> str:
        steps = agent.state.step_count
        files = agent.state.files_modified
        status = "completed" if success else "max steps reached"
        parts = [
            f"Agent finished (status: {status}, steps: {steps})",
        ]
        if files:
            parts.append(f"Files modified: {', '.join(sorted(files)[:10])}")
        if steps > 0:
            parts.append(f"Tokens used: {agent.state.total_tokens_used}")
        return "\n".join(parts)


def main() -> None:
    """Run the ACP agent server as a standalone process."""
    import argparse

    parser = argparse.ArgumentParser(description="Coding Agent (ACP Server)")
    parser.add_argument(
        "--profile",
        "-p",
        default="large_model",
        choices=["large_model", "local_model"],
        help="Configuration profile",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    server = CodingAgentServer(profile=args.profile)
    asyncio.run(run_agent(server))


if __name__ == "__main__":
    main()
