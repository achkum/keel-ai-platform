from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from keel_eval import CaseResult, GateReport, SuiteResult, run_gate

if TYPE_CHECKING:
    from conftest import Kit


def test_gate_runs_all_suites_and_passes(kit: Kit, tmp_path: Path) -> None:
    path = kit.write_app(tmp_path)
    rt = kit.make_runtime(path)
    report = asyncio.run(run_gate(rt, tmp_path, load_duration_s=0.1))
    assert report.passed
    assert [(s.name, s.kind) for s in report.suites] == [
        ("faith", "quality"),
        ("inject", "attack"),
        ("load", "load"),
    ]
    assert (report.app, report.version, report.spec_hash) == ("demo", "0.1.0", rt.spec_hash)
    started = datetime.fromisoformat(report.started_at)
    assert started.utcoffset() is not None
    assert report.duration_s >= 0


def test_gate_fails_when_any_suite_fails(kit: Kit, tmp_path: Path) -> None:
    path = kit.write_app(tmp_path, attack=[{"input": "hello", "expect": "refuse"}])
    report = asyncio.run(run_gate(kit.make_runtime(path), tmp_path, include_load=False))
    assert not report.passed
    assert [s.passed for s in report.suites] == [True, False]


def test_gate_fails_on_quality_threshold(kit: Kit, tmp_path: Path) -> None:
    path = kit.write_app(tmp_path, quality=[{"question": "q", "must_include": ["zzz"]}])
    report = asyncio.run(run_gate(kit.make_runtime(path), tmp_path, include_load=False))
    assert not report.passed
    assert report.suites[0].score == 0.0


def test_gate_filters_suites_and_load(kit: Kit, tmp_path: Path) -> None:
    path = kit.write_app(tmp_path)
    rt = kit.make_runtime(path)
    only = asyncio.run(run_gate(rt, tmp_path, suites=frozenset({"inject"}), include_load=False))
    assert [s.name for s in only.suites] == ["inject"]
    none = asyncio.run(run_gate(rt, tmp_path, suites=frozenset({"nope"}), include_load=False))
    assert none.suites == ()


def _report() -> GateReport:
    cases = (
        CaseResult(0, True, 1.0, "ok", "t0"),
        CaseResult(1, False, 0.5, "answer lacks: ['a|b']", "t1"),
    )
    return GateReport(
        app="demo",
        version="1.2.3",
        spec_hash="abc",
        passed=False,
        suites=(
            SuiteResult("faith", "quality", False, 0.75, 0.9, cases),
            SuiteResult("load", "load", False, 250.5, 100.0, detail="20 requests, 2 errors"),
        ),
        started_at="2026-01-01T00:00:00+00:00",
        duration_s=1.23456,
    )


def test_to_dict_is_json_safe() -> None:
    data = _report().to_dict()
    assert json.loads(json.dumps(data)) == data
    assert data["suites"][0]["cases"][1]["trace_id"] == "t1"
    assert data["suites"][1]["score"] == 250.5
    assert data["duration_s"] == 1.235


def test_to_markdown() -> None:
    md = _report().to_markdown()
    assert "# Gate report: demo 1.2.3" in md
    assert "FAILED" in md
    assert "| Suite | Kind | Score | Threshold | Result |" in md
    assert "| faith | quality | 0.75 | 0.9 | FAIL |" in md
    assert "## Failing cases" in md
    assert "faith #1: answer lacks: ['a\\|b'] (trace `t1`)" in md
    assert "Note on load: 20 requests, 2 errors" in md


def test_to_markdown_all_passing_has_no_failing_section() -> None:
    report = GateReport("demo", "1.0.0", "h", True, (SuiteResult("s", "attack", True, 0, 0),))
    md = report.to_markdown()
    assert "PASSED" in md
    assert "| s | attack | 0 | 0 | pass |" in md
    assert "Failing cases" not in md
