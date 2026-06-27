"""
Hierarchical context window manager.

The context window is divided into priority-ordered zones:
  immutable  → System prompt, tool schemas (never compressed)
  task       → Current task / subtask description
  working    → Recent tool call/result pairs (full fidelity)
  episodic   → Summarised history of earlier steps
  semantic   → Project conventions, AGENTS.md, memories
  scratch    → Agent scratchpad, recovery interventions

When a zone exceeds its token budget, the manager compresses or
evicts content: working → episodic (summarise), episodic → trim.
Emergency compression can drop semantic and truncate working.
"""

from __future__ import annotations

import logging
from typing import Any

from coding_agent.config import AppConfig, ZoneConfig
from coding_agent.context.budget import TokenBudget
from coding_agent.context.compressor import OutputCompressor
from coding_agent.llm.base import count_tokens
from coding_agent.types import ContextItem, Step, ZoneName

logger = logging.getLogger(__name__)


class ContextManager:
    """
    Manages the hierarchical context window.

    Each zone is a list of ContextItem instances.  Items are added
    by the agent core and evicted/compressed when budgets are tight.
    """

    def __init__(self, config: AppConfig, budget: TokenBudget) -> None:
        self.config = config
        self.budget = budget
        self.compressor = OutputCompressor()

        # Zone storage: zone_name → list of ContextItem
        self.zones: dict[str, list[ContextItem]] = {
            name: [] for name in ZoneName
        }

        # Configure zone allocations in the budget
        for name, zcfg in config.context.zones.items():
            self.budget.set_zone_allocation(name, zcfg.max_tokens)

    # ── Adding content ────────────────────────────────────────

    def add(
        self,
        zone: str,
        content: str,
        source: str = "agent",
        compressible: bool = True,
    ) -> None:
        """
        Add content to a context zone.

        Args:
            zone: Zone name (must be a ZoneName value).
            content: The text to add.
            source: Origin label (e.g. "tool_result", "memory").
            compressible: Whether this can be truncated/summarised.
        """
        tokens = count_tokens(content)
        item = ContextItem(
            content=content,
            source=source,
            token_count=tokens,
            compressible=compressible,
        )
        self.zones[zone].append(item)
        self.budget.record_usage(tokens, zone=zone)

        # Check if this zone is now over budget
        if self.budget.zone_is_over(zone):
            self._trim_zone(zone)

    def set_immutable(self, content: str) -> None:
        """Set the immutable zone (system prompt + tool schemas)."""
        self.zones[ZoneName.IMMUTABLE] = [
            ContextItem(
                content=content,
                source="system",
                token_count=count_tokens(content),
                compressible=False,
            )
        ]

    def inject_scratch(self, content: str) -> None:
        """Inject a message into the scratch zone (e.g. recovery intervention)."""
        self.add(ZoneName.SCRATCH, content, source="intervention", compressible=True)

    # ── Recording steps ───────────────────────────────────────

    def record_step(self, step: Step) -> None:
        """
        Record a completed step into the context.

        The tool call and result go into working memory.  If working
        memory is over budget, the oldest items are compressed into
        episodic memory.
        """
        if step.tool_call and step.tool_result:
            # Format the step for working memory
            call_desc = f"{step.tool_call.name}({self._summarise_args(step.tool_call.arguments)})"
            result_text = step.tool_result.output

            # Compress the result before storing
            budget_frac = self.budget.remaining_fraction()
            result_text = self.compressor.compress(
                step.tool_call.name,
                result_text,
                {"budget_remaining": budget_frac},
            )

            entry = f"[Step {step.step_number}] {call_desc}\n{result_text}"
            self.add(ZoneName.WORKING, entry, source="step", compressible=True)

        # Check if we need to rotate working → episodic
        if self.budget.zone_is_over(ZoneName.WORKING):
            self._rotate_working_to_episodic()

    # ── Building the context ──────────────────────────────────

    def build_context_string(self) -> str:
        """
        Assemble all zones into a single context string.

        Zones are rendered in priority order (lower priority number
        first).  Each zone is truncated to fit its allocation.
        """
        parts: list[str] = []
        sorted_zones = sorted(
            self.config.context.zones.items(),
            key=lambda kv: kv[1].priority,
        )

        for zone_name, zone_cfg in sorted_zones:
            items = self.zones.get(zone_name, [])
            if not items:
                continue

            zone_text = self._render_zone(items, zone_cfg.max_tokens)
            if zone_text:
                parts.append(zone_text)

        return "\n\n".join(parts)

    def _render_zone(self, items: list[ContextItem], max_tokens: int) -> str:
        """Render a zone's items, trimming to fit max_tokens."""
        rendered: list[str] = []
        token_count = 0

        for item in items:
            text = item.content
            tokens = count_tokens(text)

            if token_count + tokens > max_tokens:
                # Try to fit a truncated version
                remaining = max_tokens - token_count
                if remaining > 50:
                    truncated = self._truncate_to_tokens(text, remaining - 10)
                    rendered.append(truncated + "\n[...truncated]")
                    token_count += remaining
                break

            rendered.append(text)
            token_count += tokens

        return "\n".join(rendered)

    # ── Compression and eviction ──────────────────────────────

    def _trim_zone(self, zone: str) -> None:
        """Remove or compress the oldest items in a zone to free space."""
        items = self.zones.get(zone, [])
        if not items:
            return

        # Remove the oldest compressible item
        for i, item in enumerate(items):
            if item.compressible:
                removed = items.pop(i)
                self.budget.record_usage(-removed.token_count, zone=zone)
                logger.debug("Trimmed 1 item from zone %s (%d tokens freed)", zone, removed.token_count)
                return

    def _rotate_working_to_episodic(self) -> None:
        """
        Move the oldest working memory items into episodic memory.

        Each moved item is summarised into a one-liner to save space.
        """
        working = self.zones[ZoneName.WORKING]
        if len(working) < 3:
            return

        # Move the oldest 2 items
        to_move = working[:2]
        del working[:2]

        for item in to_move:
            summary = self._summarise_item(item)
            self.add(ZoneName.EPISODIC, summary, source="working_rotation", compressible=True)
            self.budget.record_usage(-item.token_count, zone=ZoneName.WORKING)
            logger.debug("Rotated working → episodic: %s", summary[:60])

        # Check if episodic is now over budget
        if self.budget.zone_is_over(ZoneName.EPISODIC):
            self._compress_episodic()

    def _compress_episodic(self) -> None:
        """
        Compress episodic memory by merging older entries.

        Instead of LLM summarisation (which costs tokens), we use
        template-based compression: keep the first and last entries,
        replace the middle with a count.
        """
        items = self.zones[ZoneName.EPISODIC]
        if len(items) <= 3:
            return

        # Keep first and last, summarise the middle
        first = items[0]
        last = items[-1]
        middle_count = len(items) - 2
        middle_tokens = sum(it.token_count for it in items[1:-1])

        summary_text = f"[...{middle_count} earlier steps omitted ({middle_tokens} tokens)...]"

        new_items = [
            first,
            ContextItem(
                content=summary_text,
                source="compression",
                token_count=count_tokens(summary_text),
                compressible=False,
            ),
            last,
        ]

        # Update budget
        old_tokens = sum(it.token_count for it in items)
        new_tokens = sum(it.token_count for it in new_items)
        delta = new_tokens - old_tokens
        self.budget.record_usage(delta, zone=ZoneName.EPISODIC)

        self.zones[ZoneName.EPISODIC] = new_items
        logger.debug("Compressed episodic: %d items → %d", len(items), len(new_items))

    def emergency_compress(self) -> None:
        """
        Aggressive compression when budget is critically low.

        Actions:
          1. Compress episodic memory
          2. Truncate all working memory outputs to 250 chars each
          3. Drop semantic memory entirely
          4. Drop scratch memory
        """
        logger.warning("Emergency context compression triggered")

        # 1. Compress episodic
        self._compress_episodic()

        # 2. Truncate working memory
        for item in self.zones[ZoneName.WORKING]:
            if item.compressible and len(item.content) > 250:
                original_tokens = item.token_count
                item.content = item.content[:125] + "\n...[truncated]...\n" + item.content[-125:]
                item.token_count = count_tokens(item.content)
                delta = item.token_count - original_tokens
                self.budget.record_usage(delta, zone=ZoneName.WORKING)

        # 3. Drop semantic memory
        dropped_tokens = sum(it.token_count for it in self.zones[ZoneName.SEMANTIC])
        self.zones[ZoneName.SEMANTIC] = []
        self.budget.record_usage(-dropped_tokens, zone=ZoneName.SEMANTIC)

        # 4. Drop scratch memory
        dropped_tokens = sum(it.token_count for it in self.zones[ZoneName.SCRATCH])
        self.zones[ZoneName.SCRATCH] = []
        self.budget.record_usage(-dropped_tokens, zone=ZoneName.SCRATCH)

    def reset_working(self) -> None:
        """Clear working memory (used during loop recovery)."""
        dropped_tokens = sum(it.token_count for it in self.zones[ZoneName.WORKING])
        self.zones[ZoneName.WORKING] = []
        self.budget.record_usage(-dropped_tokens, zone=ZoneName.WORKING)

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _summarise_args(args: dict[str, Any]) -> str:
        """One-line summary of tool call arguments."""
        parts: list[str] = []
        for k, v in list(args.items())[:3]:
            v_str = repr(v) if len(repr(v)) < 40 else repr(v)[:37] + "..."
            parts.append(f"{k}={v_str}")
        return ", ".join(parts)

    @staticmethod
    def _summarise_item(item: ContextItem) -> str:
        """Create a one-line summary of a context item."""
        text = item.content.replace("\n", " ").strip()
        if len(text) > 100:
            return text[:97] + "..."
        return text

    @staticmethod
    def _truncate_to_tokens(text: str, target_tokens: int) -> str:
        """Truncate text to approximately *target_tokens* tokens."""
        # Rough: 4 chars per token for code
        char_limit = target_tokens * 4
        if len(text) <= char_limit:
            return text
        return text[:char_limit]
