"""Promotion, release listing and rollback. State lives in ``<state>/releases`` and ``reports``."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from keel_eval.gate import run_gate
from keel_eval.types import GateError, GateReport, PromotionResult, Release
from keel_local import build_runtime, state_dir_for

_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]*$")


def _write(path: Path, text: str) -> None:
    """Write via a temp file so a crash never leaves a half-written release."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _check_version(version: str) -> None:
    if not _VERSION.fullmatch(version) or ".." in version:
        raise GateError(f"invalid version '{version}'")


def _current(state_dir: Path) -> str:
    try:
        return (state_dir / "releases" / "CURRENT").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _read_release(path: Path, current: str) -> Release:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Release(
            app=str(data["app"]),
            version=str(data["version"]),
            spec_hash=str(data["spec_hash"]),
            promoted_at=str(data["promoted_at"]),
            report_path=Path(str(data["report_path"])),
            current=str(data["version"]) == current,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise GateError(f"unreadable release file {path.name}: {exc}") from None


def list_releases(state_dir: Path) -> list[Release]:
    releases_dir = state_dir / "releases"
    if not releases_dir.is_dir():
        return []
    current = _current(state_dir)
    found = [_read_release(p, current) for p in releases_dir.glob("*.json")]
    return sorted(found, key=lambda r: (r.promoted_at, r.version))


def rollback(state_dir: Path, version: str) -> Release:
    """Make an earlier, already promoted version current again."""
    _check_version(version)
    path = state_dir / "releases" / f"{version}.json"
    if not path.is_file():
        known = ", ".join(r.version for r in list_releases(state_dir)) or "none"
        raise GateError(f"version {version} was never promoted (promoted versions: {known})")
    _write(state_dir / "releases" / "CURRENT", version)
    return _read_release(path, version)


def _write_reports(state_dir: Path, report: GateReport) -> Path:
    stem = f"{report.app}-{report.version}-{report.spec_hash[:12]}"
    reports = state_dir / "reports"
    json_path = reports / f"{stem}.json"
    _write(json_path, json.dumps(report.to_dict(), indent=2) + "\n")
    _write(reports / f"{stem}.md", report.to_markdown())
    return json_path


def promote(
    spec_path: Path,
    *,
    offline: bool = False,
    load_duration_s: float = 3.0,
    state_dir: Path | None = None,
) -> PromotionResult:
    """Run the full gate. Only if every suite passes, pin this spec version as a release."""
    spec_path = Path(spec_path)
    state = state_dir if state_dir is not None else state_dir_for(spec_path)
    runtime = build_runtime(spec_path, offline=offline, state_dir=state)
    report = asyncio.run(
        run_gate(runtime, spec_path.resolve().parent, load_duration_s=load_duration_s)
    )
    report_path = _write_reports(state, report)
    extra = {"report_path": str(report_path)}
    if not report.passed:
        failed = [s.name for s in report.suites if not s.passed]
        return PromotionResult(False, report, f"gate failed: {', '.join(failed)}", extra=extra)

    _check_version(report.version)
    existing = state / "releases" / f"{report.version}.json"
    if existing.is_file():
        release = _read_release(existing, _current(state))
        if release.spec_hash != report.spec_hash:
            message = (
                f"version {report.version} was already promoted with a different spec; "
                "bump app.version in keel.yaml to promote this change"
            )
            return PromotionResult(False, report, message, extra=extra)
        return PromotionResult(
            True, report, f"version {report.version} is already promoted", release, extra
        )

    promoted_at = datetime.now(UTC).isoformat(timespec="seconds")
    record = {
        "app": report.app,
        "version": report.version,
        "spec_hash": report.spec_hash,
        "promoted_at": promoted_at,
        "report_path": str(report_path),
    }
    _write(existing, json.dumps(record, indent=2) + "\n")
    _write(state / "releases" / "CURRENT", report.version)
    release = _read_release(existing, report.version)
    return PromotionResult(True, report, f"promoted {report.app} {report.version}", release, extra)
