"""Model adapters: a deterministic offline model and a LiteLLM wrapper for real providers.

The extractive model exists so evals, the quickstart and CI run with no API keys. It never
invents text: it only quotes sentences from the retrieved context.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import re
from collections.abc import Mapping, Sequence
from types import ModuleType
from typing import Any

from keel_core.errors import KeelError
from keel_core.ports import Completion, Message, ModelError, ToolCall, ToolSpec

EXTRACTIVE_NAME = "keel/extractive"
_CONTEXT_LINE = re.compile(r"^\[(\d+)\]\s+\(([^)]*)\)\s*(.*)$")
_USE_TOOL = re.compile(r"use tool ([a-z][a-z0-9-]*)", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_STOPWORD_TEXT = (
    "the a an and or of to in on for is are was were be by with at as it this that what "
    "how who when where which do does can i you we my our your from about"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())
NO_CONTEXT_ANSWER = "I do not know based on the information available to me."


def count_tokens(text: str) -> int:
    """Token count used for local accounting: whitespace-separated words."""
    return len(text.split())


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOPWORDS}


class ExtractiveModel:
    """Answers from the ``Context:`` block with the best-overlap sentences.

    Cost is always 0. If the question contains ``use tool <name>`` and that tool is offered,
    the first round asks for it; after a tool message the answer is the tool output.
    """

    name = EXTRACTIVE_NAME
    max_sentences = 2

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        timeout_s: float,
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        user_idx = max((i for i, m in enumerate(messages) if m.role == "user"), default=-1)
        content = messages[user_idx].content if user_idx >= 0 else ""
        question = content.rsplit("Question: ", 1)[1] if "Question: " in content else content
        tool_msgs = [m for m in messages[user_idx + 1 :] if m.role == "tool"]
        tool_calls: tuple[ToolCall, ...] = ()
        if tool_msgs:
            text = tool_msgs[-1].content
        else:
            wanted = _USE_TOOL.search(question)
            tool_name = wanted.group(1).lower() if wanted else ""
            if tool_name and any(t.name == tool_name for t in tools):
                call = ToolCall(id="call_1", name=tool_name, arguments={"query": question})
                tool_calls = (call,)
                text = ""
            else:
                text = self._answer(content, question)
        return Completion(
            text=text,
            input_tokens=sum(count_tokens(m.content) for m in messages),
            output_tokens=count_tokens(text),
            cost_usd=0.0,
            model=self.name,
            tool_calls=tool_calls,
        )

    def _answer(self, content: str, question: str) -> str:
        entries: list[tuple[str, str]] = []  # (marker, sentence)
        for marker, block in _context_blocks(content.split("Question: ")[0]):
            for sentence in _SENTENCE_SPLIT.split(block):
                if sentence.strip():
                    entries.append((marker, sentence.strip()))
        wanted = _terms(question)
        scored = [(len(wanted & _terms(s)), i, marker, s) for i, (marker, s) in enumerate(entries)]
        ranked = sorted((e for e in scored if e[0] > 0), key=lambda e: (-e[0], e[1]))
        best = sorted(ranked[: self.max_sentences], key=lambda e: e[1])
        if not best:
            return NO_CONTEXT_ANSWER
        return " ".join(f"{s} [{marker}]" for _, _, marker, s in best)


def _context_blocks(context: str) -> list[tuple[str, str]]:
    """Split a ``Context:`` block into (marker, text) pairs.

    A chunk may span several lines; lines that do not start a new ``[n] (ref)`` entry
    belong to the previous entry. Markdown heading lines are skipped as answer material.
    """
    blocks: list[tuple[str, list[str]]] = []
    for raw in context.splitlines():
        line = raw.strip()
        m = _CONTEXT_LINE.match(line)
        if m:
            blocks.append((m.group(1), [m.group(3)]))
        elif blocks and line and not line.startswith("#"):
            blocks[-1][1].append(line)
    return [
        (marker, "\n".join(p for p in parts if not p.startswith("#"))) for marker, parts in blocks
    ]


def _to_openai_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.input_schema) or {"type": "object", "properties": {}},
        },
    }


def _to_openai_message(message: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.role == "tool":
        out["tool_call_id"] = message.tool_call_id or ""
    if message.tool_calls:
        out["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(dict(c.arguments))},
            }
            for c in message.tool_calls
        ]
    return out


def _decode_arguments(raw: object) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except ValueError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _import_litellm() -> ModuleType:
    try:
        return importlib.import_module("litellm")
    except ImportError as exc:
        raise KeelError(
            "this spec uses a real model provider, which needs LiteLLM. "
            "Install it with `pip install keel-local[litellm]` or run with --offline."
        ) from exc


class LiteLLMModel:
    """Real providers through LiteLLM. Imported lazily so keel-local has no hard dependency."""

    def __init__(self, provider: str, name: str) -> None:
        self.name = f"{provider}/{name}"
        self._litellm = _import_litellm()

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        timeout_s: float,
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        kwargs: dict[str, Any] = {
            "model": self.name,
            "messages": [_to_openai_message(m) for m in messages],
            "timeout": timeout_s,
        }
        if tools:
            kwargs["tools"] = [_to_openai_tool(t) for t in tools]
        try:
            response = await self._litellm.acompletion(**kwargs)
        except (TimeoutError, asyncio.CancelledError):
            raise
        except Exception as exc:
            raise ModelError(f"{self.name} failed: {type(exc).__name__}: {exc}") from exc
        try:
            message = response.choices[0].message
            usage = getattr(response, "usage", None)
            calls = tuple(
                ToolCall(
                    id=str(c.id),
                    name=str(c.function.name),
                    arguments=_decode_arguments(c.function.arguments),
                )
                for c in (getattr(message, "tool_calls", None) or ())
            )
            text = getattr(message, "content", None) or ""
            in_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            out_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        except (AttributeError, IndexError, TypeError) as exc:
            raise ModelError(f"{self.name} returned an unreadable response") from exc
        return Completion(
            text=text,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=self._cost(response),
            model=self.name,
            tool_calls=calls,
        )

    def _cost(self, response: object) -> float:
        try:
            return float(self._litellm.completion_cost(completion_response=response))
        except Exception:  # cost is best effort: unknown models have no price
            return 0.0
