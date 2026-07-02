"""
Strategic planner: decomposes a task into ordered subtasks.

A single Planner class parameterized by strategy ("flat" or
"tree_of_thought" for single-pass vs multi-evaluation) handles all
non-hierarchical decomposition.  The old FlatPlanner and
TreeOfThoughtPlanner class names are kept as backward-compat aliases.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from coding_agent.config import AppConfig
from coding_agent.llm.base import LLMClient
from coding_agent.types import Message, Phase, Plan, PlanPhase, Role, SubTask, TaskStatus

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
    "Format:\n" + _BACKTICKS + "json\n"
    "{{\n"
    '  "goal": "<one-line goal>",\n'
    '  "subtasks": [\n'
    '    {{"id": 1, "description": "...", "files": ["path/to/file"]}},\n'
    "    ...\n"
    "  ],\n"
    '  "dependencies": {{\n'
    '    "3": [1, 2]\n'
    "  }}\n"
    "}}\n" + _BACKTICKS + "\n\n"
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
    'using the key "best_plan".\n\n'
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
    'it as a JSON block using the key "best_plan".\n\n'
    "Project context:\n{context}\n"
)


# ──────────────────────────────────────────────────────────────
# Strategy registry
# ──────────────────────────────────────────────────────────────


@dataclass
class _PlanningStrategy:
    """Configuration bundle for a planning strategy."""

    plan_prompt: str
    replan_prompt: str
    plan_temperature: float = 0.3
    replan_temperature: float = 0.4
    plan_max_tokens: int = 1024
    replan_max_tokens: int = 1024


_STRATEGIES: dict[str, _PlanningStrategy] = {
    "flat": _PlanningStrategy(
        plan_prompt=_FLAT_PLANNER_PROMPT,
        replan_prompt=_REPLAN_PROMPT,
    ),
    "tree_of_thought": _PlanningStrategy(
        plan_prompt=_TOT_DECOMPOSE_PROMPT,
        replan_prompt=_TOT_REPLAN_PROMPT,
        plan_temperature=0.4,
        replan_temperature=0.5,
        plan_max_tokens=2048,
        replan_max_tokens=2048,
    ),
}


# ──────────────────────────────────────────────────────────────
# Planner
# ──────────────────────────────────────────────────────────────


class Planner:
    """
    Concrete planner that decomposes a task into a Plan of SubTasks.

    Two built-in strategies:
      "flat" — simple single-pass decomposition (local models).
      "tree_of_thought" — evaluates multiple decomposition strategies
      in one call (large models with spare reasoning capacity).
    """

    def __init__(self, llm: LLMClient, config: AppConfig, strategy: str = "flat") -> None:
        self.llm = llm
        self.config = config
        if strategy not in _STRATEGIES:
            msg = f"Unknown planner strategy {strategy!r}. Choose from {list(_STRATEGIES)}"
            raise ValueError(msg)
        self._strategy = _STRATEGIES[strategy]

    # ── Planning ──────────────────────────────────────────────

    async def plan(self, task: str, context_summary: str) -> Plan:
        """
        Decompose *task* into a Plan of SubTasks.

        Args:
            task: The user's high-level task description.
            context_summary: Brief overview of the project structure / files.

        Returns:
            A Plan with ordered SubTasks and dependency edges.
        """
        s = self._strategy
        prompt = s.plan_prompt.format(task=task, context=context_summary)
        messages = [Message(role=Role.USER, content=prompt)]

        response = await self.llm.chat(
            messages=messages,
            temperature=s.plan_temperature,
            max_tokens=s.plan_max_tokens,
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
        Re-plan from a failed subtask onwards.

        Completed subtasks are preserved; only pending/failed ones
        may change.
        """
        s = self._strategy
        completed = [st for st in existing_plan.subtasks if st.status == TaskStatus.COMPLETED]
        pending = [st for st in existing_plan.subtasks if st.status != TaskStatus.COMPLETED]

        prompt = s.replan_prompt.format(
            failed_id=failed_subtask_id,
            reason=reason,
            completed=self._format_subtasks(completed),
            pending=self._format_subtasks(pending),
            context=context_summary,
        )

        messages = [Message(role=Role.USER, content=prompt)]
        response = await self.llm.chat(
            messages=messages,
            temperature=s.replan_temperature,
            max_tokens=s.replan_max_tokens,
        )

        new_partial = self._parse_plan_response(response.content)
        return self._merge_replan_results(existing_plan, completed, new_partial)

    @staticmethod
    def _merge_replan_results(
        existing_plan: Plan,
        completed: list[SubTask],
        new_partial: Plan,
    ) -> Plan:
        """Merge completed subtasks with the LLM's partial plan and re-number."""
        merged = completed + new_partial.subtasks
        for i, st in enumerate(merged):
            st.id = i + 1
        for i, st in enumerate(merged):
            if st.status != TaskStatus.COMPLETED:
                st.status = TaskStatus.IN_PROGRESS
                existing_plan.current_subtask_idx = i
                break
        existing_plan.subtasks = merged
        return existing_plan

    # ── Shared helpers ────────────────────────────────────────

    def _parse_plan_response(self, text: str) -> Plan:
        """
        Parse a structured plan from LLM output.

        Expects the LLM to return a JSON block with subtasks and
        dependencies.  Falls back to a simpler line-by-line parse
        if JSON extraction fails.
        """
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        json_str = json_match.group(1) if json_match else text.strip()

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
                        description=st_raw.get("description") or st_raw.get("desc") or "",
                        files=st_raw.get("files", []),
                    )
                )

        deps: dict[int, list[int]] = {}
        for k, v in data.get("dependencies", {}).items():
            deps[int(k)] = v if isinstance(v, list) else [v]

        plan = Plan(
            goal=data.get("goal", ""),
            subtasks=subtasks,
            dependencies=deps,
        )

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
            files_str = f" (files: {', '.join(st.files)})" if st.files else ""
            lines.append(f"  {st.id}. [{st.status.value}] {st.description}{files_str}")
        return "\n".join(lines)


