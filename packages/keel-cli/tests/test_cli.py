from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from keel_cli.main import EXIT_INVALID_SPEC, app
from keel_core import load_spec

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.startswith("keel ")


def test_init_creates_a_valid_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path)])

    assert result.exit_code == 0, result.output
    spec = load_spec(tmp_path / "keel.yaml")
    assert spec.profile == "strict"
    assert (tmp_path / "prompts" / "system.md").is_file()
    assert (tmp_path / "evals" / "quality.jsonl").is_file()
    assert (tmp_path / "evals" / "attack.jsonl").is_file()
    assert (tmp_path / "docs" / "handbook.md").is_file()
    assert spec.model.provider == "keel"


def test_init_refuses_to_overwrite(tmp_path: Path) -> None:
    (tmp_path / "keel.yaml").write_text("keep me", encoding="utf-8")

    result = runner.invoke(app, ["init", str(tmp_path)])

    assert result.exit_code == 1
    assert (tmp_path / "keel.yaml").read_text(encoding="utf-8") == "keep me"


def test_init_force_overwrites_spec_but_keeps_prompt(tmp_path: Path) -> None:
    (tmp_path / "keel.yaml").write_text("old", encoding="utf-8")
    prompt = tmp_path / "prompts" / "system.md"
    prompt.parent.mkdir()
    prompt.write_text("my prompt", encoding="utf-8")

    result = runner.invoke(app, ["init", str(tmp_path), "--force"])

    assert result.exit_code == 0
    load_spec(tmp_path / "keel.yaml")
    assert prompt.read_text(encoding="utf-8") == "my prompt"


@pytest.fixture
def two_specs(tmp_path: Path) -> tuple[Path, Path]:
    runner.invoke(app, ["init", str(tmp_path / "a")])
    runner.invoke(app, ["init", str(tmp_path / "b")])
    return tmp_path / "a" / "keel.yaml", tmp_path / "b" / "keel.yaml"


def test_diff_identical_specs(two_specs: tuple[Path, Path]) -> None:
    result = runner.invoke(app, ["diff", *map(str, two_specs), "--exit-code"])

    assert result.exit_code == 0
    assert "No changes." in result.output


def test_diff_reports_changes(two_specs: tuple[Path, Path]) -> None:
    old, new = two_specs
    new.write_text(
        new.read_text(encoding="utf-8").replace("  name: extractive", "  name: extractive-v2"),
        encoding="utf-8",
    )

    plain = runner.invoke(app, ["diff", str(old), str(new)])
    strict = runner.invoke(app, ["diff", str(old), str(new), "--exit-code"])

    assert plain.exit_code == 0
    assert "~ model.name: 'extractive' -> 'extractive-v2'" in plain.output
    assert strict.exit_code == 1


def test_diff_invalid_spec(tmp_path: Path, two_specs: tuple[Path, Path]) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("keel: keel/v0\n", encoding="utf-8")

    result = runner.invoke(app, ["diff", str(two_specs[0]), str(bad)])

    assert result.exit_code == EXIT_INVALID_SPEC
    assert "invalid spec" in result.output
