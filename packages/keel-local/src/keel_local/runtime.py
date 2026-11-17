"""Composition root: reads ``keel.yaml`` and wires one in-process adapter per layer."""

from __future__ import annotations

from pathlib import Path

from keel_core.errors import KeelError
from keel_core.ports import ModelPort, TracerPort
from keel_core.runtime import Adapters, Runtime
from keel_core.spec import load_spec, spec_hash
from keel_core.spec.models import KeelSpec
from keel_local.cache import InMemoryCache
from keel_local.guardrails import guardrails_for
from keel_local.models import ExtractiveModel, LiteLLMModel
from keel_local.observability import (
    ConsoleTracer,
    HashChainAuditLog,
    JsonlTracer,
    MultiTracer,
    NullTracer,
)
from keel_local.policy import RbacPolicy
from keel_local.prompts import FilePromptRegistry, check_no_secrets
from keel_local.quota import InMemoryQuota
from keel_local.retrieval import LocalRetriever, resolve_file_source
from keel_local.tools import load_tools

STATE_DIR_NAME = ".keel"


def state_dir_for(spec_path: Path) -> Path:
    """Where traces, the audit log and releases live: ``<spec dir>/.keel``."""
    return Path(spec_path).resolve().parent / STATE_DIR_NAME


def _build_models(spec: KeelSpec, *, offline: bool) -> list[ModelPort]:
    if offline:
        return [ExtractiveModel()]
    models: list[ModelPort] = []
    for ref in (spec.model, *spec.model.fallbacks):
        if ref.provider == "keel":
            models.append(ExtractiveModel())
        else:
            models.append(LiteLLMModel(ref.provider, ref.name))
    return models


def _build_tracer(spec: KeelSpec, state: Path) -> TracerPort:
    """Pick tracers from ``observability.exporter``.

    Real OTLP export is a later adapter; in local mode ``otlp`` writes the same events to
    ``traces.jsonl`` so nothing is lost and the shape matches what an exporter would send.
    """
    exporter = spec.observability.exporter
    if exporter == "none":
        return NullTracer()
    jsonl = JsonlTracer(state / "traces.jsonl")
    if exporter == "console":
        return MultiTracer(jsonl, ConsoleTracer())
    return jsonl


def build_runtime(
    spec_path: Path, *, offline: bool = False, state_dir: Path | None = None
) -> Runtime:
    """Load and validate the spec, build every adapter and return a ready runtime.

    ``offline=True`` replaces every model (primary and fallbacks) with the built-in
    deterministic extractive model, so evals and the quickstart need no API keys.

    The state directory is created lazily, when something is first written to it.

    Raises:
        keel_core.SpecError: if the spec is invalid.
        keel_core.KeelError: if a declared resource (prompt template, RAG source) is missing.
    """
    spec_path = Path(spec_path)
    spec = load_spec(spec_path)
    base = spec_path.resolve().parent
    state = Path(state_dir) if state_dir is not None else state_dir_for(spec_path)

    prompts = FilePromptRegistry(base)
    rendered, _version = prompts.render(spec.system_prompt.template, spec.system_prompt.variables)
    check_no_secrets(rendered)

    retriever: LocalRetriever | None = None
    if spec.rag:
        sources = {s.name: resolve_file_source(s.uri, base) for s in spec.rag.sources}
        retriever = LocalRetriever(sources)

    tools = load_tools(spec.tools, base_dir=base, lock_path=state / "tools.lock")
    models = _build_models(spec, offline=offline)
    if not models:  # pragma: no cover - the spec always has a primary model
        raise KeelError("no model configured")

    cache = None if spec.cache_router.cache == "off" else InMemoryCache()
    adapters = Adapters(
        models=models,
        prompts=prompts,
        policy=RbacPolicy(spec.access),
        quota=InMemoryQuota(),
        tracer=_build_tracer(spec, state),
        audit=HashChainAuditLog(state / "audit.jsonl"),
        retriever=retriever,
        tools=tools,
        input_guardrails=guardrails_for(spec.guardrails.input),
        output_guardrails=guardrails_for(spec.guardrails.output),
        cache=cache,
    )
    return Runtime(spec, adapters, spec_hash=spec_hash(spec))
