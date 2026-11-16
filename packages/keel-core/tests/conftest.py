from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_SPEC = REPO_ROOT / "examples" / "knowledge-assistant" / "keel.yaml"

_MINIMAL: dict[str, Any] = {
    "keel": "keel/v0",
    "app": {"name": "demo", "version": "0.1.0"},
    "model": {"provider": "openai", "name": "gpt-4o-mini"},
    "system_prompt": {"template": "prompts/system.md"},
}


@pytest.fixture
def example_spec() -> Path:
    return EXAMPLE_SPEC


@pytest.fixture
def minimal() -> dict[str, Any]:
    """A fresh copy of the smallest valid spec, safe to mutate in a test."""
    return copy.deepcopy(_MINIMAL)
