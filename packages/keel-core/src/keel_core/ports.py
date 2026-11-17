"""Interfaces (ports) for the eight layers.

The core depends only on these protocols. Each layer gets concrete adapters
(for example LiteLLM for models or pgvector for retrieval) in separate packages,
so a backend can be swapped with a spec change instead of a code change.
See ``docs/adr/0004-ports-and-adapters.md``.

Enforcement never lives in an adapter alone. The runtime in ``keel_core.runtime``
asks the policy port, filters what adapters return and traces every step,
so a buggy or hostile adapter cannot widen what a user may reach.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

AttrValue = str | int | float | bool
"""Value types allowed in trace and audit attributes (OpenTelemetry compatible)."""

# ---------------------------------------------------------------- shared types


@dataclass(frozen=True, slots=True)
class Principal:
    """Who a request runs as. The agent always acts with the user's identity."""

    user_id: str
    roles: frozenset[str] = frozenset()
    tenant: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool call the model asked for. ``arguments`` is the decoded JSON object."""

    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """What the model is told about a tool it may call."""

    name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    """Set on ``tool`` messages: which call this is the result of."""
    tool_calls: tuple[ToolCall, ...] = ()
    """Set on ``assistant`` messages that asked for tools."""


@dataclass(frozen=True, slots=True)
class Document:
    """A retrieved chunk.

    ``source`` is the spec name of the RAG source (for example ``handbook``) and is what
    access is checked against. ``ref`` is a stable citation id inside that source, for
    example ``handbook/travel.md#2``. ``labels`` carry provenance and sensitivity for the
    provenance policy, for example ``{"source:handbook", "trust:internal"}``.
    """

    source: str
    text: str
    labels: frozenset[str] = frozenset()
    ref: str = ""
    score: float = 0.0


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float = 0.0
    model: str = ""
    """``provider/name`` of the model that produced this completion."""
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class GuardrailResult:
    """Outcome of one check.

    ``passed=False`` blocks the request. A check may also pass while rewriting the text,
    for example PII redaction, in which case ``text`` is the rewritten version and
    ``findings`` says what was changed.
    """

    passed: bool
    text: str
    findings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One step on the policy and trace path. No prompt text unless the spec allows it."""

    trace_id: str
    step: str
    attributes: Mapping[str, AttrValue] = field(default_factory=dict)
    timestamp: float = 0.0
    """Unix time in seconds."""


# ---------------------------------------------------------------- 01 model


class ModelError(Exception):
    """A model call failed in a way a fallback may fix (timeout, rate limit, outage)."""


@runtime_checkable
class ModelPort(Protocol):
    name: str
    """``provider/name``, used in traces and cost accounting."""

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        timeout_s: float,
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        """Raise :class:`ModelError` (or ``TimeoutError``) on a failure worth falling back from."""
        ...


# ---------------------------------------------------------------- 02 system prompt


@runtime_checkable
class PromptRegistryPort(Protocol):
    def render(self, template: str, variables: Mapping[str, str]) -> tuple[str, str]:
        """Return the rendered prompt and the exact version id it came from.

        The version id must change whenever the template text changes (a content hash works).
        """
        ...


# ---------------------------------------------------------------- 03 RAG


@runtime_checkable
class RetrieverPort(Protocol):
    async def retrieve(self, query: str, *, sources: frozenset[str], top_k: int) -> list[Document]:
        """Return up to ``top_k`` documents, only from ``sources``.

        The runtime decides ``sources`` from the access policy and drops anything returned
        from outside it, so the retriever never makes the access decision on its own.
        """
        ...


# ---------------------------------------------------------------- 04 tools (MCP)


@runtime_checkable
class ToolPort(Protocol):
    name: str
    description: str
    input_schema: Mapping[str, Any]

    async def call(self, arguments: Mapping[str, Any], *, principal: Principal) -> str: ...


# ---------------------------------------------------------------- 05 access


@runtime_checkable
class PolicyPort(Protocol):
    def check(self, principal: Principal, action: str, resource: str) -> Decision:
        """Decide one access question.

        Actions and resources used by the runtime:
        ``("ask", "app:<name>")``, ``("retrieve", "source:<name>")``, ``("call", "tool:<name>")``.
        """
        ...


# ---------------------------------------------------------------- 06 guardrails


@runtime_checkable
class GuardrailPort(Protocol):
    name: str
    """The spec check name, for example ``pii`` or ``prompt_injection``."""

    def inspect(self, text: str) -> GuardrailResult: ...


# ---------------------------------------------------------------- 07 cache + router


@runtime_checkable
class CachePort(Protocol):
    async def get(self, key: str, *, principal: Principal) -> Completion | None:
        """Cache entries are scoped per principal, never shared across users."""
        ...

    async def put(self, key: str, value: Completion, *, principal: Principal) -> None: ...


@runtime_checkable
class QuotaPort(Protocol):
    """Sliding-window counters for rate limits and budgets. Swappable for Redis later."""

    async def add(self, key: str, amount: float, *, window_s: float) -> float:
        """Add ``amount`` to ``key`` and return the new total inside the window."""
        ...

    async def usage(self, key: str, *, window_s: float) -> float:
        """Return the current total for ``key`` inside the window without changing it."""
        ...


# ---------------------------------------------------------------- 08 observability


@runtime_checkable
class TracerPort(Protocol):
    def record(self, event: TraceEvent) -> None: ...


@runtime_checkable
class AuditLogPort(Protocol):
    """Append-only, tamper-evident log: each entry is chained to the previous one by hash."""

    def append(self, entry: Mapping[str, AttrValue]) -> str:
        """Append one entry and return its hash."""
        ...

    def verify(self) -> bool:
        """Return True if no entry was changed, removed or reordered."""
        ...
