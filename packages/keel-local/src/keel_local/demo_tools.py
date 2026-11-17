"""Demo tools used by the example apps. They return fixed strings and touch nothing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from keel_core.ports import Principal


def lookup_ticket(arguments: Mapping[str, Any], principal: Principal) -> str:
    """Look up the status of a support ticket by id."""
    ref = str(arguments.get("query", "")).strip() or "unknown"
    return f"Ticket for '{ref}': status open, priority normal, requested by {principal.user_id}."


def issue_refund(arguments: Mapping[str, Any], principal: Principal) -> str:
    """Issue a refund for an order. Needs human approval."""
    ref = str(arguments.get("query", "")).strip() or "unknown"
    return f"Refund issued for '{ref}' on behalf of {principal.user_id}."
