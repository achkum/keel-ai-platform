"""Render a gate report as JSON-safe data and as markdown."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from keel_eval.types import GateReport, SuiteResult


def _num(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 4)


def report_to_dict(report: GateReport) -> dict[str, Any]:
    return {
        "app": report.app,
        "version": report.version,
        "spec_hash": report.spec_hash,
        "passed": report.passed,
        "started_at": report.started_at,
        "duration_s": round(report.duration_s, 3),
        "suites": [
            {
                "name": s.name,
                "kind": s.kind,
                "passed": s.passed,
                "score": _num(s.score),
                "threshold": _num(s.threshold),
                "detail": s.detail,
                "cases": [
                    {
                        "index": c.index,
                        "passed": c.passed,
                        "score": round(c.score, 4),
                        "detail": c.detail,
                        "trace_id": c.trace_id,
                    }
                    for c in s.cases
                ],
            }
            for s in report.suites
        ],
    }


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _row(s: SuiteResult) -> str:
    result = "pass" if s.passed else "FAIL"
    return f"| {_cell(s.name)} | {s.kind} | {_num(s.score)} | {_num(s.threshold)} | {result} |"


def report_to_markdown(report: GateReport) -> str:
    verdict = "PASSED" if report.passed else "FAILED"
    lines = [
        f"# Gate report: {report.app} {report.version}",
        "",
        f"- Result: **{verdict}**",
        f"- Spec hash: `{report.spec_hash}`",
        f"- Started: {report.started_at}",
        f"- Duration: {report.duration_s:.2f}s",
        "",
        "| Suite | Kind | Score | Threshold | Result |",
        "| --- | --- | --- | --- | --- |",
        *(_row(s) for s in report.suites),
    ]
    failing = [(s, c) for s in report.suites for c in s.cases if not c.passed]
    if failing:
        lines += ["", "## Failing cases", ""]
        for s, c in failing:
            trace = f" (trace `{c.trace_id}`)" if c.trace_id else ""
            lines.append(f"- {_cell(s.name)} #{c.index}: {_cell(c.detail)}{trace}")
    for s in report.suites:
        if s.detail and not s.passed:
            lines += ["", f"Note on {_cell(s.name)}: {_cell(s.detail)}"]
    return "\n".join(lines) + "\n"
