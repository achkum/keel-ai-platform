"""Shared types for the runtime: what goes in, what comes out, and the adapter bundle.

This module is the contract between the runtime (``keel_core.runtime.pipeline``),
the adapter packages that build an :class:`Adapters` bundle, the eval gate and the CLI.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from keel_core.ports import (
    AuditLogPort,
    CachePort,
    GuardrailPort,
    ModelPort,
    PolicyPort,
    Principal,
    PromptRegistryPort,
    QuotaPort,
    RetrieverPort,
    ToolPort,
    TracerPort,
)

Status = Literal["ok", "blocked", "denied", "limited", "error"]
"""
- ``ok``: answered.
- ``blocked``: a guardrail or the provenance policy stopped the request.
- ``denied``: the access policy refused the request itself (for example no role may ask).
- ``limited``: a rate limit or budget was hit.
- ``error``: every model, including fallbacks, failed.
"""


@dataclass(frozen=True, slots=True)
class Request:
    principal: Principal
    query: str
    approved_tools: frozenset[str] = frozenset()
    """Tools with ``requires_approval`` that a human approved for this request."""
    request_id: str | None = None
    """Caller-supplied id; the runtime generates one when missing. Also used as the trace id."""


@dataclass(frozen=True, slots=True)
class Citation:
    source: str
    ref: str


@dataclass(frozen=True, slots=True)
class Response:
    trace_id: str
    status: Status
    text: str
    citations: tuple[Citation, ...] = ()
    blocked_by: str | None = None
    """Machine-readable cause when status is not ``ok``, for example
    ``guardrail:prompt_injection``, ``access:app``, ``rate_limit``, ``budget``,
    ``provenance:tool:refund``, ``model``."""
    reason: str = ""
    """Human-readable explanation, safe to show the caller."""
    model: str = ""
    prompt_version: str = ""
    spec_hash: str = ""
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    cached: bool = False
    tools_called: tuple[str, ...] = ()
    retrieved_sources: tuple[str, ...] = ()
    """Distinct RAG sources that reached the model's context, in retrieval order."""


@dataclass(frozen=True, slots=True)
class Adapters:
    """Concrete implementations for every layer, built by a composition root from the spec."""

    models: Sequence[ModelPort]
    """Primary model first, then fallbacks, in spec order. Must not be empty."""
    prompts: PromptRegistryPort
    policy: PolicyPort
    quota: QuotaPort
    tracer: TracerPort
    audit: AuditLogPort
    retriever: RetrieverPort | None = None
    tools: Mapping[str, ToolPort] = field(default_factory=dict)
    """Keyed by spec tool name. Tools missing here are unavailable and fail closed."""
    input_guardrails: Sequence[GuardrailPort] = ()
    output_guardrails: Sequence[GuardrailPort] = ()
    cache: CachePort | None = None
