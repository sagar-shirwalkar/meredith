"""
Adaptive Context Compactor: graduated 6-stage compaction pipeline.

Stages are applied cheapest-first as budget decreases. Each stage
is independently revertible (for stages 1-4) or uses serialized
rehydration data (stages 5-6).

Reference: Claude Code's 5-tier compaction pipeline, adapted for
Meredith's zone-based context model.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from coding_agent.config import CompressionConfig
from coding_agent.types import (
    CompactionStage,
    ContextCompressionResult,
    Message,
    RehydrationData,
    Role,
)

logger = logging.getLogger(__name__)


class ContextCompactor:
    """
    Orchestrates graduated context compaction.

    Usage:
        compactor = ContextCompactor(config)
        result = compactor.compact(messages, budget_remaining)
        if result.rehydration_needed:
            rehydration_data = compactor.last_rehydration
            # restore: plan, files, skills, tool states
    """

    def __init__(self, config: CompressionConfig) -> None:
        self.config = config
        self.last_rehydration: RehydrationData | None = None
        self._current_stage = CompactionStage.NONE

    # ── Main entry point ──────────────────────────────────────

    def compact(
        self,
        messages: list[Message],
        budget_remaining: float,
    ) -> list[Message]:
        """
        Apply the appropriate compaction stage based on remaining budget.

        Returns the compacted message list. Mutates in place.
        """
        stage = self._select_stage(budget_remaining)
        if stage == CompactionStage.NONE:
            return messages

        if stage <= self._current_stage:
            return messages

        logger.info("Compaction stage %s (budget=%.1f%%)", stage.name, budget_remaining * 100)

        result = self._apply_stage(stage, messages)
        self._current_stage = stage

        logger.info(
            "Compacted: stage=%s saved=%d tokens ratio=%.2f",
            stage.name,
            result.savings,
            result.compression_ratio,
        )
        return messages

    def _select_stage(self, budget_remaining: float) -> CompactionStage:
        """Select compaction stage based on remaining budget fraction."""
        cfg = self.config
        if budget_remaining >= cfg.stage1_budget_reduction:
            return CompactionStage.NONE
        if budget_remaining >= cfg.stage2_observation_masking:
            return CompactionStage.BUDGET_REDUCTION
        if budget_remaining >= cfg.stage3_fast_pruning:
            return CompactionStage.OBSERVATION_MASKING
        if budget_remaining >= cfg.stage4_aggressive_compression:
            return CompactionStage.FAST_PRUNING
        if budget_remaining >= cfg.stage5_reversible_collapse:
            return CompactionStage.AGGRESSIVE_COMPRESSION
        if budget_remaining >= cfg.stage6_full_llm:
            return CompactionStage.REVERSIBLE_COLLAPSE
        return CompactionStage.FULL_LLM_SUMMARIZATION

    # ── Stage implementations ─────────────────────────────────

    def _apply_stage(
        self,
        stage: CompactionStage,
        messages: list[Message],
    ) -> ContextCompressionResult:
        """Apply the selected compaction stage."""
        original = sum(m.token_estimate() for m in messages)

        if stage == CompactionStage.BUDGET_REDUCTION:
            self._stage_budget_reduction(messages)
        elif stage == CompactionStage.OBSERVATION_MASKING:
            self._stage_observation_masking(messages)
        elif stage == CompactionStage.FAST_PRUNING:
            self._stage_fast_pruning(messages)
        elif stage == CompactionStage.AGGRESSIVE_COMPRESSION:
            self._stage_aggressive_compression(messages)
        elif stage == CompactionStage.REVERSIBLE_COLLAPSE:
            self._stage_reversible_collapse(messages)
        elif stage == CompactionStage.FULL_LLM_SUMMARIZATION:
            # Stage 6 requires async LLM call — handled by the caller
            logger.warning("Stage 6 (LLM summarization) requires async — caller must invoke")
            pass

        compressed = sum(m.token_estimate() for m in messages)
        return ContextCompressionResult(
            stage=stage,
            original_tokens=original,
            compressed_tokens=compressed,
        )

    # ── Stage 1: Budget Reduction ─────────────────────────────

    def _stage_budget_reduction(self, messages: list[Message]) -> None:
        """
        Cap tool outputs per-zone.

        Every TOOL-role message gets its content truncated to
        a zone-appropriate length. No messages are removed.
        """
        for msg in messages:
            if msg.role == Role.TOOL and len(msg.content) > 2000:
                lines = msg.content.split("\n")
                if len(lines) > 40:
                    head = "\n".join(lines[:15])
                    tail = "\n".join(lines[-10:])
                    msg.content = f"{head}\n... [{len(lines) - 25} lines omitted] ...\n{tail}"

    # ── Stage 2: Observation Masking ───────────────────────────

    def _stage_observation_masking(self, messages: list[Message]) -> None:
        """
        Replace older tool results with compact reference pointers.

        The most recent N tool outputs (protected_recency_steps) are
        retained at full fidelity. Older ones are replaced with a
        one-line summary.
        """
        protected = self.config.protected_recency_steps
        tool_indices = [i for i, m in enumerate(messages) if m.role == Role.TOOL]

        # Protect the most recent N tool results
        protect_from = max(0, len(tool_indices) - protected)
        protected_set = set(tool_indices[protect_from:])

        for i, msg in enumerate(messages):
            if msg.role == Role.TOOL and i not in protected_set and len(msg.content) > 200:
                summary = msg.content[:100].replace("\n", " ").strip()
                msg.content = f"[output offloaded to scratch — summary: {summary}]"

    # ── Stage 3: Fast Pruning ─────────────────────────────────

    def _stage_fast_pruning(self, messages: list[Message]) -> None:
        """
        Drop tool outputs below MIN_LENGTH threshold.

        Only drops TOOL messages. Preserves messages within the
        protected recency window.
        """
        protected = self.config.protected_recency_steps
        min_length = self.config.min_output_length_for_pruning

        tool_indices = [i for i, m in enumerate(messages) if m.role == Role.TOOL]
        protect_from = max(0, len(tool_indices) - protected)
        protected_set = set(tool_indices[protect_from:])

        removals: list[int] = []
        for i, msg in enumerate(messages):
            if msg.role == Role.TOOL and i not in protected_set and len(msg.content) < min_length:
                removals.append(i)

        # Remove in reverse to preserve indices
        for i in reversed(removals):
            messages.pop(i)

    # ── Stage 4: Aggressive Compression ────────────────────────

    def _stage_aggressive_compression(self, messages: list[Message]) -> None:
        """
        Shrink retention window to only the most recent tool output.

        Mask all older observations with a concise placeholder.
        """
        tool_indices = [i for i, m in enumerate(messages) if m.role == Role.TOOL]

        if not tool_indices:
            return

        keep = set(tool_indices[-2:])

        for i, msg in enumerate(messages):
            if msg.role == Role.TOOL and i not in keep and len(msg.content) > 50:
                msg.content = "[earlier tool output removed]"

    # ── Stage 5: Reversible Collapse ───────────────────────────

    def _stage_reversible_collapse(self, messages: list[Message]) -> None:
        """
        Serialize full conversation to scratch file (non-lossy).

        Then aggressively prune to minimal working set.
        Post-compaction rehydration restores from the scratch file.
        """
        path = Path(self.config.collapse_serialization_path)
        path.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time())
        collapse_file = path / f"collapse_{timestamp}.json"

        # Serialize messages
        serialized = [
            {
                "role": m.role.value,
                "content": m.content,
                "tool_call_id": m.tool_call_id,
                "name": m.name,
                "timestamp": m.timestamp,
            }
            for m in messages
        ]

        collapse_file.write_text(json.dumps(serialized, indent=2, default=str), encoding="utf-8")

        logger.info("Conversation collapsed to %s (%d messages)", collapse_file, len(messages))

        # Aggressively prune — keep system + last user + last 2 assistant+tool pairs
        system_msgs = [m for m in messages if m.role == Role.SYSTEM]
        user_msgs = [m for m in messages if m.role == Role.USER]
        recent = messages[-6:] if len(messages) > 6 else messages[-4:]

        messages.clear()
        messages.extend(system_msgs)
        if user_msgs:
            messages.append(user_msgs[-1])
        messages.extend(recent)

        # Insert collapse marker
        messages.append(
            Message(
                role=Role.SYSTEM,
                content=(
                    f"[Conversation was collapsed to save space. Full history preserved at "
                    f"{collapse_file}. Key context: see rehydration data.]"
                ),
            )
        )

    # ── Stage 6: Full LLM Summarization ────────────────────────

    async def _stage_full_llm_async(
        self,
        messages: list[Message],
        llm_summarize: Any,  # Callable[[str], str]
    ) -> None:
        """
        Full LLM-based summarization of middle portion.

        Two-phase CoT:
          1. LLM writes chain-of-thought reasoning + structured summary
          2. Keep only the conclusion (CoT is consumed, not kept)
        """
        cfg = self.config
        path = Path(cfg.collapse_serialization_path)
        path.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time())
        collapse_file = path / f"collapse_llm_{timestamp}.json"

        serialized = [
            {
                "role": m.role.value,
                "content": m.content,
                "tool_call_id": m.tool_call_id,
                "name": m.name,
                "timestamp": m.timestamp,
            }
            for m in messages
        ]
        collapse_file.write_text(json.dumps(serialized, indent=2, default=str), encoding="utf-8")

        # Select middle portion for summarization (skip first 2 and last 4 messages)
        if len(messages) > 6:
            to_summarize = messages[2:-4]
            keep = messages[:2] + messages[-4:]
        else:
            to_summarize = []
            keep = list(messages)

        if to_summarize and llm_summarize:
            conversation_text = "\n\n".join(
                f"[{m.role.value}] {m.content[:500]}" for m in to_summarize
            )

            summary = llm_summarize(
                f"Compress this conversation.\n"
                f"First, reason step-by-step about what to keep.\n"
                f"Then output a structured summary with:\n"
                f"  - GOAL: What was the task?\n"
                f"  - PROGRESS: What has been done?\n"
                f"  - FINDINGS: What was discovered?\n"
                f"  - NEXT: What remains?\n\n"
                f"{conversation_text}"
            )

            messages.clear()
            messages.extend(keep)
            messages.append(
                Message(
                    role=Role.SYSTEM,
                    content=f"[LLM Summary of earlier conversation]\n{summary}",
                )
            )
            messages.append(
                Message(
                    role=Role.SYSTEM,
                    content=(f"[Full history preserved at {collapse_file}]"),
                )
            )

    # ── Stage 6 public API ────────────────────────────────────

    def should_run_llm_summarization(self, budget_remaining: float) -> bool:
        """
        Returns True when the budget is low enough that Stage 6
        (LLM summarization) should be triggered.

        This is a separate check from compact() so the caller can
        handle the async LLM call in its own event loop context.
        """
        return budget_remaining < self.config.stage6_full_llm

    async def stage_full_llm(
        self,
        messages: list[Message],
        llm_summarize: Any,  # Callable[[str], Awaitable[str]]
    ) -> None:
        """
        Public async wrapper for Stage 6 LLM summarization.

        Mutates *messages* in place with the summarised result
        and stores a reference on self for rehydration.
        """
        await self._stage_full_llm_async(messages, llm_summarize)

    # ── Post-compaction rehydration ────────────────────────────

    def prepare_rehydration(
        self,
        plan_state: dict[str, Any] | None = None,
        modified_files: list[str] | None = None,
        current_phase: str = "",
        skills_remaining: list[str] | None = None,
        tool_states: dict[str, Any] | None = None,
    ) -> RehydrationData:
        """Capture rehydration data before a destructive compaction stage."""
        data = RehydrationData(
            plan_state=plan_state or {},
            modified_files=modified_files or [],
            current_phase=current_phase,
            skills_remaining=skills_remaining or [],
            tool_states=tool_states or {},
        )
        self.last_rehydration = data
        return data

    def restore_rehydration(
        self,
        messages: list[Message],
        data: RehydrationData | None = None,
    ) -> list[Message]:
        """
        Inject rehydration markers after compaction.

        Restores: current plan state, modified files list, skills,
        and tool states. Messages remain compacted.
        """
        d = data or self.last_rehydration
        if d is None:
            return messages

        sections: list[str] = []
        if d.current_phase:
            sections.append(f"Current phase: {d.current_phase}")
        if d.modified_files:
            section = "Modified files: " + ", ".join(d.modified_files[:5])
            if len(d.modified_files) > 5:
                section += f" (+{len(d.modified_files) - 5} more)"
            sections.append(section)
        if d.skills_remaining:
            sections.append("Active skills: " + ", ".join(d.skills_remaining[:3]))
        if d.plan_state:
            sections.append(f"Plan: {json.dumps(d.plan_state, default=str)[:200]}")

        if sections:
            msg = "[Session context restored]\n" + "\n".join(sections)
            messages.append(Message(role=Role.SYSTEM, content=msg))

        return messages
