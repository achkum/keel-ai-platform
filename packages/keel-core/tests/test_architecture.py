"""Dependency direction between packages, enforced by scanning imports."""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[2]
CORE_ALLOWED = {"pydantic", "yaml", "keel_core"}


def _imports(path: Path) -> Iterator[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0]


def _tops(package_dir: str) -> dict[Path, set[str]]:
    root = PACKAGES / package_dir / "src"
    return {p: set(_imports(p)) for p in root.rglob("*.py")}


def test_core_imports_only_stdlib_pydantic_yaml() -> None:
    allowed = CORE_ALLOWED | set(sys.stdlib_module_names)
    files = _tops("keel-core")
    assert files
    for path, tops in files.items():
        assert tops <= allowed, f"{path} imports {sorted(tops - allowed)}"


def test_local_never_imports_eval_or_cli() -> None:
    for path, tops in _tops("keel-local").items():
        assert not tops & {"keel_eval", "keel_cli"}, path


def test_eval_never_imports_cli() -> None:
    for path, tops in _tops("keel-eval").items():
        assert "keel_cli" not in tops, path
