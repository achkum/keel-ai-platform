"""Exceptions raised by keel-core."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class KeelError(Exception):
    """Base class for all Keel errors."""


@dataclass(frozen=True, slots=True)
class SpecIssue:
    """One problem found in a spec, located by a dotted path such as ``model.timeout_s``."""

    location: str
    message: str

    def __str__(self) -> str:
        return f"{self.location}: {self.message}" if self.location else self.message


class SpecError(KeelError):
    """A spec could not be read or did not validate."""

    def __init__(self, source: Path | str, issues: list[SpecIssue]) -> None:
        self.source = str(source)
        self.issues = tuple(issues)
        lines = "\n".join(f"  - {issue}" for issue in self.issues)
        super().__init__(f"invalid spec {self.source}:\n{lines}")
