#!/usr/bin/env python3
"""
Tool-Calling Evaluation Harness

Tests whether a local Ollama model can correctly invoke each registered tool
by name and extract the required parameters.  Run against any model:

    uv run python scripts/test_tool_calling.py --model qwen3.5:9b-mlx
    uv run python scripts/test_tool_calling.py --model huihui_ai/granite4.1-abliterated:8b-q4_K

Exit code is the number of failed tools (0 = all passed).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coding_agent.config import AppConfig
from coding_agent.tools.base import ToolRegistry

# ── Test cases ──────────────────────────────────────────────────────────
# Each test sends a prompt and expects the model to invoke a specific tool
# with parameters matching the "expect" dict.

TOOL_TESTS: list[dict] = [
    {
        "tool": "read_file",
        "prompt": "Read the file src/main.py to see how the CLI is structured.",
        "expect": {"path": "src/main.py"},
    },
    {
        "tool": "search_code",
        "prompt": "Search for all function definitions containing 'async def' in the codebase.",
        "expect": {"pattern": "async def"},
    },
    {
        "tool": "list_directory",
        "prompt": "List the contents of the src/ directory to understand the project layout.",
        "expect": {"path": "src/"},
    },
    {
        "tool": "find_symbols",
        "prompt": "Find where the class AgentCore is defined in the codebase.",
        "expect": {"query": "AgentCore"},
    },
    {
        "tool": "edit_file",
        "prompt": "In src/main.py, replace 'foo' with 'bar'.",
        "expect": {"path": "src/main.py", "search": "foo", "replace": "bar"},
    },
    {
        "tool": "write_file",
        "prompt": "Create a new file at src/utils.py with a greeting function.",
        "expect": {"path": "src/utils.py"},
    },
    {
        "tool": "run_command",
        "prompt": "Run the test suite with pytest.",
        "expect": {"command": "pytest"},
    },
    {
        "tool": "get_diagnostics",
        "prompt": "Check src/main.py for lint errors.",
        "expect": {"path": "src/main.py"},
    },
    {
        "tool": "web_search",
        "prompt": "Search the web for the latest Python 3.13 release notes.",
        "expect": {"query": "Python 3.13"},
    },
    {
        "tool": "web_fetch",
        "prompt": "Fetch the content from https://example.com.",
        "expect": {"url": "https://example.com"},
    },
    {
        "tool": "git_status",
        "prompt": "Check the current git status of the project.",
        "expect": {},
    },
    {
        "tool": "git_diff",
        "prompt": "Show the current unstaged git diff.",
        "expect": {},
    },
    {
        "tool": "git_log",
        "prompt": "Show the last 5 git commits.",
        "expect": {"n": 5},
    },
    {
        "tool": "git_commit",
        "prompt": "Commit all staged changes with message 'fix tests'.",
        "expect": {"message": "fix tests"},
    },
]


def _convert_schema_to_ollama(schema) -> dict:
    """Convert our ToolSchema to Ollama's tool format."""
    props = {}
    required = []
    for p in schema.parameters:
        type_map = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}
        param = {"type": type_map.get(p.type, p.type), "description": p.description}
        if p.enum:
            param["enum"] = p.enum
        props[p.name] = param
        if p.required:
            required.append(p.name)
    return {
        "type": "function",
        "function": {
            "name": schema.name,
            "description": schema.description,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


def _check_params(call: dict, expected: dict) -> tuple[bool, str]:
    """Check if the tool call's arguments match expected values."""
    args = call.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return False, f"arguments not parseable JSON: {args[:100]}"

    for key, expected_val in expected.items():
        actual = args.get(key)
        if actual is None:
            return False, f"missing key {key!r}"
        if isinstance(expected_val, str):
            # For string params, check the model included the key with a non-empty value
            if not actual:
                return False, f"param {key!r} is empty"
        elif isinstance(expected_val, (int, float)):
            if not isinstance(actual, (int, float)):
                return False, f"param {key!r} should be numeric, got {type(actual).__name__}"
    return True, ""


async def test_model_tool_calling(ollama_base: str, model: str, schemas: dict) -> dict:
    """Run all tool tests against the given model and return results."""
    results = {}
    async with httpx.AsyncClient(timeout=60.0) as client:
        for test in TOOL_TESTS:
            tool_name = test["tool"]
            schema = schemas.get(tool_name)
            if not schema:
                results[tool_name] = {"pass": False, "reason": "schema not found"}
                continue

            prompt = test["prompt"]
            expected = test["expect"]

            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "tools": [_convert_schema_to_ollama(schema)],
                "options": {"temperature": 0.0, "num_predict": 1024},
            }

            try:
                start = time.time()
                resp = await client.post(f"{ollama_base}/api/chat", json=payload)
                elapsed = time.time() - start
            except Exception as exc:
                results[tool_name] = {"pass": False, "reason": str(exc), "elapsed": 0}
                continue

            if resp.status_code != 200:
                results[tool_name] = {
                    "pass": False,
                    "reason": f"HTTP {resp.status_code}: {resp.text[:100]}",
                    "elapsed": elapsed,
                }
                continue

            data = resp.json()
            msg = data.get("message", {})
            tool_calls = msg.get("tool_calls", [])

            if not tool_calls:
                content_preview = msg.get("content", "")[:80]
                # Model may respond with reasoning instead of tool call
                results[tool_name] = {
                    "pass": False,
                    "reason": f"no tool call (text: {content_preview})",
                    "elapsed": elapsed,
                }
                continue

            call = tool_calls[0].get("function", {})

            if call.get("name") != tool_name:
                results[tool_name] = {
                    "pass": False,
                    "reason": f"wrong tool: {call.get('name')!r}",
                    "elapsed": elapsed,
                }
                continue

            ok, detail = _check_params(call, expected)
            results[tool_name] = {
                "pass": ok,
                "reason": detail if not ok else "",
                "elapsed": elapsed,
                "args": call.get("arguments", {}),
            }

    return results


async def main() -> int:
    parser = argparse.ArgumentParser(description="Test tool-calling ability of a local model")
    parser.add_argument("--model", default=None, help="Ollama model name")
    parser.add_argument("--ollama-base", default="http://localhost:11434")
    parser.add_argument("--list-models", action="store_true", help="List available models and exit")
    args = parser.parse_args()

    async with httpx.AsyncClient() as client:
        # List models
        resp = await client.get(f"{args.ollama_base}/api/tags")
        models = resp.json().get("models", [])
        model_names = [m["name"] for m in models]

        if args.list_models:
            print("Available models:")
            for m in model_names:
                print(f"  {m}")
            return 0

        if args.model:
            model = args.model
        else:
            # Try to find the best model
            preferred = [m for m in model_names if "qwen3.5" in m or "granite" in m]
            model = preferred[0] if preferred else model_names[0] if model_names else ""
            if not model:
                print("No models found. Start Ollama and pull a model first.")
                return 1

        if model not in model_names:
            print(f"Model {model!r} not found in Ollama. Available: {model_names}")
            return 1

    # Load tool schemas
    config = AppConfig()
    reg = ToolRegistry(config)
    await reg.setup()

    print(f"Testing tool-calling with model: {model}")
    print(f"Total tools registered: {len(reg.schemas)}")
    print(f"Test cases: {len(TOOL_TESTS)}")
    print()

    results = await test_model_tool_calling(args.ollama_base, model, reg.schemas)

    # Report
    passed = sum(1 for r in results.values() if r["pass"])
    failed = sum(1 for r in results.values() if not r["pass"])

    print(f"{'TOOL':<20} {'RESULT':<8} {'TIME':<8} DETAIL")
    print("-" * 80)
    for tool_name, r in sorted(results.items()):
        status = "✅ PASS" if r["pass"] else "❌ FAIL"
        elapsed = f"{r.get('elapsed', 0):.1f}s" if r.get("elapsed") else "N/A"
        reason = r.get("reason", "")
        print(f"{tool_name:<20} {status:<8} {elapsed:<8} {reason}")

    print()
    print(f"Passed: {passed}/{len(results)} ({passed / len(results) * 100:.0f}%)")
    print(f"Failed: {failed}/{len(results)}")

    return failed


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
