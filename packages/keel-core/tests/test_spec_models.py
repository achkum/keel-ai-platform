from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from keel_core.spec.models import KeelSpec


def _validate(data: dict[str, Any]) -> KeelSpec:
    return KeelSpec.model_validate(data)


def test_minimal_spec_gets_secure_defaults(minimal: dict[str, Any]) -> None:
    spec = _validate(minimal)

    assert spec.profile == "strict"
    assert spec.access.default == "deny"
    assert "prompt_injection" in spec.guardrails.input
    assert spec.observability.log_prompts is False


def test_spec_is_immutable(minimal: dict[str, Any]) -> None:
    spec = _validate(minimal)
    with pytest.raises(ValidationError):
        spec.app.name = "changed"  # type: ignore[misc]


def test_unknown_keys_are_rejected(minimal: dict[str, Any]) -> None:
    minimal["model"]["temprature"] = 0.2
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _validate(minimal)


def test_wrong_spec_version_is_rejected(minimal: dict[str, Any]) -> None:
    minimal["keel"] = "keel/v9"
    with pytest.raises(ValidationError):
        _validate(minimal)


@pytest.mark.parametrize("name", ["Demo", "1demo", "demo_app", "", "a" * 64])
def test_app_name_must_be_a_slug(minimal: dict[str, Any], name: str) -> None:
    minimal["app"]["name"] = name
    with pytest.raises(ValidationError):
        _validate(minimal)


def test_fallback_cannot_repeat_primary(minimal: dict[str, Any]) -> None:
    minimal["model"]["fallbacks"] = [{"provider": "openai", "name": "gpt-4o-mini"}]
    with pytest.raises(ValidationError, match="repeats an earlier model"):
        _validate(minimal)


def test_role_must_reference_declared_tools(minimal: dict[str, Any]) -> None:
    minimal["access"] = {"roles": [{"name": "user", "tools": ["refund"]}]}
    with pytest.raises(ValidationError, match="undeclared tools"):
        _validate(minimal)


def test_role_must_reference_declared_sources(minimal: dict[str, Any]) -> None:
    minimal["access"] = {"roles": [{"name": "user", "sources": ["hr"]}]}
    with pytest.raises(ValidationError, match="undeclared rag sources"):
        _validate(minimal)


def test_duplicate_tool_names_are_rejected(minimal: dict[str, Any]) -> None:
    tool = {"name": "lookup", "mcp_server": "mcp://x"}
    minimal["tools"] = [tool, tool]
    minimal["evals"] = {"attack": [{"name": "inj", "dataset": "a.jsonl"}]}
    with pytest.raises(ValidationError, match="duplicate tool name"):
        _validate(minimal)


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        ({"access": {"default": "allow"}}, "access.default must be 'deny'"),
        ({"guardrails": {"input": ["pii"]}}, "must include 'prompt_injection'"),
        ({"observability": {"log_prompts": True}}, "log_prompts must be false"),
        (
            {"tools": [{"name": "lookup", "mcp_server": "mcp://x"}]},
            "at least one attack suite",
        ),
    ],
)
def test_strict_profile_blocks_insecure_settings(
    minimal: dict[str, Any], patch: dict[str, Any], expected: str
) -> None:
    minimal.update(patch)
    with pytest.raises(ValidationError, match=expected):
        _validate(minimal)


def test_standard_profile_allows_relaxed_settings(minimal: dict[str, Any]) -> None:
    minimal["profile"] = "standard"
    minimal["access"] = {"default": "allow"}
    minimal["guardrails"] = {"input": []}

    spec = _validate(minimal)

    assert spec.access.default == "allow"
