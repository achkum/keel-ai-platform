"""The request pipeline: one policy and trace path through every declared layer.

``Runtime.handle`` runs the steps in a fixed order. Any step may end the request early by
raising :class:`Stop`; ``handle`` turns that into a response, writes the audit entry and the
final trace event, so every outcome (ok or not) is audited the same way.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from keel_core.ports import (
    AttrValue,
    Completion,
    Document,
    GuardrailPort,
    Message,
    ModelError,
    ModelPort,
    ToolCall,
    ToolPort,
    ToolSpec,
)
from keel_core.runtime._context import (
    RequestState,
    Stop,
    build_user_message,
    cache_key,
    pick_citations,
)
from keel_core.runtime.types import Adapters, Citation, Request, Response, Status
from keel_core.spec.models import KeelSpec

_RATE_WINDOW_S = 60.0
_BUDGET_WINDOW_S = 86400.0


@dataclass(frozen=True, slots=True)
class RuntimeOptions:
    max_tool_steps: int = 5
    """Upper bound on model -> tool -> model rounds per request (agent loop step limit)."""
    untrusted_labels: frozenset[str] = frozenset({"trust:untrusted"})
    """Provenance labels that, once in context, block every tool call unless the request
    carries a human approval for that tool. Tool output always counts as untrusted."""


class Runtime:
    def __init__(
        self,
        spec: KeelSpec,
        adapters: Adapters,
        *,
        spec_hash: str,
        options: RuntimeOptions | None = None,
    ) -> None:
        if not adapters.models:
            raise ValueError("Adapters.models must not be empty")
        self._spec = spec
        self._adapters = adapters
        self._spec_hash = spec_hash
        self._options = options or RuntimeOptions()

    @property
    def spec(self) -> KeelSpec:
        return self._spec

    @property
    def spec_hash(self) -> str:
        return self._spec_hash

    async def handle(self, request: Request) -> Response:
        """Run one request. Never raises for policy outcomes; those come back as a status."""
        st = RequestState(
            request=request,
            trace_id=request.request_id or uuid.uuid4().hex,
            tracer=self._adapters.tracer,
        )
        self._trace_request(st)
        try:
            text, citations = await self._run(st)
        except Stop as stop:
            return self._finish(st, stop.status, f"Request blocked: {stop.reason}", (), stop)
        return self._finish(st, "ok", text, citations, None)

    # ------------------------------------------------------------ pipeline

    async def _run(self, st: RequestState) -> tuple[str, tuple[Citation, ...]]:
        self._check_access(st)
        await self._check_limits(st)
        st.query = self._guard(self._adapters.input_guardrails, st.request.query, st, "input")
        system, st.prompt_version = self._adapters.prompts.render(
            self._spec.system_prompt.template, self._spec.system_prompt.variables
        )
        st.docs = await self._retrieve(st)
        completion = await self._answer(st, system)
        text = self._guard(self._adapters.output_guardrails, completion.text, st, "output")
        return text, pick_citations(text, st.docs)

    def _check_access(self, st: RequestState) -> None:
        decision = self._adapters.policy.check(st.principal, "ask", f"app:{self._spec.app.name}")
        st.emit("access.app", allowed=decision.allowed)
        if not decision.allowed:
            raise Stop("denied", "access:app", decision.reason or "access denied")

    async def _check_limits(self, st: RequestState) -> None:
        router = self._spec.cache_router
        quota, subject = self._adapters.quota, st.quota_subject
        if router.rate_limit_per_minute is not None:
            total = await quota.add(f"rate:{subject}", 1, window_s=_RATE_WINDOW_S)
            st.emit("rate_limit", total=total, limit=router.rate_limit_per_minute)
            if total > router.rate_limit_per_minute:
                raise Stop("limited", "rate_limit", "rate limit exceeded")
        if router.budget_usd_per_day is not None:
            used = await quota.usage(f"budget:{subject}", window_s=_BUDGET_WINDOW_S)
            st.emit("budget", used_usd=used, limit_usd=router.budget_usd_per_day)
            if used >= router.budget_usd_per_day:
                raise Stop("limited", "budget", "daily budget used up")

    def _guard(
        self, guards: Sequence[GuardrailPort], text: str, st: RequestState, phase: str
    ) -> str:
        for guard in guards:
            result = guard.inspect(text)
            st.emit(
                f"guardrail.{phase}",
                name=guard.name,
                passed=result.passed,
                findings=len(result.findings),
            )
            if not result.passed:
                raise Stop(
                    "blocked", f"guardrail:{guard.name}", f"{phase} check '{guard.name}' failed"
                )
            text = result.text
        return text

    # ------------------------------------------------------------ retrieval

    async def _retrieve(self, st: RequestState) -> list[Document]:
        rag, retriever = self._spec.rag, self._adapters.retriever
        if rag is None or retriever is None:
            return []
        allowed = frozenset(
            s.name
            for s in rag.sources
            if self._adapters.policy.check(st.principal, "retrieve", f"source:{s.name}").allowed
        )
        if not allowed:
            st.emit("retrieve.skipped", reason="no allowed sources")
            return []
        found = await retriever.retrieve(st.query, sources=allowed, top_k=rag.top_k)
        permitted = [d for d in found if d.source in allowed]
        if len(permitted) != len(found):
            st.emit("access.filtered", dropped=len(found) - len(permitted))
        kept = permitted[: rag.top_k]
        st.emit("retrieve", documents=len(kept))
        return [dataclasses.replace(d, labels=d.labels | {f"source:{d.source}"}) for d in kept]

    # ------------------------------------------------------------ model + tools

    async def _answer(self, st: RequestState, system: str) -> Completion:
        cache = self._adapters.cache
        key: str | None = None
        if cache is not None and self._spec.cache_router.cache != "off":
            key = cache_key(self._spec_hash, st.prompt_version, st.query, st.docs)
            hit = await cache.get(key, principal=st.principal)
            st.emit("cache", hit=hit is not None)
            if hit is not None:
                st.cached, st.model = True, hit.model
                return hit
        completion = await self._converse(st, system)
        if cache is not None and key is not None and not st.tools_called:
            await cache.put(key, completion, principal=st.principal)
        return completion

    def _offered_tools(self, st: RequestState) -> dict[str, ToolPort]:
        offered: dict[str, ToolPort] = {}
        for tool in self._spec.tools:
            impl = self._adapters.tools.get(tool.name)
            allowed = self._adapters.policy.check(st.principal, "call", f"tool:{tool.name}")
            if impl is not None and allowed.allowed:
                offered[tool.name] = impl
        return offered

    async def _converse(self, st: RequestState, system: str) -> Completion:
        offered = self._offered_tools(st)
        specs = [ToolSpec(n, t.description, t.input_schema) for n, t in offered.items()]
        messages = [
            Message("system", system),
            Message("user", build_user_message(st.query, st.docs)),
        ]
        untrusted = any(d.labels & self._options.untrusted_labels for d in st.docs)
        rounds = 0
        while True:
            completion = await self._call_model(st, messages, specs)
            if not completion.tool_calls:
                return completion
            if rounds >= self._options.max_tool_steps:
                raise Stop("blocked", "step_limit", "too many tool steps")
            rounds += 1
            messages.append(Message("assistant", completion.text, tool_calls=completion.tool_calls))
            for call in completion.tool_calls:
                if call.name in offered:
                    output = await self._run_tool(st, offered[call.name], call, untrusted)
                    untrusted = True  # every tool output is untrusted from here on
                else:
                    st.emit("tool.denied", tool=call.name)
                    output = "error: tool not allowed"
                messages.append(Message("tool", output, tool_call_id=call.id))

    async def _run_tool(
        self, st: RequestState, tool: ToolPort, call: ToolCall, untrusted: bool
    ) -> str:
        approved = call.name in st.request.approved_tools
        if untrusted and not approved:
            raise Stop(
                "blocked",
                f"provenance:tool:{call.name}",
                f"tool '{call.name}' needs approval because untrusted content is in context",
            )
        if call.name in self._approval_tools and not approved:
            raise Stop(
                "blocked", f"approval:tool:{call.name}", f"tool '{call.name}' needs approval"
            )
        st.tools_called.append(call.name)
        try:
            output = await asyncio.wait_for(
                tool.call(call.arguments, principal=st.principal), self._spec.model.timeout_s
            )
        except Exception as exc:  # fail closed: a broken tool must not crash the request
            st.emit("tool.error", tool=call.name, error=type(exc).__name__)
            return "error: tool failed"
        st.emit("tool.call", tool=call.name)
        return output

    @property
    def _approval_tools(self) -> frozenset[str]:
        return frozenset(t.name for t in self._spec.tools if t.requires_approval)

    async def _call_model(
        self, st: RequestState, messages: Sequence[Message], specs: Sequence[ToolSpec]
    ) -> Completion:
        models = self._adapters.models
        for index, model in enumerate(models):
            completion = await self._try_model(st, model, messages, specs)
            if completion is not None:
                return await self._account(st, completion, model)
            if index + 1 < len(models):
                st.emit("model.fallback", failed=model.name, next=models[index + 1].name)
        raise Stop("error", "model", f"all {len(models)} model(s) failed")

    async def _try_model(
        self,
        st: RequestState,
        model: ModelPort,
        messages: Sequence[Message],
        specs: Sequence[ToolSpec],
    ) -> Completion | None:
        layer = self._spec.model
        for attempt in range(1 + layer.max_retries):
            try:
                return await asyncio.wait_for(
                    model.complete(messages, timeout_s=layer.timeout_s, tools=specs),
                    layer.timeout_s,
                )
            except (ModelError, TimeoutError) as exc:
                st.emit(
                    "model.error", model=model.name, attempt=attempt + 1, error=type(exc).__name__
                )
            except Exception as exc:
                # A bug in an adapter: do not retry it, fall back to the next model,
                # and never let it crash the request path.
                st.emit(
                    "model.error",
                    model=model.name,
                    attempt=attempt + 1,
                    error=type(exc).__name__,
                    unexpected=True,
                )
                return None
        return None

    async def _account(
        self, st: RequestState, completion: Completion, model: ModelPort
    ) -> Completion:
        st.model = completion.model or model.name
        st.cost_usd += completion.cost_usd
        if self._spec.cache_router.budget_usd_per_day is not None:
            await self._adapters.quota.add(
                f"budget:{st.quota_subject}", completion.cost_usd, window_s=_BUDGET_WINDOW_S
            )
        st.emit("model.call", model=st.model, cost_usd=completion.cost_usd)
        return completion

    # ------------------------------------------------------------ finish

    def _trace_request(self, st: RequestState) -> None:
        p = st.principal
        attrs: dict[str, AttrValue] = {
            "user_id": p.user_id,
            "roles": ",".join(sorted(p.roles)),
            "tenant": p.tenant or "",
        }
        if self._spec.observability.log_prompts:
            attrs["query"] = st.request.query
        st.emit("request", **attrs)

    def _finish(
        self,
        st: RequestState,
        status: Status,
        text: str,
        citations: tuple[Citation, ...],
        stop: Stop | None,
    ) -> Response:
        response = Response(
            trace_id=st.trace_id,
            status=status,
            text=text,
            citations=citations,
            blocked_by=stop.blocked_by if stop else None,
            reason=stop.reason if stop else "",
            model=st.model,
            prompt_version=st.prompt_version,
            spec_hash=self._spec_hash,
            cost_usd=st.cost_usd,
            latency_ms=st.latency_ms(),
            cached=st.cached,
            tools_called=tuple(st.tools_called),
            retrieved_sources=st.sources(),
        )
        self._adapters.audit.append(
            {
                "trace_id": response.trace_id,
                "app": self._spec.app.name,
                "version": self._spec.app.version,
                "spec_hash": self._spec_hash,
                "user_id": st.principal.user_id,
                "tenant": st.principal.tenant or "",
                "status": status,
                "blocked_by": response.blocked_by or "",
                "model": response.model,
                "prompt_version": response.prompt_version,
                "cost_usd": response.cost_usd,
                "sources": ",".join(response.retrieved_sources),
                "tools": ",".join(response.tools_called),
            }
        )
        st.emit(
            "response",
            status=status,
            latency_ms=response.latency_ms,
            cost_usd=response.cost_usd,
            blocked_by=response.blocked_by or "",
        )
        return response
