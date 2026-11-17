from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

from keel_core.errors import KeelError
from keel_core.ports import Message, ModelError, ToolSpec
from keel_local.models import ExtractiveModel, LiteLLMModel, count_tokens

CONTEXT = (
    "Context:\n[1] (handbook/travel.md#1) Employees may book economy flights. "
    "Hotels are capped.\n[2] (handbook/travel.md#2) Dinner is reimbursed up to 30 euros.\n\n"
    "Question: "
)


def _ask(question: str, *, tools: tuple[ToolSpec, ...] = (), prefix: str = CONTEXT) -> Any:
    msgs = [Message("system", "sys"), Message("user", prefix + question)]
    return asyncio.run(ExtractiveModel().complete(msgs, timeout_s=1, tools=tools))


def test_extractive_quotes_best_sentence_with_marker() -> None:
    out = _ask("Which flights can employees book?")
    assert out.text == "Employees may book economy flights. [1]"
    assert out.cost_usd == 0.0
    assert out.model == "keel/extractive"
    assert out.output_tokens == count_tokens(out.text)


def test_extractive_unknown_without_overlap_or_context() -> None:
    assert "do not know" in _ask("zebra migration patterns").text
    assert "do not know" in _ask("anything", prefix="").text


def test_extractive_no_user_message() -> None:
    out = asyncio.run(ExtractiveModel().complete([], timeout_s=1))
    assert "do not know" in out.text


def test_extractive_tool_round_trip() -> None:
    tool = ToolSpec("lookup-ticket", "d")
    first = _ask("please use tool lookup-ticket for 42", tools=(tool,))
    assert first.tool_calls[0].name == "lookup-ticket"
    assert first.tool_calls[0].arguments["query"].startswith("please use tool")
    msgs = [
        Message("user", "use tool lookup-ticket"),
        Message("assistant", "", tool_calls=first.tool_calls),
        Message("tool", "ticket is open", tool_call_id="call_1"),
    ]
    second = asyncio.run(ExtractiveModel().complete(msgs, timeout_s=1, tools=(tool,)))
    assert second.text == "ticket is open"
    assert not second.tool_calls


def test_extractive_ignores_tool_not_offered() -> None:
    out = _ask("use tool lookup-ticket now")
    assert not out.tool_calls


# ---------------------------------------------------------------- LiteLLM


class _Obj:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


def _fake_litellm(
    monkeypatch: pytest.MonkeyPatch, *, response: Any = None, error: Exception | None = None
) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    async def acompletion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        if error:
            raise error
        return response

    def completion_cost(completion_response: Any) -> float:
        return 0.002

    mod = types.ModuleType("litellm")
    mod.acompletion = acompletion  # type: ignore[attr-defined]
    mod.completion_cost = completion_cost  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", mod)
    return seen


def _response(tool_args: Any = '{"query": "x"}') -> Any:
    call = _Obj(id="c1", function=_Obj(name="lookup-ticket", arguments=tool_args))
    msg = _Obj(content="hello", tool_calls=[call])
    return _Obj(choices=[_Obj(message=msg)], usage=_Obj(prompt_tokens=7, completion_tokens=3))


def test_litellm_maps_request_and_response(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _fake_litellm(monkeypatch, response=_response())
    model = LiteLLMModel("openai", "gpt-4o-mini")
    assert model.name == "openai/gpt-4o-mini"
    history = [
        Message("user", "hi"),
        Message("assistant", "", tool_calls=(_call(),)),
        Message("tool", "out", tool_call_id="c0"),
    ]
    tool = ToolSpec("lookup-ticket", "Looks up", {"type": "object", "properties": {}})
    out = asyncio.run(model.complete(history, timeout_s=5, tools=(tool,)))
    assert seen["model"] == "openai/gpt-4o-mini"
    assert seen["timeout"] == 5
    assert seen["tools"][0]["function"]["name"] == "lookup-ticket"
    assert seen["messages"][1]["tool_calls"][0]["function"]["arguments"] == '{"a": 1}'
    assert seen["messages"][2]["tool_call_id"] == "c0"
    assert out.text == "hello"
    assert (out.input_tokens, out.output_tokens, out.cost_usd) == (7, 3, 0.002)
    assert out.tool_calls[0].arguments == {"query": "x"}


def _call() -> Any:
    from keel_core.ports import ToolCall

    return ToolCall("c0", "lookup-ticket", {"a": 1})


@pytest.mark.parametrize("raw", ["not json", "[1]", "", {"q": 1}])
def test_litellm_tolerates_bad_tool_arguments(monkeypatch: pytest.MonkeyPatch, raw: Any) -> None:
    _fake_litellm(monkeypatch, response=_response(raw))
    out = asyncio.run(LiteLLMModel("openai", "m").complete([Message("user", "x")], timeout_s=1))
    assert out.tool_calls[0].arguments == ({"q": 1} if raw == {"q": 1} else {})


def test_litellm_wraps_provider_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_litellm(monkeypatch, error=RuntimeError("rate limited"))
    with pytest.raises(ModelError, match="rate limited"):
        asyncio.run(LiteLLMModel("openai", "m").complete([Message("user", "x")], timeout_s=1))


def test_litellm_lets_timeouts_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_litellm(monkeypatch, error=TimeoutError())
    with pytest.raises(TimeoutError):
        asyncio.run(LiteLLMModel("openai", "m").complete([Message("user", "x")], timeout_s=1))


def test_litellm_unreadable_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_litellm(monkeypatch, response=_Obj(choices=[]))
    with pytest.raises(ModelError, match="unreadable"):
        asyncio.run(LiteLLMModel("openai", "m").complete([Message("user", "x")], timeout_s=1))


def test_litellm_cost_failure_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_litellm(monkeypatch, response=_Obj(choices=[_Obj(message=_Obj(content=None))]))

    def boom(**_: Any) -> float:
        raise ValueError("unknown model")

    sys.modules["litellm"].completion_cost = boom  # type: ignore[attr-defined]
    out = asyncio.run(LiteLLMModel("x", "y").complete([Message("user", "q")], timeout_s=1))
    assert out.cost_usd == 0.0
    assert out.text == ""


def test_litellm_missing_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "litellm", None)
    with pytest.raises(KeelError, match="keel-local\\[litellm\\]"):
        LiteLLMModel("openai", "m")
