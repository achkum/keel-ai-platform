"""Role based access policy built from ``spec.access``."""

from __future__ import annotations

from keel_core.ports import Decision, Principal
from keel_core.spec.models import AccessLayer

_KNOWN_ACTIONS = {"ask": "app", "retrieve": "source", "call": "tool"}


class RbacPolicy:
    """Default deny: asking needs a declared role, other actions need a role that grants them.

    Default allow permits every known action. Unknown actions are always denied.
    """

    def __init__(self, access: AccessLayer) -> None:
        self._default_allow = access.default == "allow"
        self._roles = {r.name: r for r in access.roles}

    def check(self, principal: Principal, action: str, resource: str) -> Decision:
        kind = _KNOWN_ACTIONS.get(action)
        if kind is None:
            return Decision(False, f"unknown action '{action}'")
        if self._default_allow:
            return Decision(True, "access.default is allow")
        declared = [self._roles[r] for r in sorted(principal.roles) if r in self._roles]
        if not declared:
            return Decision(False, "no declared role")
        if action == "ask":
            return Decision(True, f"role {declared[0].name}")
        prefix, _, name = resource.partition(":")
        if prefix != kind or not name:
            return Decision(False, f"resource '{resource}' does not match action '{action}'")
        for role in declared:
            granted = role.sources if action == "retrieve" else role.tools
            if name in granted:
                return Decision(True, f"role {role.name} grants {resource}")
        return Decision(False, f"no role grants {resource}")
