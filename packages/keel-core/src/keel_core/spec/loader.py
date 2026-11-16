"""Read ``keel.yaml`` from disk or text and turn it into a validated :class:`KeelSpec`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from keel_core.errors import SpecError, SpecIssue
from keel_core.spec.models import KeelSpec

MAX_SPEC_BYTES = 1_000_000
"""Upper bound on spec size. A spec is configuration; anything larger is a mistake or an attack."""


def load_spec(path: Path | str) -> KeelSpec:
    """Load and validate a spec file.

    Raises:
        SpecError: if the file is missing, too large, not valid YAML, or fails validation.
    """
    path = Path(path)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        raise SpecError(path, [SpecIssue("", "file not found")]) from None
    if size > MAX_SPEC_BYTES:
        raise SpecError(path, [SpecIssue("", f"file is larger than {MAX_SPEC_BYTES} bytes")])
    return parse_spec(path.read_text(encoding="utf-8"), source=path)


def parse_spec(text: str, *, source: Path | str = "<string>") -> KeelSpec:
    """Validate spec text. ``source`` is only used in error messages."""
    data = _parse_yaml(text, source)
    try:
        return KeelSpec.model_validate(data)
    except ValidationError as exc:
        raise SpecError(source, [_to_issue(err) for err in exc.errors()]) from None


def _parse_yaml(text: str, source: Path | str) -> dict[str, Any]:
    try:
        # safe_load never constructs arbitrary Python objects.
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise SpecError(source, [SpecIssue(where, f"not valid YAML: {exc}")]) from None
    if not isinstance(data, dict):
        raise SpecError(source, [SpecIssue("", "top level must be a mapping")])
    return data


def _to_issue(err: Any) -> SpecIssue:
    location = ".".join(str(part) for part in err.get("loc", ()))
    message = str(err.get("msg", "invalid value"))
    message = message.removeprefix("Value error, ")
    return SpecIssue(location, message)
