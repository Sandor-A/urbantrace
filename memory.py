from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


_ENTITY_KEYS = {
    "borough", "zip", "neighborhood", "owner_name_contains",
    "min_sale_price", "max_sale_price", "is_srl", "property_class_contains",
}

_RESULT_SAMPLE_SIZE = 3
_DEFAULT_MAX_HISTORY = 10


@dataclass
class ToolCall:
    """Immutable record of one tool invocation."""
    tool: str
    params: dict[str, Any]
    result_count: int
    result_sample: list[dict[str, Any]]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def short_repr(self) -> str:
        param_str = _fmt_params(self.params)
        return f"{self.tool}({param_str}) → {self.result_count} result(s)"


class SessionMemory:
    """
    Tracks tool-call history, per-tool filter state, and active research
    entities across a conversation session.
    """

    def __init__(self, max_history: int = _DEFAULT_MAX_HISTORY) -> None:
        self._history: deque[ToolCall] = deque(maxlen=max_history)
        # Separate filter dicts per tool so search_properties filters
        # don't contaminate get_market_stats context and vice versa.
        self._filters_by_tool: dict[str, dict[str, Any]] = {}
        # Salient entities currently in focus (borough, ZIP, price range, …)
        self._active_entities: dict[str, Any] = {}
        self._query_count: int = 0

    # ── Write ────────────────────────────────────────────────────────────────

    def update(
        self,
        tool: str,
        params: dict[str, Any] | None = None,
        results: list[dict[str, Any]] | None = None,
    ) -> None:
        params = dict(params or {})
        results = list(results or [])

        self._history.append(ToolCall(
            tool=tool,
            params=params,
            result_count=len(results),
            result_sample=results[:_RESULT_SAMPLE_SIZE],
        ))

        if params:
            self._filters_by_tool.setdefault(tool, {}).update(params)

        self._extract_entities(params, results)
        self._query_count += 1

    def _extract_entities(
        self, params: dict[str, Any], results: list[dict[str, Any]]
    ) -> None:
        for key in _ENTITY_KEYS:
            value = params.get(key)
            if value is not None and value != "":
                self._active_entities[key] = value

        # Infer a single-borough focus from result rows when not explicit.
        if results and "borough" not in params:
            boroughs = {r.get("borough") for r in results if r.get("borough")}
            if len(boroughs) == 1:
                self._active_entities["inferred_borough"] = boroughs.pop()
            else:
                self._active_entities.pop("inferred_borough", None)

    # ── Read ─────────────────────────────────────────────────────────────────

    def get(self) -> dict[str, Any]:
        """Backward-compatible accessor used by the fast-path follow-up."""
        if not self._history:
            return {}
        last = self._history[-1]
        return {
            "last_tool": last.tool,
            "filters": self._filters_by_tool.get(last.tool, {}),
            "last_results": last.result_sample,
        }

    def get_history(self) -> list[ToolCall]:
        return list(self._history)

    def get_active_entities(self) -> dict[str, Any]:
        return dict(self._active_entities)

    def get_filters_for(self, tool: str) -> dict[str, Any]:
        """Return the accumulated filters used with a specific tool."""
        return dict(self._filters_by_tool.get(tool, {}))

    @property
    def last_tool(self) -> str | None:
        return self._history[-1].tool if self._history else None

    @property
    def query_count(self) -> int:
        return self._query_count

    def context_summary(self) -> str:
        """
        One-paragraph plain-text summary of session state, suitable for
        injection into an LLM system prompt as conversation context.
        """
        if not self._history:
            return "No tool calls have been made yet this session."

        lines = [f"Session tool calls so far: {self._query_count}"]

        recent = list(self._history)[-3:]
        lines.append("Recent calls:")
        for call in recent:
            lines.append(f"  • {call.short_repr()}")

        if self._active_entities:
            lines.append(f"Current research focus: {_fmt_params(self._active_entities)}")

        return "\n".join(lines)

    # ── Reset ─────────────────────────────────────────────────────────────────

    def clear(self) -> None:
        self._history.clear()
        self._filters_by_tool.clear()
        self._active_entities.clear()
        self._query_count = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_params(params: dict[str, Any]) -> str:
    parts = [
        f"{k}={v!r}"
        for k, v in params.items()
        if v is not None and v != "" and v != []
    ]
    return ", ".join(parts) if parts else "(none)"
