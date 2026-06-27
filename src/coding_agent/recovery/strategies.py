"""
Recovery strategies: interventions injected into the agent's
context when a loop is detected.

Each strategy produces a RecoveryAction that may:
  - Inject a warning message into the scratch zone
  - Force the agent to think before acting
  - Suggest alternative tools
  - Trigger replanning
  - Request user intervention
"""

from __future__ import annotations

import logging
import random

from coding_agent.config import AppConfig
from coding_agent.llm.base import LLMClient
from coding_agent.types import AgentState, LoopDetection, LoopType, RecoveryAction

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Divergence prompts — injected to break the agent out of a
# reasoning rut by forcing a different perspective.
# ──────────────────────────────────────────────────────────────

_DIVERGENCE_PROMPTS = [
    "What assumption are you making that might be wrong?",
    "If you could not use the approach you have been trying, what would you do instead?",
    "Describe the problem as if explaining it to a junior developer. What becomes obvious?",
    "What would the simplest possible solution look like, even if it is not elegant?",
    "Are you solving the right problem, or is there a simpler root cause?",
    "Take a step back. What is the one thing that must be true for your approach to work?",
    "Is there a completely different file or module where this change should be made?",
]


class LoopRecovery:
    """
    Generates RecoveryActions based on detected loops.

    Different loop types trigger different recovery strategies:
      - Exact repetition: hard stop + redirect
      - Error loop: force deeper analysis of the error
      - Semantic loop: expand search space
      - Stall: replan or request user input
    """

    def __init__(self, llm: LLMClient, config: AppConfig) -> None:
        self.llm = llm
        self.config = config

    async def recover(
        self,
        detection: LoopDetection,
        state: AgentState,
    ) -> RecoveryAction:
        """
        Generate a recovery action for the given loop detection.

        The strategy is selected based on loop type.  Each strategy
        may use the LLM for replanning or simply inject a prompt.
        """
        logger.info(
            "Recovering from loop: type=%s severity=%s",
            detection.loop_type.value,
            detection.severity.value,
        )

        if detection.loop_type == LoopType.EXACT_REPETITION:
            return self._recover_exact_repetition(detection, state)
        elif detection.loop_type == LoopType.ERROR_LOOP:
            return await self._recover_error_loop(detection, state)
        elif detection.loop_type == LoopType.SEMANTIC_LOOP:
            return self._recover_semantic_loop(detection, state)
        elif detection.loop_type == LoopType.STALL:
            return await self._recover_stall(detection, state)

        # Fallback: generic intervention
        return RecoveryAction(
            inject_message="A potential loop was detected. Please reconsider your approach.",
            force_think=True,
        )

    # ── Exact repetition recovery ─────────────────────────────

    def _recover_exact_repetition(
        self,
        detection: LoopDetection,
        state: AgentState,
    ) -> RecoveryAction:
        """
        Hard stop for exact repetitions.

        The agent is doing the same thing over and over — it needs
        a strong signal to change course entirely.
        """
        tool_name = ""
        if detection.repeated_actions and detection.repeated_actions[0].tool_call:
            tool_name = detection.repeated_actions[0].tool_call.name

        message = (
            "CRITICAL: You are repeating the exact same action "
            f"({tool_name} with identical arguments). "
            "This indicates a bug in your reasoning. "
            "You MUST choose a completely different approach. "
            "Consider:\n"
            "1. Reading more context around the area you are trying to change\n"
            "2. Using a different tool or search strategy\n"
            "3. Asking the user for clarification\n"
        )

        return RecoveryAction(
            inject_message=message,
            force_think=True,
            max_retries=0,
            force_user_intervention=True,
        )

    # ── Error loop recovery ───────────────────────────────────

    async def _recover_error_loop(
        self,
        detection: LoopDetection,
        state: AgentState,
    ) -> RecoveryAction:
        """
        Escalate from the current approach when the same error
        keeps appearing.

        Forces the agent to read the full error, consider whether
        it is editing the right file, and think about dependencies.
        """
        error_desc = detection.recurring_error or "unknown error"

        # Summarise what the agent has tried
        previous_actions = self._summarise_recent_actions(state, max_steps=4)

        message = (
            f"LOOP DETECTED: You have encountered the same error "
            f"{len(detection.repeated_actions)} times.\n\n"
            f"Error that is recurring:\n{error_desc[:300]}\n\n"
            f"Actions you have already tried:\n{previous_actions}\n\n"
            "Your current approach is not working. You must:\n"
            "1. STOP trying variations of what you have been doing\n"
            "2. Read the FULL error message carefully, including any stack trace\n"
            "3. Consider whether you are editing the RIGHT file "
            "(maybe the error is caused elsewhere)\n"
            "4. Consider whether you need to install a dependency or update configuration\n"
            "5. If stuck, describe the problem clearly and ask the user for guidance\n"
        )

        return RecoveryAction(
            inject_message=message,
            force_think=True,
            suggest_tools=["read_file", "find_symbols", "search_code", "run_command"],
        )

    # ── Semantic loop recovery ────────────────────────────────

    def _recover_semantic_loop(
        self,
        detection: LoopDetection,
        state: AgentState,
    ) -> RecoveryAction:
        """
        Expand the search space when the agent is trying
        slightly different variations of the same approach.
        """
        divergence = random.choice(_DIVERGENCE_PROMPTS)

        message = (
            "You have been trying similar approaches multiple times without success. "
            f"Ask yourself: {divergence}\n\n"
            "Alternative approaches to consider:\n"
            "- List the directory structure to understand the project layout\n"
            "- Try a broader search (different query terms)\n"
            "- Check if this functionality already exists elsewhere in the codebase\n"
            "- Look at imports and dependencies for clues\n"
            "- Consider that you might need to CREATE something new rather than find it\n"
        )

        return RecoveryAction(
            inject_message=message,
            force_think=True,
            suggest_tools=["list_directory", "search_code", "find_symbols"],
        )

    # ── Stall recovery ────────────────────────────────────────

    async def _recover_stall(
        self,
        detection: LoopDetection,
        state: AgentState,
    ) -> RecoveryAction:
        """
        Replan or request user input when no progress is being made.

        Uses a lightweight LLM call to suggest an alternative approach.
        """
        # Summarise current state for replanning
        state_summary = self._summarise_state(state)

        # Use the LLM to suggest a different approach
        try:
            suggestion = await self._llm_suggest_alternative(state_summary)
        except Exception:
            suggestion = "No alternative suggestion available."

        message = (
            "No progress has been made in recent steps. "
            "The current approach may be fundamentally flawed.\n\n"
            f"Suggested alternative approach:\n{suggestion}\n\n"
            "If you are unsure how to proceed, ask the user for guidance."
        )

        return RecoveryAction(
            inject_message=message,
            reset_working_memory=True,
            suggest_tools=["list_directory", "read_file", "run_command"],
        )

    # ── LLM-assisted recovery ─────────────────────────────────

    async def _llm_suggest_alternative(self, state_summary: str) -> str:
        """
        Ask the LLM to suggest a different approach.

        Uses a short, focused prompt to minimise token cost.
        """
        from coding_agent.types import Message as Msg
        from coding_agent.types import Role

        prompt = (
            "The agent is stuck. Suggest ONE different approach or ask "
            "a clarifying question. Be concise (2-3 sentences max).\n\n"
            f"Current state:\n{state_summary}\n\n"
            "Suggestion:"
        )

        messages = [Msg(role=Role.USER, content=prompt)]
        response = await self.llm.chat(
            messages=messages,
            temperature=0.7,
            max_tokens=150,
        )
        return response.content.strip()

    # ── Helpers ────────────────────────────────────────────────

    @staticmethod
    def _summarise_recent_actions(state: AgentState, max_steps: int = 4) -> str:
        """Create a short summary of the agent's recent actions."""
        recent = state.steps[-max_steps:]
        if not recent:
            return "(no recent actions)"

        lines: list[str] = []
        for step in recent:
            if step.tool_call:
                args_summary = ", ".join(
                    f"{k}={str(v)[:30]}" for k, v in list(step.tool_call.arguments.items())[:2]
                )
                result = "ok" if step.tool_result and step.tool_result.success else "error"
                lines.append(f"  {step.tool_call.name}({args_summary}) -> {result}")
            else:
                lines.append("  (reasoning only)")

        return "\n".join(lines)

    @staticmethod
    def _summarise_state(state: AgentState) -> str:
        """Create a brief state summary for replanning."""
        parts: list[str] = [
            f"Task: {state.task[:100]}",
            f"Steps taken: {state.step_count}",
            f"Files modified: "
            f"{', '.join(state.files_modified) if state.files_modified else 'none'}",
            f"Files read: {', '.join(list(state.files_read)[-5:]) if state.files_read else 'none'}",
        ]
        if state.last_error:
            parts.append(f"Last error: {state.last_error[:100]}")
        if state.plan and state.plan.current_subtask:
            parts.append(f"Current subtask: {state.plan.current_subtask.description[:80]}")
        return "\n".join(parts)
