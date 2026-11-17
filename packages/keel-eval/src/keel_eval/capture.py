"""Turn a failing trace into an attack case, so a production miss becomes a regression test."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from keel_core.ports import TraceEvent


def trace_to_case(events: Iterable[TraceEvent]) -> dict[str, Any] | None:
    """Return an attack case for the request in a trace, or ``None`` if it has no query.

    The query is only recorded when ``observability.log_prompts`` is true, so without it
    there is nothing to replay.
    """
    for event in events:
        if event.step != "request":
            continue
        query = event.attributes.get("query")
        if not isinstance(query, str) or not query:
            return None
        case: dict[str, Any] = {"input": query, "expect": "refuse"}
        roles = event.attributes.get("roles")
        if isinstance(roles, str) and roles:
            case["roles"] = sorted(roles.split(","))
        return case
    return None