# ── Backward-compat aliases ───────────────────────────────────


class FlatPlanner(Planner):
    """Simple single-pass planner. Backward-compat alias."""


class TreeOfThoughtPlanner(Planner):
    """
    Tree-of-thought planner with multi-branch evaluation.

    Generates multiple candidate decomposition strategies, evaluates them
    against completeness/ordering/risk criteria, and returns the best.

    When ``parallel_branches=True`` (requires a verifier), branches are
    evaluated independently and the best-performing one is selected.
    """

    def __init__(
        self,
        llm: LLMClient,
        config: AppConfig,
        parallel_branches: bool = False,
    ) -> None:
        super().__init__(llm=llm, config=config, strategy="tree_of_thought")
        self._parallel_branches = parallel_branches

    async def plan(self, task: str, context_summary: str) -> Plan:
        if not self._parallel_branches:
            return await super().plan(task, context_summary)

        # Parallel ToT: generate N candidate plans independently, pick best
        n_branches = 3
        prompts = [
            (
                f"You are an expert task planner for a coding agent.\n\n"
                f"Generate ONE decomposition strategy for the task below.\n"
                f"List the subtasks and explain why this approach works.\n\n"
                f"Project context:\n{context_summary}\n\n"
                f"Task: {task}\n"
            )
            for _ in range(n_branches)
        ]

        results = await asyncio.gather(
            *[
                self.llm.chat(
                    messages=[Message(role=Role.USER, content=p)],
                    temperature=0.6,
                    max_tokens=1536,
                )
                for p in prompts
            ],
            return_exceptions=True,
        )

        # Collect successful plans
        plans: list[Plan] = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning("ToT branch failed: %s", r)
                continue
            plan = self._parse_plan_response(r.content)
            plans.append(plan)

        if not plans:
            logger.warning("All ToT branches failed — falling back to single-pass")
            return await super().plan(task, context_summary)

        # Score each plan by subtask count + dependency coverage
        def _score(p: Plan) -> float:
            score = len(p.subtasks) * 2.0
            score += len(p.dependencies) * 1.0
            for st in p.subtasks:
                if st.files:
                    score += 1.0
            return score

        plans.sort(key=_score, reverse=True)
        return plans[0]


# ──────────────────────────────────────────────────────────────
# Hierarchical planner (multi-stage, for complex tasks)
# ──────────────────────────────────────────────────────────────

_STRATEGIC_PROMPT = """\
You are a strategic task planner for a coding agent.

Decompose the following task into 3-7 high-level phases. Each phase \
should represent a major stage of work.

Rules:
- Each phase should be a concrete, measurable stage
- Order phases so earlier ones don't depend on later ones
- Include likely file paths when obvious
- Keep phase names short (under 50 chars)
- Return ONLY a JSON block, no other text

Format:
```json
{{
  "goal": "<one-line goal>",
  "phases": [
    {{"id": 1, "name": "Discover & Explore", "description": "Map the codebase"}},
    {{"id": 2, "name": "Implement Core", "description": "Write the main implementation"}},
    ...
  ]
}}
```

Project context:
{context}

Task: {task}
"""

