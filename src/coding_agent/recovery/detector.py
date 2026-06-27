"""
Loop detector: examines recent agent steps to identify
repetitive patterns that indicate the agent is stuck.

Four detection modes:
  1. Exact repetition — same tool + same args
  2. Semantic loop   — same tool, similar args (e.g. search variants)
  3. Error loop      — same error message recurring
  4. Stall           — no measurable progress over N steps
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from coding_agent.config import RecoveryConfig
from coding_agent.types import LoopDetection, LoopType, Severity, Step

logger = logging.getLogger(__name__)


class LoopDetector:
    """
    Detects loops in the agent's recent action history.

    Called after every step by the agent core.  When a loop is
    detected, returns a LoopDetection object that triggers
    recovery strategies.
    """

    def __init__(self, config: RecoveryConfig) -> None:
        self.config = config
        self._history: list[Step] = []

    def check(self, step: Step) -> LoopDetection | None:
        """
        Check whether the latest step indicates a loop.

        Examines the last N steps (configurable window size).
        Returns a LoopDetection if a loop is found, None otherwise.
        """
        self._history.append(step)

        window = self.config.loop_detection_window
        if len(self._history) < 4:
            return None

        recent = self._history[-window:]

        # Run all detection methods; return the first hit
        result = (
            self._check_exact_repetition(recent)
            or self._check_error_loop(recent)
            or self._check_semantic_loop(recent)
            or self._check_stall(recent)
        )

        if result:
            logger.warning(
                "Loop detected: type=%s severity=%s",
                result.loop_type.value,
                result.severity.value,
            )

        return result

    # ── Exact repetition ──────────────────────────────────────

    def _check_exact_repetition(self, recent: list[Step]) -> LoopDetection | None:
        """
        Detect when the exact same tool call is repeated.

        Compares tool name + serialised arguments.  If the same
        fingerprint appears more than N times, it is a loop.
        """
        threshold = self.config.exact_repetition_threshold
        fingerprints: dict[str, int] = {}

        for step in recent:
            if not step.tool_call:
                continue
            fp = self._fingerprint(step.tool_call.name, step.tool_call.arguments)
            fingerprints[fp] = fingerprints.get(fp, 0) + 1

            if fingerprints[fp] >= threshold:
                return LoopDetection(
                    loop_type=LoopType.EXACT_REPETITION,
                    severity=Severity.HIGH,
                    repeated_actions=recent[-threshold:],
                    message=(
                        f"Tool '{step.tool_call.name}' called with identical "
                        f"arguments {fingerprints[fp]} times"
                    ),
                )

        return None

    # ── Error loop ────────────────────────────────────────────

    def _check_error_loop(self, recent: list[Step]) -> LoopDetection | None:
        """
        Detect when the same error message appears repeatedly.

        Normalises error messages (strips line numbers, variable
        values) to catch structurally identical errors.
        """
        threshold = self.config.error_repetition_threshold
        errors: dict[str, int] = {}

        for step in recent:
            if not step.tool_result or step.tool_result.success:
                continue
            normalised = self._normalise_error(step.tool_result.error or step.tool_result.output)
            if not normalised:
                continue
            errors[normalised] = errors.get(normalised, 0) + 1

            if errors[normalised] >= threshold:
                return LoopDetection(
                    loop_type=LoopType.ERROR_LOOP,
                    severity=Severity.HIGH,
                    recurring_error=normalised,
                    repeated_actions=recent[-threshold:],
                    message=(
                        f"Same error occurred {errors[normalised]} times: "
                        f"{normalised[:100]}"
                    ),
                )

        return None

    # ── Semantic loop ─────────────────────────────────────────

    def _check_semantic_loop(self, recent: list[Step]) -> LoopDetection | None:
        """
        Detect when the agent is making semantically similar calls
        with slightly different arguments (e.g. search variants).

        Uses simple heuristics:
          - Same tool called 4+ times
          - Same file edited 3+ times
          - Search queries with high string similarity
        """
        # Group by tool name
        tool_counts: dict[str, list[Step]] = {}
        for step in recent:
            if not step.tool_call:
                continue
            tool_counts.setdefault(step.tool_call.name, []).append(step)

        # Check: same tool 4+ times
        for tool_name, steps in tool_counts.items():
            if len(steps) >= 4:
                # Check if the arguments are similar (not exact duplicates,
                # which would have been caught by exact_repetition)
                if self._args_are_similar(steps):
                    return LoopDetection(
                        loop_type=LoopType.SEMANTIC_LOOP,
                        severity=Severity.MEDIUM,
                        repeated_actions=steps[-4:],
                        message=(
                            f"Tool '{tool_name}' called {len(steps)} times "
                            f"with similar but not identical arguments"
                        ),
                    )

        # Check: same file edited 3+ times
        file_edits: dict[str, int] = {}
        for step in recent:
            if step.tool_call and step.tool_call.name == "edit_file":
                path = step.tool_call.arguments.get("path", "")
                if path:
                    file_edits[path] = file_edits.get(path, 0) + 1

        for path, count in file_edits.items():
            if count >= 3:
                return LoopDetection(
                    loop_type=LoopType.SEMANTIC_LOOP,
                    severity=Severity.MEDIUM,
                    repeated_actions=recent[-count:],
                    message=(
                        f"File '{path}' edited {count} times — "
                        f"agent may be oscillating on this file"
                    ),
                )

        return None

    # ── Stall detection ───────────────────────────────────────

    def _check_stall(self, recent: list[Step]) -> LoopDetection | None:
        """
        Detect when the agent is making no measurable progress.

        A stall is when N consecutive steps produce no state change:
        no files modified, no tests fixed, no diagnostics cleared.
        """
        stall_steps = self.config.stall_steps
        if len(recent) < stall_steps:
            return None

        # Check if any of the recent steps actually changed something
        has_progress = False
        for step in recent[-stall_steps:]:
            if step.tool_call and step.tool_result:
                # Edits and writes count as progress
                if step.tool_call.name in ("edit_file", "write_file"):
                    has_progress = True
                    break
                # Successful commands that produce output count
                if step.tool_call.name == "run_command" and step.tool_result.success:
                    # But only if the output suggests something changed
                    output = step.tool_result.output.lower()
                    if any(word in output for word in ("passed", "succeeded", "created", "updated")):
                        has_progress = True
                        break

        if not has_progress:
            return LoopDetection(
                loop_type=LoopType.STALL,
                severity=Severity.MEDIUM,
                repeated_actions=recent[-stall_steps:],
                message=(
                    f"No measurable progress in the last {stall_steps} steps"
                ),
            )

        return None

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _fingerprint(tool_name: str, arguments: dict[str, Any]) -> str:
        """
        Create a stable fingerprint for a tool call.

        Used for exact-repetition detection.
        """
        # Sort keys for stability
        args_str = str(sorted(arguments.items()))
        raw = f"{tool_name}:{args_str}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _normalise_error(error: str) -> str:
        """
        Normalise an error message for comparison.

        Strips line numbers, variable values, and paths to
        catch structurally identical errors regardless of specifics.
        """
        if not error:
            return ""
        # Remove specific line numbers
        normalised = re.sub(r"line \d+", "line N", error)
        # Remove specific file paths (keep filename only)
        normalised = re.sub(r"/[\w./\-]+\.py", "<file>.py", normalised)
        normalised = re.sub(r"/[\w./\-]+\.ts", "<file>.ts", normalised)
        # Remove hex addresses
        normalised = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", normalised)
        # Truncate
        return normalised[:200]

    @staticmethod
    def _args_are_similar(steps: list[Step]) -> bool:
        """
        Check if the arguments of multiple tool calls are similar
        but not identical (indicating the agent is trying variants).

        Simple heuristic: if the arguments share >60% of words,
        they are considered similar.
        """
        if len(steps) < 2:
            return False

        word_sets: list[set[str]] = []
        for step in steps:
            if not step.tool_call:
                continue
            args_text = " ".join(str(v) for v in step.tool_call.arguments.values())
            words = set(args_text.lower().split())
            word_sets.append(words)

        if len(word_sets) < 2:
            return False

        # Compare each pair
        similar_count = 0
        total_pairs = 0
        for i in range(len(word_sets)):
            for j in range(i + 1, len(word_sets)):
                if not word_sets[i] or not word_sets[j]:
                    continue
                intersection = word_sets[i] & word_sets[j]
                union = word_sets[i] | word_sets[j]
                jaccard = len(intersection) / len(union) if union else 0
                total_pairs += 1
                if jaccard > 0.5:
                    similar_count += 1

        # If more than half of pairs are similar
        return total_pairs > 0 and similar_count / total_pairs > 0.5


# Need re for _normalise_error
import re
