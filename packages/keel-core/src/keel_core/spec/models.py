"""Typed schema for ``keel.yaml``.

One spec describes a whole LLM application across eight layers plus its eval suites.
The schema is strict on purpose: unknown keys are rejected, and cross-references
(roles to tools, roles to sources) are checked when the spec is loaded.

The format is provisional (``keel/v0``) and will change before v1.0.
See ``docs/adr/0003-spec-as-single-source-of-truth.md``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SPEC_VERSION = "keel/v0"

Slug = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")]
SemVer = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")]

GuardrailCheck = Literal["pii", "prompt_injection", "toxicity", "topic", "schema"]


class _Strict(BaseModel):
    """Base for every spec block: no unknown keys, immutable once loaded."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


# ---------------------------------------------------------------- app


class AppMeta(_Strict):
    name: Slug
    version: SemVer
    description: str = ""


# ---------------------------------------------------------------- 01 model


class ModelRef(_Strict):
    provider: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]


class ModelLayer(ModelRef):
    fallbacks: tuple[ModelRef, ...] = ()
    timeout_s: Annotated[float, Field(gt=0, le=600)] = 30.0
    max_retries: Annotated[int, Field(ge=0, le=10)] = 2

    @model_validator(mode="after")
    def _fallbacks_differ_from_primary(self) -> Self:
        primary = (self.provider, self.name)
        seen = {primary}
        for fb in self.fallbacks:
            key = (fb.provider, fb.name)
            if key in seen:
                raise ValueError(f"fallback {fb.provider}/{fb.name} repeats an earlier model")
            seen.add(key)
        return self


# ---------------------------------------------------------------- 02 system prompt


class SystemPromptLayer(_Strict):
    template: Annotated[str, Field(min_length=1, description="Path to the prompt template.")]
    variables: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------- 03 RAG


class Source(_Strict):
    name: Slug
    uri: Annotated[str, Field(min_length=1)]


class RagLayer(_Strict):
    sources: Annotated[tuple[Source, ...], Field(min_length=1)]
    top_k: Annotated[int, Field(ge=1, le=100)] = 5
    rerank: bool = False
    require_citations: bool = True

    @model_validator(mode="after")
    def _unique_source_names(self) -> Self:
        _require_unique((s.name for s in self.sources), "rag source")
        return self


# ---------------------------------------------------------------- 04 tools (MCP)


class Tool(_Strict):
    name: Slug
    mcp_server: Annotated[str, Field(min_length=1)]
    requires_approval: bool = False


# ---------------------------------------------------------------- 05 access


class Role(_Strict):
    name: Slug
    tools: tuple[Slug, ...] = ()
    sources: tuple[Slug, ...] = ()


class AccessLayer(_Strict):
    default: Literal["deny", "allow"] = "deny"
    roles: tuple[Role, ...] = ()

    @model_validator(mode="after")
    def _unique_role_names(self) -> Self:
        _require_unique((r.name for r in self.roles), "role")
        return self


# ---------------------------------------------------------------- 06 guardrails


class GuardrailsLayer(_Strict):
    input: tuple[GuardrailCheck, ...] = ("prompt_injection", "pii")
    output: tuple[GuardrailCheck, ...] = ("pii",)


# ---------------------------------------------------------------- 07 cache + router


class CacheRouterLayer(_Strict):
    cache: Literal["off", "exact", "semantic"] = "exact"
    budget_usd_per_day: Annotated[float, Field(gt=0)] | None = None
    rate_limit_per_minute: Annotated[int, Field(gt=0)] | None = None


# ---------------------------------------------------------------- 08 observability


class ObservabilityLayer(_Strict):
    exporter: Literal["otlp", "console", "none"] = "otlp"
    log_prompts: bool = False


# ---------------------------------------------------------------- eval gate


class QualitySuite(_Strict):
    name: Slug
    dataset: Annotated[str, Field(min_length=1)]
    min_score: Annotated[float, Field(ge=0, le=1)]


class AttackSuite(_Strict):
    name: Slug
    dataset: Annotated[str, Field(min_length=1)]
    max_failures: Annotated[int, Field(ge=0)] = 0


class LoadSuite(_Strict):
    requests_per_second: Annotated[float, Field(gt=0)]
    max_p95_latency_ms: Annotated[int, Field(gt=0)]


class EvalGate(_Strict):
    quality: tuple[QualitySuite, ...] = ()
    attack: tuple[AttackSuite, ...] = ()
    load: LoadSuite | None = None

    @model_validator(mode="after")
    def _unique_suite_names(self) -> Self:
        names = [s.name for s in self.quality] + [s.name for s in self.attack]
        _require_unique(names, "eval suite")
        return self


# ---------------------------------------------------------------- root


class KeelSpec(_Strict):
    """The whole application. Parsed from ``keel.yaml``."""

    spec_version: Literal["keel/v0"] = Field(alias="keel")
    app: AppMeta
    profile: Literal["strict", "standard"] = "strict"

    model: ModelLayer
    system_prompt: SystemPromptLayer
    rag: RagLayer | None = None
    tools: tuple[Tool, ...] = ()
    access: AccessLayer = Field(default_factory=AccessLayer)
    guardrails: GuardrailsLayer = Field(default_factory=GuardrailsLayer)
    cache_router: CacheRouterLayer = Field(default_factory=CacheRouterLayer)
    observability: ObservabilityLayer = Field(default_factory=ObservabilityLayer)
    evals: EvalGate = Field(default_factory=EvalGate)

    model_config = ConfigDict(
        extra="forbid", frozen=True, populate_by_name=True, str_strip_whitespace=True
    )

    @model_validator(mode="after")
    def _cross_references(self) -> Self:
        _require_unique((t.name for t in self.tools), "tool")
        tool_names = {t.name for t in self.tools}
        source_names = {s.name for s in self.rag.sources} if self.rag else set()
        for role in self.access.roles:
            if unknown := set(role.tools) - tool_names:
                raise ValueError(
                    f"role '{role.name}' refers to undeclared tools: {sorted(unknown)}"
                )
            if unknown := set(role.sources) - source_names:
                raise ValueError(
                    f"role '{role.name}' refers to undeclared rag sources: {sorted(unknown)}"
                )
        return self

    @model_validator(mode="after")
    def _strict_profile(self) -> Self:
        """The strict profile is the default and enforces secure-by-default settings."""
        if self.profile != "strict":
            return self
        problems: list[str] = []
        if self.access.default != "deny":
            problems.append("access.default must be 'deny'")
        if "prompt_injection" not in self.guardrails.input:
            problems.append("guardrails.input must include 'prompt_injection'")
        if self.observability.log_prompts:
            problems.append("observability.log_prompts must be false")
        if self.tools and not self.evals.attack:
            problems.append("apps with tools must declare at least one attack suite")
        if problems:
            raise ValueError("strict profile: " + "; ".join(problems))
        return self


def _require_unique(names: Iterable[str], what: str) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ValueError(f"duplicate {what} name: '{name}'")
        seen.add(name)
