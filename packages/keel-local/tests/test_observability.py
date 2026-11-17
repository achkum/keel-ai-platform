from __future__ import annotations

import io
import json
import threading
from pathlib import Path

from keel_core.ports import TraceEvent
from keel_local.observability import (
    GENESIS,
    ConsoleTracer,
    HashChainAuditLog,
    JsonlTracer,
    MultiTracer,
    NullTracer,
)


def _event(i: int = 0) -> TraceEvent:
    return TraceEvent("t1", "request", {"n": i, "ok": True}, 1.5)


def test_jsonl_tracer_appends_one_object_per_line(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "traces.jsonl"
    tracer = JsonlTracer(path)
    threads = [threading.Thread(target=tracer.record, args=(_event(i),)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 20
    assert {r["attributes"]["n"] for r in rows} == set(range(20))
    assert rows[0]["step"] == "request"


def test_console_and_null_and_multi(tmp_path: Path) -> None:
    buf = io.StringIO()
    path = tmp_path / "t.jsonl"
    MultiTracer(ConsoleTracer(buf), NullTracer(), JsonlTracer(path)).record(_event())
    assert json.loads(buf.getvalue())["trace_id"] == "t1"
    assert path.exists()


def test_console_tracer_defaults_to_stderr(capsys) -> None:  # type: ignore[no-untyped-def]
    ConsoleTracer().record(_event())
    assert "request" in capsys.readouterr().err


def test_audit_chain_verifies(tmp_path: Path) -> None:
    log = HashChainAuditLog(tmp_path / "state" / "audit.jsonl")
    assert log.verify()  # missing file is an empty, valid chain
    h1 = log.append({"status": "ok", "n": 1})
    h2 = log.append({"status": "blocked", "n": 2})
    rows = [
        json.loads(x)
        for x in (tmp_path / "state" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["prev"] == GENESIS
    assert rows[1]["prev"] == h1 == rows[0]["hash"]
    assert rows[1]["hash"] == h2
    assert log.verify()
    # a new instance continues the same chain
    h3 = HashChainAuditLog(tmp_path / "state" / "audit.jsonl").append({"n": 3})
    assert h3 != h2
    assert log.verify()


def _log_with_three(tmp_path: Path) -> tuple[HashChainAuditLog, Path]:
    path = tmp_path / "audit.jsonl"
    log = HashChainAuditLog(path)
    for i in range(3):
        log.append({"status": "ok", "n": i})
    return log, path


def test_audit_detects_edit(tmp_path: Path) -> None:
    log, path = _log_with_three(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace('"n": 1', '"n": 9'), encoding="utf-8")
    assert not log.verify()


def test_audit_detects_removed_and_reordered_lines(tmp_path: Path) -> None:
    log, path = _log_with_three(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert not log.verify()
    path.write_text("\n".join([lines[1], lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert not log.verify()


def test_audit_detects_garbage(tmp_path: Path) -> None:
    log, path = _log_with_three(tmp_path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("not json\n")
    assert not log.verify()
    path.write_text('{"entry": {}}\n\n', encoding="utf-8")
    assert not log.verify()
