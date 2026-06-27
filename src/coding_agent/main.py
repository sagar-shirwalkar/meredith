"""
CLI entry point for the meredith.

Usage:
    meredith "Add JWT authentication to the login endpoint"
    meredith --profile local_model "Fix the failing test in test_auth.py"
    meredith --profile large_model --working-dir ./myproject "Refactor the user service"

Wires together config loading, LLM client creation, and the agent loop.
The agent loop itself lives in agent/core.py; this module is the orchestrator.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from coding_agent.config import AppConfig, load_config
from coding_agent.llm.base import LLMClient
from coding_agent.llm.local import LocalLLMClient
from coding_agent.llm.remote import RemoteLLMClient

logger = logging.getLogger("coding_agent")


# ──────────────────────────────────────────────────────────────
# Logging setup
# ──────────────────────────────────────────────────────────────


def setup_logging(config: AppConfig) -> None:
    """Configure logging based on AppConfig."""
    log_path = Path(config.agent.working_directory) / config.logging.file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(log_path, encoding="utf-8"),
    ]

    logging.basicConfig(
        level=getattr(logging, config.logging.level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


# ──────────────────────────────────────────────────────────────
# LLM client factory
# ──────────────────────────────────────────────────────────────


def create_llm_client(config: AppConfig) -> LLMClient:
    """
    Instantiate the appropriate LLM client based on config.

    - provider="remote" → RemoteLLMClient (OpenAI-compatible API)
    - provider="local"  → LocalLLMClient  (Ollama / MLX)
    """
    llm_cfg = config.llm

    if llm_cfg.provider == "remote":
        return RemoteLLMClient(
            model=llm_cfg.model,
            api_base=llm_cfg.api_base,
            key_var=llm_cfg.key_var,
            temperature=llm_cfg.temperature,
            max_tokens=llm_cfg.max_response_tokens,
        )
    elif llm_cfg.provider == "local":
        return LocalLLMClient(
            model=llm_cfg.model,
            ollama_base=llm_cfg.ollama_base,
            mlx_model_path=llm_cfg.mlx_model_path,
            mlx_fallback=llm_cfg.mlx_fallback,
            temperature=llm_cfg.temperature,
            max_tokens=llm_cfg.max_response_tokens,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {llm_cfg.provider!r}")


# ──────────────────────────────────────────────────────────────
# Directory scaffolding
# ──────────────────────────────────────────────────────────────


def ensure_project_dirs(config: AppConfig) -> None:
    """Create .agent/ directory and subdirectories if they don't exist."""
    workdir = Path(config.agent.working_directory)
    (workdir / ".agent").mkdir(exist_ok=True)

    if config.rag.enabled:
        (workdir / config.rag.index_dir).mkdir(parents=True, exist_ok=True)

    if config.skills.directories:
        for d in config.skills.directories:
            (workdir / d).mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────────────────────
# Main run logic
# ──────────────────────────────────────────────────────────────


async def run_agent(config: AppConfig, task: str) -> None:
    """
    Create all components and run the agent loop.

    This is the async main function.  The actual agent execution
    is delegated to AgentCore.run(), which we import here to
    keep the entry point decoupled from the core loop.
    """
    # Late import to avoid circular dependencies
    from coding_agent.agent.core import AgentCore

    llm = create_llm_client(config)

    try:
        agent = AgentCore(config=config, llm=llm, task=task)

        logger.info("Starting agent with profile=%s model=%s task=%r",
                     config.llm.provider, config.llm.model, task[:80])

        result = await agent.run()

        if result:
            logger.info("Agent completed successfully")
            print("\n✅ Agent finished.\n")
        else:
            logger.warning("Agent did not complete the task")
            print("\n⚠️  Agent could not complete the task.\n")

    finally:
        await llm.close()


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="meredith",
        description="AI coding agent with RAG, ACP, and smart context management",
    )
    parser.add_argument(
        "task",
        help="The coding task for the agent to perform",
    )
    parser.add_argument(
        "--profile", "-p",
        default="large_model",
        choices=["large_model", "local_model"],
        help="Configuration profile (default: large_model)",
    )
    parser.add_argument(
        "--working-dir", "-d",
        default=".",
        help="Project directory the agent operates on (default: .)",
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="Override the model name from config",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Set logging to DEBUG",
    )
    return parser


def cli() -> None:
    """Synchronous entry point registered in pyproject.toml."""
    parser = build_parser()
    args = parser.parse_args()

    # Build CLI overrides dict
    overrides: dict[str, Any] = {}
    if args.working_dir:
        overrides["agent"] = {"working_directory": args.working_dir}
    if args.model:
        overrides.setdefault("llm", {})["model"] = args.model
    if args.verbose:
        overrides["logging"] = {"level": "DEBUG"}

    # Load merged config
    config = load_config(profile=args.profile, overrides=overrides)

    # Setup
    setup_logging(config)
    ensure_project_dirs(config)

    # Run
    try:
        asyncio.run(run_agent(config, args.task))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)


if __name__ == "__main__":
    cli()
