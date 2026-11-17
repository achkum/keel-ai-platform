"""The local HTTP server behind ``keel dev``.

It is a thin FastAPI wrapper over :class:`keel_core.runtime.Runtime`. All policy lives in the
runtime; this module only translates HTTP to a :class:`Request` and back.

**Dev-only identity.** ``POST /v1/ask`` trusts the ``user_id``, ``roles`` and ``tenant`` fields in
the body, so any caller can claim any role. That is fine on ``127.0.0.1`` for development and
wrong anywhere else. Real identity (OIDC tokens mapped to roles) comes with the access layer.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from keel_core.ports import Principal
from keel_core.runtime import Request, Runtime


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=20_000)
    user_id: str = Field(default="dev", min_length=1, max_length=200)
    roles: list[str] = Field(default_factory=list, max_length=50)
    tenant: str | None = Field(default=None, max_length=200)
    approved_tools: list[str] = Field(default_factory=list, max_length=50)


class CitationOut(BaseModel):
    source: str
    ref: str


class AskOut(BaseModel):
    trace_id: str
    status: str
    text: str
    citations: list[CitationOut]
    blocked_by: str | None
    reason: str
    model: str
    prompt_version: str
    cost_usd: float
    latency_ms: float
    cached: bool
    tools_called: list[str]


def create_app(runtime: Runtime) -> FastAPI:
    """Build the FastAPI app for one runtime."""
    api = FastAPI(title="Keel dev server", docs_url=None, redoc_url=None)

    @api.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/v1/spec")
    async def spec_info() -> dict[str, str]:
        spec = runtime.spec
        return {
            "app": spec.app.name,
            "version": spec.app.version,
            "spec_hash": runtime.spec_hash,
            "profile": spec.profile,
        }

    @api.post("/v1/ask")
    async def ask(body: AskBody) -> AskOut:
        principal = Principal(user_id=body.user_id, roles=frozenset(body.roles), tenant=body.tenant)
        response = await runtime.handle(
            Request(
                principal=principal,
                query=body.query,
                approved_tools=frozenset(body.approved_tools),
            )
        )
        return AskOut(
            trace_id=response.trace_id,
            status=response.status,
            text=response.text,
            citations=[CitationOut(source=c.source, ref=c.ref) for c in response.citations],
            blocked_by=response.blocked_by,
            reason=response.reason,
            model=response.model,
            prompt_version=response.prompt_version,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            cached=response.cached,
            tools_called=list(response.tools_called),
        )

    return api
