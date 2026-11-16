from __future__ import annotations

from typing import Any

from keel_core.spec import ChangeKind, KeelSpec, diff_specs


def _spec(data: dict[str, Any]) -> KeelSpec:
    return KeelSpec.model_validate(data)


def test_identical_specs_have_no_changes(minimal: dict[str, Any]) -> None:
    assert diff_specs(_spec(minimal), _spec(minimal)) == []


def test_changed_value_is_reported(minimal: dict[str, Any]) -> None:
    old = _spec(minimal)
    minimal["model"]["name"] = "gpt-4o"

    changes = diff_specs(old, _spec(minimal))

    assert len(changes) == 1
    assert changes[0].path == "model.name"
    assert changes[0].kind is ChangeKind.CHANGED
    assert str(changes[0]) == "~ model.name: 'gpt-4o-mini' -> 'gpt-4o'"


def test_added_and_removed_blocks_are_reported(minimal: dict[str, Any]) -> None:
    without_rag = _spec(minimal)
    minimal["rag"] = {"sources": [{"name": "docs", "uri": "file://docs"}]}
    with_rag = _spec(minimal)

    added = diff_specs(without_rag, with_rag)
    removed = diff_specs(with_rag, without_rag)

    # rag is optional, so it appears as a change from None rather than a new key.
    assert [c.path for c in added] == ["rag"]
    assert added[0].old is None
    assert removed[0].new is None


def test_changes_are_sorted_by_path(minimal: dict[str, Any]) -> None:
    old = _spec(minimal)
    minimal["model"]["timeout_s"] = 5
    minimal["app"]["version"] = "0.2.0"

    paths = [c.path for c in diff_specs(old, _spec(minimal))]

    assert paths == sorted(paths)


def test_mapping_keys_added_and_removed(minimal: dict[str, Any]) -> None:
    minimal["system_prompt"]["variables"] = {"company": "Acme"}
    old = _spec(minimal)
    minimal["system_prompt"]["variables"] = {"team": "Search"}

    changes = {str(c) for c in diff_specs(old, _spec(minimal))}

    assert changes == {
        "- system_prompt.variables.company: 'Acme'",
        "+ system_prompt.variables.team: 'Search'",
    }
