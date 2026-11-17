from __future__ import annotations

import json
from typing import Any

from keel_core import KeelSpec, parse_spec, spec_hash
from keel_core.spec import spec_hash as spec_hash_from_package


def _spec(raw: dict[str, Any]) -> KeelSpec:
    return parse_spec(json.dumps(raw))


def test_hash_is_stable_hex_and_exported(minimal: dict[str, Any]) -> None:
    digest = spec_hash(_spec(minimal))

    assert len(digest) == 64
    assert int(digest, 16) >= 0
    assert digest == spec_hash(_spec(minimal))
    assert spec_hash_from_package is spec_hash


def test_hash_ignores_key_order(minimal: dict[str, Any]) -> None:
    reordered = dict(reversed(list(minimal.items())))

    assert spec_hash(_spec(minimal)) == spec_hash(_spec(reordered))


def test_hash_changes_with_content(minimal: dict[str, Any]) -> None:
    other = {**minimal, "model": {"provider": "openai", "name": "gpt-4o"}}

    assert spec_hash(_spec(minimal)) != spec_hash(_spec(other))
