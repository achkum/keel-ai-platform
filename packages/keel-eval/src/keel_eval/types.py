"""Result types and the gate error. Re-exported from ``keel_eval``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SuiteKind = Literal["quality", "attack", "load"]


class GateError(Exception):
    """A gate could not run at all (for example a dataset file is missing or malformed)."""


@dataclass(frozen=True, slots=True)
class CaseResult:
    index: int
    passed: bool
    score: float
    detail: str = ""
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class SuiteResult:
    name: str
    kind: SuiteKind
    passed: bool
    score: float
    """quality: mean case score; attack: number of failed cases; load: observed p95 ms."""
    threshold: float
    """quality: min_score; attack: max_failures; load: max_p95_latency_ms."""
    cases: tuple[CaseResult, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class GateReport:
    app: str
    version: str
    spec_hash: str
    passed: bool
    suites: tuple[SuiteResult, ...] = ()
    started_at: str = ""
    """ISO 8601 UTC."""
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        from keel_eval.report import report_to_dict

        return report_to_dict(self)

    def to_markdown(self) -> str:
        from keel_eval.report import report_to_markdown

        return report_to_markdown(self)


@dataclass(frozen=True, slots=True)
class Release:
    app: str
    version: str
    spec_hash: str
    promoted_at: str
    report_path: Path
    current: bool = False


@dataclass(frozen=True, slots=True)
class PromotionResult:
    promoted: bool
    report: GateReport
    message: str
    release: Release | None = None
    extra: dict[str, Any] = field(default_factory=dict)
