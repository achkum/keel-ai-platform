from __future__ import annotations

from pathlib import Path

import pytest

from keel_core.errors import KeelError
from keel_local.prompts import FilePromptRegistry, check_no_secrets


def test_render_substitutes_only_known_placeholders(tmp_path: Path) -> None:
    (tmp_path / "p.md").write_text("Hi {name}, {unknown} {0} {name.__class__}", encoding="utf-8")
    text, version = FilePromptRegistry(tmp_path).render("p.md", {"name": "Ann"})
    assert text == "Hi Ann, {unknown} {0} {name.__class__}"
    assert version.startswith("sha256:")
    assert len(version) == len("sha256:") + 12


def test_version_changes_with_template_and_variables(tmp_path: Path) -> None:
    reg = FilePromptRegistry(tmp_path)
    (tmp_path / "p.md").write_text("one {a}", encoding="utf-8")
    v1 = reg.render("p.md", {"a": "1"})[1]
    assert reg.render("p.md", {"a": "1"})[1] == v1
    assert reg.render("p.md", {"a": "2"})[1] != v1
    (tmp_path / "p.md").write_text("two {a}", encoding="utf-8")
    assert reg.render("p.md", {"a": "1"})[1] != v1


def test_path_traversal_rejected(tmp_path: Path) -> None:
    inner = tmp_path / "app"
    inner.mkdir()
    (tmp_path / "secret.md").write_text("x", encoding="utf-8")
    reg = FilePromptRegistry(inner)
    with pytest.raises(KeelError, match="outside"):
        reg.render("../secret.md", {})
    with pytest.raises(KeelError, match="outside"):
        reg.render(str(tmp_path / "secret.md"), {})


def test_missing_and_unreadable_template(tmp_path: Path) -> None:
    reg = FilePromptRegistry(tmp_path)
    with pytest.raises(KeelError, match="not found"):
        reg.render("nope.md", {})
    (tmp_path / "bin.md").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(KeelError, match="cannot read"):
        reg.render("bin.md", {})


@pytest.mark.parametrize(
    "text",
    [
        "key sk-abcdefghijklmnopqrstuvwx",
        "AKIAABCDEFGHIJKLMNOP",
        "-----BEGIN RSA PRIVATE KEY-----",
        "ghp_" + "a" * 30,
    ],
)
def test_secrets_detected(text: str) -> None:
    with pytest.raises(KeelError, match="secret"):
        check_no_secrets(text)


def test_clean_prompt_passes() -> None:
    check_no_secrets("You are a helpful assistant. Use sk as an abbreviation.")
