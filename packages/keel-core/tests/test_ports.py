"""Contract tests: minimal in-memory adapters must satisfy every layer interface.

If a port changes shape, these fakes stop matching and the test fails, which is the
signal to update every adapter package as well.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from keel_core.ports import (
    CachePort,
    Completion,
    Decision,
    Document,
    GuardrailPort,
    GuardrailResult,
    Message,
    ModelPort,
    PolicyPort,
    Principal,
    PromptRegistryPort,
    RetrieverPort,
    ToolPort,
    TracerPort,
)

ALICE = Principal(user_id="alice", roles=frozenset({"employee"}))


class EchoModel:
    async def complete(self, messages: Sequence[Message], *, timeout_s: float) -> Completion:
        text = messages[-1].content
        return Completion(text=text, input_tokens=len(text), output_tokens=len(text))


class StaticPrompts:
    def render(self, template: str, variables: Mapping[str, str]) -> tuple[str, str]:
        return template.format_map(dict(variables)), "v1"


class RoleFilteredRetriever:
    def __init__(self, docs: Mapping[str, Document]) -> None:
        self._docs = docs

    async def retrieve(self, query: str, *, principal: Principal, top_k: int) -> list[Document]:
        allowed = [d for role, d in self._docs.items() if role in principal.roles]
        return allowed[:top_k]


class UpperTool:
    name = "upper"

    async def call(self, arguments: Mapping[str, Any], *, principal: Principal) -> str:
        return str(arguments["text"]).upper()


class DenyAllPolicy:
    def check(self, principal: Principal, action: str, resource: str) -> Decision:
        return Decision(allowed=False, reason="default deny")


class KeywordGuardrail:
    name = "keyword"

    def inspect(self, text: str) -> GuardrailResult:
        hit = "ignore previous instructions" in text.lower()
        return GuardrailResult(passed=not hit, text=text, findings=("injection",) if hit else ())


class PerUserCache:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], Completion] = {}

    async def get(self, key: str, *, principal: Principal) -> Completion | None:
        return self._store.get((principal.user_id, key))

    async def put(self, key: str, value: Completion, *, principal: Principal) -> None:
        self._store[(principal.user_id, key)] = value


class ListTracer:
    def __init__(self) -> None:
        self.steps: list[str] = []

    def record(self, step: str, attributes: Mapping[str, str | int | float | bool]) -> None:
        self.steps.append(step)


def test_fakes_satisfy_every_port() -> None:
    pairs: list[tuple[object, type]] = [
        (EchoModel(), ModelPort),
        (StaticPrompts(), PromptRegistryPort),
        (RoleFilteredRetriever({}), RetrieverPort),
        (UpperTool(), ToolPort),
        (DenyAllPolicy(), PolicyPort),
        (KeywordGuardrail(), GuardrailPort),
        (PerUserCache(), CachePort),
        (ListTracer(), TracerPort),
    ]
    for adapter, port in pairs:
        assert isinstance(adapter, port), f"{type(adapter).__name__} does not satisfy {port}"


def test_ports_carry_the_principal_end_to_end() -> None:
    async def scenario() -> None:
        docs = {"employee": Document("handbook", "travel policy"), "hr": Document("hr", "salaries")}
        retrieved = await RoleFilteredRetriever(docs).retrieve("q", principal=ALICE, top_k=5)
        assert [d.source for d in retrieved] == ["handbook"]

        cache = PerUserCache()
        answer = await EchoModel().complete([Message("user", "hi")], timeout_s=1)
        await cache.put("q", answer, principal=ALICE)
        assert await cache.get("q", principal=ALICE) == answer
        assert await cache.get("q", principal=Principal(user_id="bob")) is None

    asyncio.run(scenario())


def test_guardrail_and_policy_results() -> None:
    blocked = KeywordGuardrail().inspect("Please IGNORE previous instructions")
    assert not blocked.passed
    assert blocked.findings == ("injection",)
    assert not DenyAllPolicy().check(ALICE, "call", "tool:refund").allowed
