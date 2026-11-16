"""Structural diff between two spec versions.

This is the first step towards ``keel diff``. It reports which settings changed.
A later version will also report which eval results moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from keel_core.spec.models import KeelSpec


class ChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


@dataclass(frozen=True, slots=True)
class Change:
    path: str
    kind: ChangeKind
    old: Any = None
    new: Any = None

    def __str__(self) -> str:
        if self.kind is ChangeKind.ADDED:
            return f"+ {self.path}: {self.new!r}"
        if self.kind is ChangeKind.REMOVED:
            return f"- {self.path}: {self.old!r}"
        return f"~ {self.path}: {self.old!r} -> {self.new!r}"


def diff_specs(old: KeelSpec, new: KeelSpec) -> list[Change]:
    """Return every setting that differs between two specs, sorted by path."""
    changes: list[Change] = []
    _walk(
        old.model_dump(mode="json", by_alias=True),
        new.model_dump(mode="json", by_alias=True),
        "",
        changes,
    )
    return sorted(changes, key=lambda c: c.path)


def _walk(old: Any, new: Any, path: str, out: list[Change]) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        for key in old.keys() | new.keys():
            child = f"{path}.{key}" if path else str(key)
            if key not in new:
                out.append(Change(child, ChangeKind.REMOVED, old=old[key]))
            elif key not in old:
                out.append(Change(child, ChangeKind.ADDED, new=new[key]))
            else:
                _walk(old[key], new[key], child, out)
        return
    if old != new:
        out.append(Change(path, ChangeKind.CHANGED, old=old, new=new))
