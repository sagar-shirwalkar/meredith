"""
Strategic planner: decomposes a task into ordered subtasks.

Two implementations:
  - TreeOfThoughtPlanner: Evaluates multiple decomposition strategies
    before committing (for large models with spare reasoning capacity).
  - FlatPlanner: Simple list decomposition in a single LLM call
    (for local models that need simpler prompts).
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from coding_agent.config import AppConfig
from coding_agent.llm.base import LLMClient
from coding_agent.types import Message, Plan, Role, SubTask, TaskStatus

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Prompt templates
# ──────────────────────────────────────────────────────────────

_BACKTICKS = "```"

_FLAT_PLANNER_PROMPT = (
    "You are a task planner for a coding agent. "
    "Decompose the following task into a simple ordered list of subtasks.\n\n"
    "Rules:\n"
    "- Each subtask should be a single, concrete coding action\n"
    "- Order them so earlier subtasks don't depend on later ones\n"
    "- Include likely file paths when obvious\n"
    "- Keep descriptions under 100 characters each\n"
    "- Return ONLY a JSON block, no other text\n\n"
    "Format:\n"
    + _BACKTICKS
    + "json\n"
    '{\n'
    '  "goal": "<one-line goal>",\n'
    '  "subtasks": [\n'
    '    {"id": 1, "description": "...", "files": ["path/to/file"]},\n'
    '    ...\n'
    '  ],\n'
    '  "dependencies": {\n'
    '    "3": [1, 2]\n'
    '  }\n'
    '}\n'
    + _BACKTICKS
    + "\n\n"
    "Project context:\n{context}\n\n"
    "Task: {task}\n"
)

_TOT_DECOMPOSE_PROMPT = (
    "You are an expert task planner for a coding agent.\n\n"
    "Generate THREE different decomposition strategies for the task below. "
    "For each strategy, list the subtasks and briefly explain why this "
    "approach might work.\n\n"
    "Then evaluate each strategy on:\n"
    "  - Completeness (does it cover all aspects?)\n"
    "  - Ordering (are dependencies respected?)\n"
    "  - Risk (how likely is it to fail?)\n\n"
    "Finally, select the best strategy and output it as a JSON block "
    "using the key \"best_plan\".\n\n"
    "Project context:\n{context}\n\n"
    "Task: {task}\n"
)

_REPLAN_PROMPT = (
    "The following subtask failed: #{failed_id}\n"
    "Reason: {reason}\n\n"
    "Completed subtasks:\n{completed}\n\n"
    "Remaining subtasks (may need revision):\n{pending}\n\n"
    "Project context:\n{context}\n\n"
    "Please provide a revised plan for the remaining work, starting from a "
    "different approach to the failed subtask. Return ONLY a JSON block "
    "with the same format as the original plan.\n"
)

_TOT_REPLAN_PROMPT = (
    "Subtask #{failed_id} failed: {reason}\n\n"
    "Completed so far:\n{completed}\n\n"
    "Generate TWO different approaches to complete the remaining work, "
    "starting from the failure point. For each approach, explain the "
    "key difference in strategy. Then pick the better one and output "
    "it as a JSON block using the key \"best_plan\".\n\n"
    "Project context:\n{context}\n"
)


# ──────────────────────────────────────────────────────────────
# Abstract planner
# ──────────────────────────────────────────────────────────────


class Planner(ABC):
    """Base class for task planners."""

    def __init__(self, llm: LLMClient, config: AppConfig) -> None:
        self.llm = llm
        self.config = config

    @abstractmethod
    async def plan(self, task: str, context_summary: str) -> Plan:
        """
        Decompose *task* into a Plan of SubTasks.

        Args:
            task: The user's high-level task description.
            context_summary: Brief overview of the project structure / files.

        Returns:
            A Plan with ordered SubTasks and dependency edges.
        """
        ...

    @abstractmethod
    async def replan(
        self,
        existing_plan: Plan,
        failed_subtask_id: int,
        reason: str,
        context_summary: str,
    ) -> Plan:
        """
        Re-plan from a failed subtask onwards.

        The planner may modify, add, or remove future subtasks.
        Completed subtasks are preserved.
        """
        ...

    # ── Shared helpers ────────────────────────────────────────

    def _parse_plan_response(self, text: str) -> Plan:
        """
        Parse a structured plan from LLM output.

        Expects the LLM to return a JSON block with subtasks and
        dependencies.  Falls back to a simpler line-by-line parse
        if JSON extraction fails.
        """
        # Try to extract JSON from a fenced code block
        json_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL
        )
        json_str = json_match.group(1) if json_match else text.strip()

        # If the LLM used a "best_plan" key (tree-of-thought), unwrap it
        try:
            data = json.loads(json_str)
            if isinstance(data, dict) and "best_plan" in data:
                data = data["best_plan"]
            return self._dict_to_plan(data)
        except json.JSONDecodeError:
            logger.warning("Failed to parse plan as JSON, falling back to line-by-line")
            return self._parse_plan_from_lines(text)

    def _dict_to_plan(self, data: dict[str, Any]) -> Plan:
        """Convert a parsed JSON dict into a Plan object."""
        subtasks: list[SubTask] = []
        for i, st_raw in enumerate(data.get("subtasks", [])):
            if isinstance(st_raw, str):
                subtasks.append(SubTask(id=i + 1, description=st_raw))
            elif isinstance(st_raw, dict):
                subtasks.append(
                    SubTask(
                        id=st_raw.get("id", i + 1),
                        description=st_raw.get("description", st_raw.get("desc", "")),
                        files=st_raw.get("files", []),
                    )
                )

        # Parse dependencies: {subtask_id: [dep_ids...]}
        deps: dict[int, list[int]] = {}
        for k, v in data.get("dependencies", {}).items():
            deps[int(k)] = v if isinstance(v, list) else [v]

        plan = Plan(
            goal=data.get("goal", ""),
            subtasks=subtasks,
            dependencies=deps,
        )

        # Set first subtask to in_progress
        if subtasks:
            subtasks[0].status = TaskStatus.IN_PROGRESS
            plan.current_subtask_idx = 0

        return plan

    def _parse_plan_from_lines(self, text: str) -> Plan:
        """
        Fallback: parse a plan from numbered or bulleted lines.

        Handles:
          1. Create the User model
          2. Implement JWT token generation
          - Create auth endpoints
        """
        subtasks: list[SubTask] = []
        for line in text.split("\n"):
            line = line.strip()
            m = re.match(r"(?:\d+[\.\)]\s*|-\s+)(.+)", line)
            if m:
                subtasks.append(
                    SubTask(
                        id=len(subtasks) + 1,
                        description=m.group(1).strip(),
                    )
                )

        if not subtasks:
            # Could not parse at all; make the whole task one subtask
            subtasks.append(SubTask(id=1, description=text[:200]))

        plan = Plan(goal=text[:100], subtasks=subtasks)
        subtasks[0].status = TaskStatus.IN_PROGRESS
        plan.current_subtask_idx = 0
        return plan

    @staticmethod
    def _format_subtasks(subtasks: list[SubTask]) -> str:
        """Format a list of subtasks for inclusion in a prompt."""
        lines: list[str] = []
        for st in subtasks:
            files_str = (
                f" (files: {', '.join(st.files)})" if st.files else ""
            )
            lines.append(
                f"  {st.id}. [{st.status.value}] {st.description}{files_str}"
            )
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# Flat planner (simple, for local models)
# ──────────────────────────────────────────────────────────────


class FlatPlanner(Planner):
    """
    Simple single-pass planner.

    Makes one LLM call to decompose the task.  Best for local models
    where we want minimal prompt complexity.
    """

    async def plan(self, task: str, context_summary: str) -> Plan:
        prompt = _FLAT_PLANNER_PROMPT.format(task=task, context=context_summary)
        messages = [Message(role=Role.USER, content=prompt)]

        response = await self.llm.chat(
            messages=messages,
            temperature=0.3,
            max_tokens=1024,
        )

        return self._parse_plan_response(response.content)

    async def replan(
        self,
        existing_plan: Plan,
        failed_subtask_id: int,
        reason: str,
        context_summary: str,
    ) -> Plan:
        """
        Replan by asking the LLM to revise from the failed subtask.

        Completed subtasks are preserved; only pending/failed ones
        may change.
        """
        completed = [
            st for st in existing_plan.subtasks
            if st.status == TaskStatus.COMPLETED
        ]
        pending = [
            st for st in existing_plan.subtasks
            if st.status != TaskStatus.COMPLETED
        ]

        prompt = _REPLAN_PROMPT.format(
            failed_id=failed_subtask_id,
            reason=reason,
            completed=self._format_subtasks(completed),
            pending=self._format_subtasks(pending),
            context=context_summary,
        )

        messages = [Message(role=Role.USER, content=prompt)]
        response = await self.llm.chat(
            messages=messages, temperature=0.4, max_tokens=1024
        )

        new_partial = self._parse_plan_response(response.content)

        # Merge: keep completed, replace the rest
        merged_subtasks = completed + new_partial.subtasks

        # Re-number IDs
        for i, st in enumerate(merged_subtasks):
            st.id = i + 1

        # First non-completed subtask becomes current
        for i, st in enumerate(merged_subtasks):
            if st.status != TaskStatus.COMPLETED:
                st.status = TaskStatus.IN_PROGRESS
                existing_plan.current_subtask_idx = i
                break

        existing_plan.subtasks = merged_subtasks
        return existing_plan


# ──────────────────────────────────────────────────────────────
# Tree-of-thought planner (for large models)
# ──────────────────────────────────────────────────────────────


class TreeOfThoughtPlanner(Planner):
    """
    Advanced planner that evaluates multiple strategies before committing.

    Uses more tokens but produces higher-quality plans for complex tasks.
    Only suitable for large models with sufficient reasoning capacity.
    """

    async def plan(self, task: str, context_summary: str) -> Plan:
        prompt = _TOT_DECOMPOSE_PROMPT.format(task=task, context=context_summary)
        messages = [Message(role=Role.USER, content=prompt)]

        response = await self.llm.chat(
            messages=messages,
            temperature=0.4,
            max_tokens=2048,
        )

        return self._parse_plan_response(response.content)

    async def replan(
        self,
        existing_plan: Plan,
        failed_subtask_id: int,
        reason: str,
        context_summary: str,
    ) -> Plan:
        """
        Replan using tree-of-thought: generate multiple alternative
        approaches to the failed subtask and pick the best one.
        """
        completed = [
            st for st in existing_plan.subtasks
            if st.status == TaskStatus.COMPLETED
        ]

        prompt = _TOT_REPLAN_PROMPT.format(
            failed_id=failed_subtask_id,
            reason=reason,
            completed=self._format_subtasks(completed),
            context=context_summary,
        )

        messages = [Message(role=Role.USER, content=prompt)]
        response = await self.llm.chat(
            messages=messages, temperature=0.5, max_tokens=2048
        )

        new_partial = self._parse_plan_response(response.content)

        # Merge
        merged_subtasks = completed + new_partial.subtasks
        for i, st in enumerate(merged_subtasks):
            st.id = i + 1

        for i, st in enumerate(merged_subtasks):
            if st.status != TaskStatus.COMPLETED:
                st.status = TaskStatus.IN_PROGRESS
                existing_plan.current_subtask_idx = i
                break

        existing_plan.subtasks = merged_subtasks
        return existing_plan