_TACTICAL_PROMPT = """\
You are a tactical task planner for a coding agent.

Given the following strategic phase of a larger project, decompose it \
into concrete subtasks. Each subtask should be a single coding action.

Phase: #{phase_id} — {phase_name}
Description: {phase_description}

Rules:
- Each subtask should be a single, concrete coding action
- Order them so earlier subtasks don't depend on later ones
- Include likely file paths when obvious
- Keep descriptions under 100 characters each
- Return ONLY a JSON block, no other text

Format:
```json
{{
  "subtasks": [
    {{"id": 1, "description": "...", "files": ["path/to/file"]}},
    ...
  ],
  "dependencies": {{"3": [1, 2]}}
}}
```

Project context:
{context}
"""


class HierarchicalPlanner(Planner):
    """
    Multi-stage planner with strategic and tactical layers.

    Produces a Plan with 3-7 strategic phases.  Each phase contains
    a tactical sub-plan with concrete subtasks.

    When a phase fails, only that phase is re-planned (keeping the
    strategic structure intact).
    """

    async def plan(self, task: str, context_summary: str) -> Plan:
        prompt = _STRATEGIC_PROMPT.format(task=task, context=context_summary)
        messages = [Message(role=Role.USER, content=prompt)]

        response = await self.llm.chat(
            messages=messages,
            temperature=0.3,
            max_tokens=2048,
        )

        plan = self._parse_strategic_response(response.content, task)

        if plan.phases:
            first_phase = plan.phases[0]
            plan = await self._tactical_for_phase(plan, first_phase, context_summary)

        return plan

    async def replan(
        self,
        existing_plan: Plan,
        failed_subtask_id: int,
        reason: str,
        context_summary: str,
    ) -> Plan:
        failed_phase = None
        for ph in existing_plan.phases:
            if ph.plan and any(
                st.id == failed_subtask_id or st.status == TaskStatus.FAILED
                for st in ph.plan.subtasks
            ):
                failed_phase = ph
                break

        if failed_phase is None:
            return await FlatPlanner(self.llm, self.config).replan(
                existing_plan,
                failed_subtask_id,
                reason,
                context_summary,
            )

        failed_phase.status = PlanPhase.RETRY

        return await self._tactical_for_phase(
            existing_plan,
            failed_phase,
            context_summary,
            reason=reason,
        )

    async def _tactical_for_phase(
        self,
        plan: Plan,
        phase: Phase,
        context_summary: str,
        reason: str = "",
    ) -> Plan:
        prompt_parts = f"Reason for revision: {reason}\n\n" if reason else ""
        prompt = (
            _TACTICAL_PROMPT.format(
                phase_id=phase.id,
                phase_name=phase.name,
                phase_description=phase.description,
                context=context_summary,
            )
            + prompt_parts
        )

        messages = [Message(role=Role.USER, content=prompt)]
        response = await self.llm.chat(
            messages=messages,
            temperature=0.3,
            max_tokens=1024,
        )

        tactical = self._parse_tactical_response(response.content)
        phase.plan = tactical

        for i, ph in enumerate(plan.phases):
            if ph.id == phase.id:
                plan.phases[i] = phase
                break

        if plan.current_phase_idx < 0:
            plan.advance_phase()

        return plan

    def _parse_strategic_response(self, text: str, task: str) -> Plan:
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        json_str = json_match.group(1) if json_match else text.strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return Plan(
                goal=task[:100],
                phases=[
                    Phase(id=1, name="Execute", description=task[:200]),
                ],
            )

        phases: list[Phase] = []
        for ph_raw in data.get("phases", []):
            phases.append(
                Phase(
                    id=ph_raw.get("id", len(phases) + 1),
                    name=ph_raw.get("name", f"Phase {len(phases) + 1}"),
                    description=ph_raw.get("description", ""),
                )
            )

        if not phases:
            phases.append(Phase(id=1, name="Execute", description=task[:200]))

        return Plan(
            goal=data.get("goal", task[:100]),
            phases=phases,
        )

    def _parse_tactical_response(self, text: str) -> Plan:
        return self._parse_plan_response(text)
