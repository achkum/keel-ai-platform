from __future__ import annotations

from pathlib import Path

import pytest

from keel_core import SpecError, load_spec, parse_spec
from keel_core.spec import loader


def test_example_spec_is_valid(example_spec: Path) -> None:
    spec = load_spec(example_spec)

    assert spec.app.name == "knowledge-assistant"
    assert spec.rag is not None
    assert {s.name for s in spec.rag.sources} == {"handbook", "hr-policies"}


def test_missing_file_raises_spec_error(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="file not found"):
        load_spec(tmp_path / "nope.yaml")


def test_oversized_file_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader, "MAX_SPEC_BYTES", 10)
    path = tmp_path / "keel.yaml"
    path.write_text("keel: keel/v0\n" * 5, encoding="utf-8")

    with pytest.raises(SpecError, match="larger than"):
        load_spec(path)


def test_invalid_yaml_reports_line() -> None:
    with pytest.raises(SpecError) as info:
        parse_spec("app: [unclosed")

    assert info.value.issues[0].location.startswith("line ")


def test_top_level_must_be_a_mapping() -> None:
    with pytest.raises(SpecError, match="top level must be a mapping"):
        parse_spec("- just\n- a list\n")


def test_python_tags_are_never_executed() -> None:
    # yaml.safe_load refuses to build Python objects from tags.
    with pytest.raises(SpecError, match="not valid YAML"):
        parse_spec("keel: !!python/object/apply:os.system ['echo pwned']")


def test_validation_errors_carry_locations() -> None:
    text = "keel: keel/v0\napp: {name: demo, version: '1'}\n"

    with pytest.raises(SpecError) as info:
        parse_spec(text, source="keel.yaml")

    locations = {issue.location for issue in info.value.issues}
    assert "app.version" in locations
    assert "model" in locations
    assert "keel.yaml" in str(info.value)
