"""Load and validate eval datasets (JSONL, one object per line, blank lines ignored)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from keel_eval.types import GateError

MAX_DATASET_BYTES = 10 * 1024 * 1024
Expect = Literal["refuse", "deny", "no_leak", "no_tool"]
_EXPECTS = ("refuse", "deny", "no_leak", "no_tool")


@dataclass(frozen=True, slots=True)
class QualityCase:
    question: str
    roles: frozenset[str] | None = None
    expected_sources: tuple[str, ...] = ()
    must_include: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AttackCase:
    input: str
    expect: Expect
    roles: frozenset[str] | None = None
    tool: str | None = None
    forbidden: tuple[str, ...] = ()


def resolve_in(spec_dir: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``spec_dir`` and refuse anything that escapes it."""
    base = spec_dir.resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise GateError(f"path '{relative}' is outside the spec directory")
    return target


def _fail(path: Path, line_no: int, message: str) -> GateError:
    return GateError(f"{path.name}:{line_no}: {message}")


def _read_objects(path: Path) -> list[tuple[int, dict[str, Any]]]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise GateError(f"cannot read dataset {path.name}: {exc.strerror or exc}") from None
    if size > MAX_DATASET_BYTES:
        raise GateError(f"dataset {path.name} is larger than {MAX_DATASET_BYTES} bytes")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise GateError(f"cannot read dataset {path.name}: {exc}") from None
    rows: list[tuple[int, dict[str, Any]]] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _fail(path, line_no, f"invalid JSON ({exc.msg})") from None
        if not isinstance(obj, dict):
            raise _fail(path, line_no, "each line must be a JSON object")
        rows.append((line_no, cast("dict[str, Any]", obj)))
    if not rows:
        raise GateError(f"dataset {path.name} has no cases")
    return rows


def _text(obj: dict[str, Any], key: str, path: Path, line_no: int) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _fail(path, line_no, f"'{key}' must be a non-empty string")
    return value


def _str_list(obj: dict[str, Any], key: str, path: Path, line_no: int) -> tuple[str, ...]:
    value = obj.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _fail(path, line_no, f"'{key}' must be a list of strings")
    return tuple(value)


def _roles(obj: dict[str, Any], path: Path, line_no: int) -> frozenset[str] | None:
    roles: set[str] = set()
    found = False
    if "role" in obj:
        found = True
        roles.add(_text(obj, "role", path, line_no))
    if "roles" in obj:
        found = True
        roles.update(_str_list(obj, "roles", path, line_no))
    return frozenset(roles) if found else None


def _check_keys(obj: dict[str, Any], allowed: set[str], path: Path, line_no: int) -> None:
    if unknown := sorted(set(obj) - allowed):
        raise _fail(path, line_no, f"unknown keys: {unknown}")


def load_quality(path: Path) -> list[QualityCase]:
    allowed = {"question", "role", "roles", "expected_sources", "must_include"}
    cases: list[QualityCase] = []
    for line_no, obj in _read_objects(path):
        _check_keys(obj, allowed, path, line_no)
        cases.append(
            QualityCase(
                question=_text(obj, "question", path, line_no),
                roles=_roles(obj, path, line_no),
                expected_sources=_str_list(obj, "expected_sources", path, line_no),
                must_include=_str_list(obj, "must_include", path, line_no),
            )
        )
    return cases


def load_attack(path: Path) -> list[AttackCase]:
    allowed = {"input", "role", "roles", "expect", "tool", "forbidden"}
    cases: list[AttackCase] = []
    for line_no, obj in _read_objects(path):
        _check_keys(obj, allowed, path, line_no)
        expect = obj.get("expect")
        if expect not in _EXPECTS:
            raise _fail(path, line_no, f"'expect' must be one of {list(_EXPECTS)}")
        tool = obj.get("tool")
        if tool is not None and not isinstance(tool, str):
            raise _fail(path, line_no, "'tool' must be a string")
        cases.append(
            AttackCase(
                input=_text(obj, "input", path, line_no),
                expect=cast("Expect", expect),
                roles=_roles(obj, path, line_no),
                tool=tool,
                forbidden=_str_list(obj, "forbidden", path, line_no),
            )
        )
    return cases
