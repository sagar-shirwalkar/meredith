"""
Tool preference tracker: learns which tools work best for which tasks.

Success/failure rates are tracked per tool and per broad task category
(editing, searching, debugging, web, git).  Preferences are persisted
to a JSON file and reloaded on startup.

Used by ``ToolRouter`` to adjust tool availability weights when
``learned_preferences`` is enabled in config.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Task categories derived from tool name patterns
_TOOL_CATEGORIES: dict[str, str] = {
    "read_file": "reading",
    "write_file": "writing",
    "edit_file": "writing",
    "list_directory": "reading",
    "search_code": "searching",
    "find_symbols": "searching",
    "get_diagnostics": "debugging",
    "run_command": "shell",
    "web_search": "web",
    "web_fetch": "web",
    "git_status": "git",
    "git_diff": "git",
    "git_log": "git",
    "git_commit": "git",
}


class ToolPreferences:
    """
    Lightweight preference tracker for tool selection.

    Tracks success rates per tool and per category.  Higher success
    rates → higher weight in the router's availability ranking.

    Persisted as JSON to *store_path*.
    """

    def __init__(self, store_path: str = ".agent/tool_preferences.json") -> None:
        self._store_path = store_path
        self._data: dict[str, Any] = self._load()

    # ── Public API ────────────────────────────────────────────

    def record_result(
        self,
        tool_name: str,
        success: bool,
        duration_seconds: float = 0.0,
    ) -> None:
        """
        Record a tool execution result.

        Updates both per-tool stats and per-category stats.
        Triggers an asynchronous save (in the caller's event loop
        step via the agent core).
        """
        now = time.time()
        entry: dict[str, Any] = {
            "success": success,
            "duration": duration_seconds,
            "timestamp": now,
        }

        # Per-tool history (rolling window of 50)
        tool_history = self._data.setdefault("tools", {}).setdefault(tool_name, [])
        tool_history.append(entry)
        if len(tool_history) > 50:
            tool_history.pop(0)

        # Per-category history
        category = _TOOL_CATEGORIES.get(tool_name, "other")
        cat_history = self._data.setdefault("categories", {}).setdefault(category, [])
        cat_history.append(entry)
        if len(cat_history) > 100:
            cat_history.pop(0)

        logger.debug(
            "Tool preference: %s → %s (duration=%.1fs)",
            tool_name,
            "ok" if success else "fail",
            duration_seconds,
        )

    def get_weight(self, tool_name: str) -> float:
        """
        Return a weight between 0.0 and 1.0 for the given tool.

        Weight is derived from recent success rate.  Tools with
        no history default to 0.5 (neutral).

        Used by ``ToolRouter.get_available_tools()`` to rank tools
        when ``learned_preferences`` is enabled.
        """
        tool_history = self._data.get("tools", {}).get(tool_name, [])
        if not tool_history:
            return 0.5

        # Recent successes / recent total
        recent = tool_history[-20:]
        successes = sum(1 for e in recent if e["success"])
        rate = successes / len(recent)

        # Map [0,1] → [0.1, 1.0] so even low-rated tools remain available
        return 0.1 + 0.9 * rate

    def get_category_weight(self, category: str) -> float:
        """
        Return the aggregate weight for a whole tool category.
        """
        cat_history = self._data.get("categories", {}).get(category, [])
        if not cat_history:
            return 0.5
        recent = cat_history[-30:]
        successes = sum(1 for e in recent if e["success"])
        rate = successes / len(recent)
        return 0.1 + 0.9 * rate

    def get_preferred_tools(self, min_weight: float = 0.3) -> list[str]:
        """
        Return tool names whose weight is at least *min_weight*.

        Used to filter out tools that have consistently failed.
        """
        result: list[str] = []
        for tool_name in self._data.get("tools", {}):
            if self.get_weight(tool_name) >= min_weight:
                result.append(tool_name)
        return result

    def save(self) -> None:
        """Persist preferences to disk."""
        try:
            path = Path(self._store_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write via temp file + rename
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            tmp.rename(path)
        except OSError as exc:
            logger.warning("Failed to save tool preferences: %s", exc)

    def reset(self) -> None:
        """Clear all learned preferences."""
        self._data = {"tools": {}, "categories": {}}
        self.save()

    # ── Internal ──────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        """Load preferences from disk, or return defaults."""
        try:
            path = Path(self._store_path)
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw)
                # Ensure structure is valid
                if "tools" in data and "categories" in data:
                    return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load tool preferences: %s", exc)
        return {"tools": {}, "categories": {}}
