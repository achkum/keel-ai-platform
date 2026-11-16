"""Interfaces (ports) for the eight layers.

The core depends only on these protocols. Each layer gets concrete adapters
(for example LiteLLM for models or pgvector for retrieval) in separate packages,
so a backend can be swapped with a spec change instead of a code change.
See ``docs/adr/0004-ports-and-adapters.md``.

These are deliberately small. They will grow as each layer is built.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------- shared types


@dataclass(frozen=True, slots=True)
class Principal:
    """Who a request runs as. The agent always acts with the user's identity."""

    user_id: str
    roles: frozenset[str] = frozenset()
    tenant: str | None = None


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str


@dataclass(frozen=True, slots=True)
class Document:
    """A retrieved chunk. ``labels`` carry source and sensitivity for the provenance policy."""

    source: str
    text: str
    labels: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class GuardrailResult:
    passed: bool
    text: str
    findings: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------- 01 model


@runtime_checkable
class ModelPort(Protocol):
    async def complete(self, messages: Sequence[Message], *, timeout_s: float) -> Completion: ...


# ---------------------------------------------------------------- 02 system prompt


@runtime_checkable
class PromptRegistryPort(Protocol):
    def render(self, template: str, variables: Mapping[str, str]) -> tuple[str, str]:
        """Return the rendered prompt and the exact version id it came from."""
        ...


# ---------------------------------------------------------------- 03 RAG


@runtime_checkable
class RetrieverPort(Protocol):
    async def retrieve(self, query: str, *, principal: Principal, top_k: int) -> list[Document]:
        """Return only documents the principal is allowed to see."""
        ...


# ---------------------------------------------------------------- 04 tools (MCP)


@runtime_checkable
class ToolPort(Protocol):
    name: str

    async def call(self, arguments: Mapping[str, Any], *, principal: Principal) -> str: ...


# ---------------------------------------------------------------- 05 access


@runtime_checkable
class PolicyPort(Protocol):
    def check(self, principal: Principal, action: str, resource: str) -> Decision: ...


# ---------------------------------------------------------------- 06 guardrails


@runtime_checkable
class GuardrailPort(Protocol):
    name: str

    def inspect(self, text: str) -> GuardrailResult: ...


# ---------------------------------------------------------------- 07 cache + router


@runtime_checkable
class CachePort(Protocol):
    async def get(self, key: str, *, principal: Principal) -> Completion | None:
        """Cache entries are scoped per principal, never shared across users."""
        ...

    async def put(self, key: str, value: Completion, *, principal: Principal) -> None: ...


# ---------------------------------------------------------------- 08 observability


@runtime_checkable
class TracerPort(Protocol):
    def record(self, step: str, attributes: Mapping[str, str | int | float | bool]) -> None: ...
