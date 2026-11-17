from __future__ import annotations

import pytest

from keel_core.ports import Principal
from keel_core.spec.models import AccessLayer, Role
from keel_local.policy import RbacPolicy

ACCESS = AccessLayer(
    default="deny",
    roles=(Role(name="employee", sources=("handbook",), tools=("lookup",)), Role(name="empty")),
)


def _p(*roles: str) -> Principal:
    return Principal("u", frozenset(roles))


def test_default_deny_requires_declared_role() -> None:
    policy = RbacPolicy(ACCESS)
    assert not policy.check(_p(), "ask", "app:x").allowed
    assert not policy.check(_p("stranger"), "ask", "app:x").allowed
    assert policy.check(_p("employee"), "ask", "app:x").allowed
    assert policy.check(_p("empty"), "ask", "app:x").allowed


def test_role_grants_sources_and_tools() -> None:
    policy = RbacPolicy(ACCESS)
    emp = _p("employee")
    assert policy.check(emp, "retrieve", "source:handbook").allowed
    assert not policy.check(emp, "retrieve", "source:finance").allowed
    assert policy.check(emp, "call", "tool:lookup").allowed
    assert not policy.check(emp, "call", "tool:refund").allowed
    assert not policy.check(_p("empty"), "retrieve", "source:handbook").allowed
    assert not policy.check(_p(), "call", "tool:lookup").allowed


def test_combined_roles_union() -> None:
    policy = RbacPolicy(ACCESS)
    assert policy.check(_p("empty", "employee"), "retrieve", "source:handbook").allowed


@pytest.mark.parametrize("resource", ["tool:lookup", "handbook", "source:"])
def test_mismatched_resource_denied(resource: str) -> None:
    assert not RbacPolicy(ACCESS).check(_p("employee"), "retrieve", resource).allowed


def test_default_allow_and_unknown_action() -> None:
    policy = RbacPolicy(AccessLayer(default="allow"))
    assert policy.check(_p(), "call", "tool:anything").allowed
    assert not policy.check(_p("employee"), "delete", "app:x").allowed
    assert not RbacPolicy(ACCESS).check(_p("employee"), "write", "app:x").allowed
