"""Per-request state and small pure helpers for the pipeline.

Everything that changes during a request lives in :class:`RequestState`, which is created
inside ``Runtime.handle``. The ``Runtime`` itself holds no request data, so concurrent
calls cannot see each other.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from keel_core.ports import AttrValue, Document, Principal, TraceEvent, TracerPort
from keel_core.runtime.types import Citation, Request, Status

_MARKER = re.compile(r"\[(\d+)\]")


class Stop(Exception):  # noqa: N818 - control flow, not an error
    """Ends the request early with a non-ok status. Caught once, in ``Runtime.handle``."""

    def __init__(self, status: Status, blocked_by: str, reason: str) -> None:
        super().__init__(reason)
        self.status: Status = status
        self.blocked_by = blocked_by
        self.reason = reason


@dataclass(slots=True)
class RequestState:
    request: Request
    trace_id: str
    tracer: TracerPort
    started: float = field(default_factory=time.perf_counter)
    query: str = ""
    """The query after input guardrails (so after redaction)."""
    docs: list[Document] = field(default_factory=list)
    cost_usd: float = 0.0
    model: str = ""
    prompt_version: str = ""
    cached: bool = False
    tools_called: list[str] = field(default_factory=list)

    @property
    def principal(self) -> Principal:
        return self.request.principal

    @property
    def quota_subject(self) -> str:
        return self.principal.tenant or self.principal.user_id

    def emit(self, step: str, **attributes: AttrValue) -> None:
        self.tracer.record(TraceEvent(self.trace_id, step, attributes, time.time()))

    def latency_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000.0

    def sources(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(d.source for d in self.docs))


def build_user_message(query: str, docs: Sequence[Document]) -> str:
    if not docs:
        return query
    lines = [f"[{i}] ({d.ref}) {d.text}" for i, d in enumerate(docs, start=1)]
    return "Context:\n" + "\n".join(lines) + f"\n\nQuestion: {query}"


def cache_key(spec_hash: str, prompt_version: str, query: str, docs: Sequence[Document]) -> str:
    payload = json.dumps([spec_hash, prompt_version, query, sorted(d.ref for d in docs)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def pick_citations(answer: str, docs: Sequence[Document]) -> tuple[Citation, ...]:
    """Cite the documents the answer marks with ``[n]``, or all of them if it marks none."""
    marked = {int(m) for m in _MARKER.findall(answer)}
    chosen = [d for i, d in enumerate(docs, start=1) if i in marked] or list(docs)
    return tuple(dict.fromkeys(Citation(d.source, d.ref) for d in chosen))
