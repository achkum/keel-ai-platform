from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from keel_core import load_spec
from keel_core.ports import TraceEvent
from keel_eval import GateError, list_releases, promote, release, rollback
from keel_eval.capture import trace_to_case

if TYPE_CHECKING:
    from conftest import Kit


@pytest.fixture
def patched(kit: Kit, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build(spec_path: Path, *, offline: bool = False, state_dir: Path | None = None) -> Any:
        return kit.make_runtime(spec_path)

    monkeypatch.setattr(release, "build_runtime", fake_build)


def test_promote_writes_reports_and_release(kit: Kit, tmp_path: Path, patched: None) -> None:
    spec = kit.write_app(tmp_path / "app")
    state = tmp_path / "state"
    result = promote(spec, load_duration_s=0.0, state_dir=state)
    assert result.promoted
    assert result.release is not None
    assert result.release.current
    assert result.release.version == "0.1.0"
    hash12 = result.report.spec_hash[:12]
    report_json = state / "reports" / f"demo-0.1.0-{hash12}.json"
    assert json.loads(report_json.read_text(encoding="utf-8"))["passed"] is True
    assert (state / "reports" / f"demo-0.1.0-{hash12}.md").is_file()
    assert (state / "releases" / "CURRENT").read_text(encoding="utf-8") == "0.1.0"
    record = json.loads((state / "releases" / "0.1.0.json").read_text(encoding="utf-8"))
    assert record["spec_hash"] == result.report.spec_hash
    assert record["report_path"] == str(report_json)
    assert result.extra["report_path"] == str(report_json)


def test_promote_defaults_state_dir_next_to_spec(kit: Kit, tmp_path: Path, patched: None) -> None:
    spec = kit.write_app(tmp_path / "app")
    assert promote(spec, load_duration_s=0.0).promoted
    assert (tmp_path / "app" / ".keel" / "releases" / "CURRENT").is_file()


def test_failed_gate_writes_report_but_no_release(kit: Kit, tmp_path: Path, patched: None) -> None:
    spec = kit.write_app(tmp_path / "app", attack=[{"input": "hello", "expect": "refuse"}])
    state = tmp_path / "state"
    result = promote(spec, load_duration_s=0.0, state_dir=state)
    assert not result.promoted
    assert result.release is None
    assert "inject" in result.message
    assert list((state / "reports").glob("*.json"))
    assert list((state / "reports").glob("*.md"))
    assert not (state / "releases").exists()
    assert list_releases(state) == []


def test_promote_is_idempotent_for_same_spec(kit: Kit, tmp_path: Path, patched: None) -> None:
    spec = kit.write_app(tmp_path / "app")
    state = tmp_path / "state"
    first = promote(spec, load_duration_s=0.0, state_dir=state)
    second = promote(spec, load_duration_s=0.0, state_dir=state)
    assert second.promoted
    assert "already promoted" in second.message
    assert second.release is not None
    assert first.release is not None
    assert second.release.promoted_at == first.release.promoted_at
    assert len(list_releases(state)) == 1


def test_same_version_different_spec_is_refused(kit: Kit, tmp_path: Path, patched: None) -> None:
    spec = kit.write_app(tmp_path / "app")
    state = tmp_path / "state"
    assert promote(spec, load_duration_s=0.0, state_dir=state).promoted
    kit.write_app(tmp_path / "app", note="changed")
    result = promote(spec, load_duration_s=0.0, state_dir=state)
    assert not result.promoted
    assert "bump app.version" in result.message
    assert len(list_releases(state)) == 1


def test_list_and_rollback(kit: Kit, tmp_path: Path, patched: None) -> None:
    app = tmp_path / "app"
    state = tmp_path / "state"
    assert list_releases(state) == []
    promote(kit.write_app(app, version="0.1.0"), load_duration_s=0.0, state_dir=state)
    promote(kit.write_app(app, version="0.2.0"), load_duration_s=0.0, state_dir=state)
    releases = list_releases(state)
    assert [r.version for r in releases] == ["0.1.0", "0.2.0"]
    assert [r.current for r in releases] == [False, True]

    back = rollback(state, "0.1.0")
    assert back.current
    assert back.version == "0.1.0"
    assert [r.current for r in list_releases(state)] == [True, False]


def test_rollback_unknown_or_unsafe_version(tmp_path: Path) -> None:
    state = tmp_path / "state"
    with pytest.raises(GateError, match="never promoted"):
        rollback(state, "9.9.9")
    for bad in ("../x", "a/b", "", "..", "1..2"):
        with pytest.raises(GateError, match="invalid version"):
            rollback(state, bad)


def test_unreadable_release_file(tmp_path: Path) -> None:
    releases = tmp_path / "releases"
    releases.mkdir()
    (releases / "0.1.0.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(GateError, match="unreadable release file"):
        list_releases(tmp_path)


def test_spec_fixture_loads(kit: Kit, tmp_path: Path) -> None:
    # guards the fixture itself: the generated spec must satisfy the strict profile
    assert load_spec(kit.write_app(tmp_path)).app.name == "demo"


# ---------------------------------------------------------------- capture


def _event(step: str, **attrs: Any) -> TraceEvent:
    return TraceEvent("t", step, attrs, 0.0)


def test_trace_to_case_with_query() -> None:
    events = [_event("request", user_id="u", roles="hr,employee", query="steal it")]
    assert trace_to_case(events) == {
        "input": "steal it",
        "expect": "refuse",
        "roles": ["employee", "hr"],
    }


def test_trace_to_case_without_query_or_request() -> None:
    assert trace_to_case([_event("request", user_id="u", roles="")]) is None
    assert trace_to_case([_event("response", status="ok")]) is None
    assert trace_to_case([]) is None
    assert trace_to_case([_event("request", query="q", roles="")]) == {
        "input": "q",
        "expect": "refuse",
    }
