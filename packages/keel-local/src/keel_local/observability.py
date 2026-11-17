"""Tracers and the tamper-evident audit log."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from keel_core.ports import AttrValue, TraceEvent, TracerPort

GENESIS = "0" * 64


def _event_json(event: TraceEvent) -> str:
    return json.dumps(
        {
            "trace_id": event.trace_id,
            "step": event.step,
            "attributes": dict(event.attributes),
            "timestamp": event.timestamp,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


class NullTracer:
    def record(self, event: TraceEvent) -> None:
        return None


class ConsoleTracer:
    """One line of JSON per event on stderr."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream

    def record(self, event: TraceEvent) -> None:
        print(_event_json(event), file=self._stream or sys.stderr, flush=True)


class JsonlTracer:
    """Appends one JSON object per event. Thread safe; the file is created on first write."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def record(self, event: TraceEvent) -> None:
        line = _event_json(event) + "\n"
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)


class MultiTracer:
    """Fan out to several tracers."""

    def __init__(self, *tracers: TracerPort) -> None:
        self._tracers = tracers

    def record(self, event: TraceEvent) -> None:
        for tracer in self._tracers:
            tracer.record(event)


def _canonical(entry: Mapping[str, AttrValue]) -> str:
    return json.dumps(dict(entry), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _chain_hash(prev: str, entry: Mapping[str, AttrValue]) -> str:
    return hashlib.sha256((prev + _canonical(entry)).encode("utf-8")).hexdigest()


class HashChainAuditLog:
    """JSONL file where each line holds ``entry``, ``prev`` and ``hash``.

    ``hash = sha256(prev + canonical entry json)``, starting from 64 zeros. Editing, removing
    or reordering a line anywhere before the last one breaks the chain. Dropping the final
    lines cannot be seen from the file alone; anchor the last hash elsewhere if that matters.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def _last_hash(self) -> str:
        if not self._path.exists():
            return GENESIS
        last = GENESIS
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                last = str(json.loads(line)["hash"])
        return last

    def append(self, entry: Mapping[str, AttrValue]) -> str:
        with self._lock:
            prev = self._last_hash()
            digest = _chain_hash(prev, entry)
            line = json.dumps(
                {"entry": dict(entry), "prev": prev, "hash": digest},
                sort_keys=True,
                ensure_ascii=False,
            )
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            return digest

    def verify(self) -> bool:
        if not self._path.exists():
            return True
        prev = GENESIS
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row["prev"] != prev or row["hash"] != _chain_hash(prev, row["entry"]):
                    return False
                prev = row["hash"]
        except (ValueError, KeyError, TypeError):
            return False
        return True
