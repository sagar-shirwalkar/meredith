"""
Token budget tracker with per-zone accounting.

Every token added to the context window has a cost.  This module
tracks cumulative usage, enforces per-step caps, and signals when
compression is necessary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from coding_agent.config import StepAllocConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ZoneUsage:
    """Token usage record for a single context zone."""

    allocated: int = 0
    used: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.allocated - self.used)


class TokenBudget:
    """
    Tracks token usage across context zones and enforces limits.

    Usage::

        budget = TokenBudget(total=128000, step_allocations=cfg.budget.step_allocations)
        if budget.can_execute(estimated=500):
            budget.record_usage(500)
    """

    def __init__(
        self,
        total: int,
        step_allocations: StepAllocConfig,
        max_fraction_per_step: float = 0.10,
        reserved_for_system: int = 4000,
        reserved_for_response: int = 4096,
    ) -> None:
        self.total = total
        self.step_allocations = step_allocations
        self.max_fraction_per_step = max_fraction_per_step
        self.reserved_for_system = reserved_for_system
        self.reserved_for_response = reserved_for_response

        # Available budget after system prompt + response reservation
        self.available = total - reserved_for_system - reserved_for_response

        # Cumulative tracking
        self.used_total: int = 0
        self.used_this_step: int = 0
        self.step_number: int = 0

        # Per-zone tracking (zone names → ZoneUsage)
        self.zones: dict[str, ZoneUsage] = {}

    # ── Core queries ──────────────────────────────────────────

    def remaining(self) -> int:
        """Absolute tokens remaining in the budget."""
        return max(0, self.available - self.used_total)

    def remaining_fraction(self) -> float:
        """Fraction of available budget remaining (0.0 – 1.0)."""
        if self.available == 0:
            return 0.0
        return self.remaining() / self.available

    def can_execute(self, estimated_tokens: int) -> bool:
        """
        Check whether an operation costing *estimated_tokens* can proceed.

        Enforces two constraints:
          1. Must not exceed max_fraction_per_step of remaining budget.
          2. Must leave at least 5% of available budget as headroom.
        """
        rem = self.remaining()
        max_for_step = int(rem * self.max_fraction_per_step)
        headroom = int(self.available * 0.05)

        if estimated_tokens > max_for_step:
            logger.debug(
                "Budget reject: est=%d > max_step=%d (remaining=%d)",
                estimated_tokens, max_for_step, rem,
            )
            return False

        if (rem - estimated_tokens) < headroom:
            logger.debug(
                "Budget reject: would leave only %d < headroom %d",
                rem - estimated_tokens, headroom,
            )
            return False

        return True

    # ── Recording usage ───────────────────────────────────────

    def record_usage(self, tokens: int, zone: str | None = None) -> None:
        """
        Record token consumption.

        Args:
            tokens: Number of tokens consumed.
            zone: Optional zone name for per-zone accounting.
        """
        self.used_total += tokens
        self.used_this_step += tokens

        if zone:
            if zone not in self.zones:
                self.zones[zone] = ZoneUsage()
            self.zones[zone].used += tokens

    def start_new_step(self) -> None:
        """Reset per-step counters at the beginning of a new ReAct step."""
        self.used_this_step = 0
        self.step_number += 1

    # ── Zone allocation ───────────────────────────────────────

    def set_zone_allocation(self, zone: str, max_tokens: int) -> None:
        """Set the token budget for a specific context zone."""
        if zone not in self.zones:
            self.zones[zone] = ZoneUsage(allocated=max_tokens)
        else:
            self.zones[zone].allocated = max_tokens

    def zone_remaining(self, zone: str) -> int:
        """Tokens remaining in a specific zone's budget."""
        if zone not in self.zones:
            return 0
        return self.zones[zone].remaining

    def zone_is_over(self, zone: str) -> bool:
        """Check if a zone has exceeded its allocation."""
        if zone not in self.zones:
            return False
        zu = self.zones[zone]
        return zu.allocated > 0 and zu.used > zu.allocated

    # ── Estimation helpers ────────────────────────────────────

    def estimate_tool_output(self, tool_name: str, params: dict) -> int:
        """
        Rough estimate of how many tokens a tool call will produce.

        Used by the router to decide whether a tool call is affordable.
        """
        if tool_name == "read_file":
            # Estimate ~3 tokens per line (code is denser than prose)
            lines = params.get("end_line", 50) - params.get("start_line", 1)
            return max(50, lines * 3)
        elif tool_name == "search_code":
            return self.step_allocations.tool_result
        elif tool_name in ("find_symbols", "find_references"):
            return 200
        elif tool_name == "run_command":
            return 500
        elif tool_name == "list_directory":
            return 300
        else:
            return 800  # conservative default

    # ── Reporting ─────────────────────────────────────────────

    def summary(self) -> str:
        """One-line budget summary for logging."""
        pct = self.remaining_fraction() * 100
        return (
            f"Budget: {self.used_total}/{self.available} used "
            f"({pct:.1f}% remaining, step #{self.step_number})"
        )
