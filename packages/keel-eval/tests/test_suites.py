from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from keel_core.runtime import Request, Response
from keel_eval import GateError, SuiteResult
from keel_eval.suites import run_attack, run_quality

if TYPE_CHECKING:
    from conftest import Kit


def _quality(kit: Kit, tmp_path: Path, rows: list[Any], handler: Any, **kw: Any) -> SuiteResult:
    path = kit.write_app(tmp_path, quality=rows, load=None, **kw)
    rt = kit.make_runtime(path, handler=handler)
    return asyncio.run(run_quality(rt, tmp_path, rt.spec.evals.quality[0]))


def _attack(
    kit: Kit, tmp_path: Path, rows: list[Any], handler: Any, **kw: Any
) -> tuple[SuiteResult, Any]:
    path = kit.write_app(tmp_path, attack=rows, load=None, **kw)
    rt = kit.make_runtime(path, handler=handler)
    return asyncio.run(run_attack(rt, tmp_path, rt.spec.evals.attack[0])), rt


# ---------------------------------------------------------------- quality


def test_quality_perfect(kit: Kit, tmp_path: Path) -> None:
    rows = [{"question": "q", "expected_sources": ["handbook"], "must_include": ["ANSWER"]}]
    res = _quality(
        kit, tmp_path, rows, lambda r: kit.reply(text="the answer", sources=["handbook"])
    )
    assert res.passed
    assert res.score == 1.0
    assert res.cases[0].trace_id == "t-1"


def test_quality_partial_score_and_threshold(kit: Kit, tmp_path: Path) -> None:
    rows = [{"question": "q", "expected_sources": ["handbook", "hr-policies"]}]

    def handler(_: Request) -> Response:
        return kit.reply(sources=["handbook"])

    res = _quality(kit, tmp_path, rows, handler, min_score=0.5)
    assert res.score == 0.5
    assert res.passed  # meets min_score even though the case itself is not perfect
    assert not res.cases[0].passed
    assert "hr-policies" in res.cases[0].detail
    failing = _quality(kit, tmp_path / "b", rows, handler, min_score=0.6)
    assert not failing.passed


def test_quality_mean_of_checks_and_missing_text(kit: Kit, tmp_path: Path) -> None:
    rows = [{"question": "q", "expected_sources": ["handbook"], "must_include": ["a", "b"]}]
    res = _quality(kit, tmp_path, rows, lambda r: kit.reply(text="a only", sources=["handbook"]))
    assert res.score == pytest.approx((1.0 + 0.5) / 2)
    assert "answer lacks" in res.cases[0].detail


def test_quality_non_ok_scores_zero_and_no_checks_scores_one(kit: Kit, tmp_path: Path) -> None:
    rows = [{"question": "bad"}, {"question": "fine"}]

    def handler(r: Request) -> Response:
        if r.query == "bad":
            return kit.reply("error", blocked_by="model")
        return kit.reply()

    res = _quality(kit, tmp_path, rows, handler, min_score=0.5)
    assert [c.score for c in res.cases] == [0.0, 1.0]
    assert "status=error" in res.cases[0].detail
    assert res.passed


def test_principal_defaults_and_overrides(kit: Kit, tmp_path: Path) -> None:
    rows = [{"question": "a"}, {"question": "b", "role": "hr"}, {"question": "c", "roles": []}]
    path = kit.write_app(tmp_path, quality=rows, load=None)
    rt = kit.make_runtime(path, handler=lambda r: kit.reply())
    asyncio.run(run_quality(rt, tmp_path, rt.spec.evals.quality[0]))
    by_query = {r.query: r.principal for r in rt.seen}
    assert by_query["a"].user_id == "eval"
    assert by_query["a"].roles == frozenset({"employee", "hr"})
    assert by_query["b"].roles == frozenset({"hr"})
    assert by_query["c"].roles == frozenset()


def test_cases_run_concurrently_with_cap_of_eight(kit: Kit, tmp_path: Path) -> None:
    rows = [{"question": f"q{i}"} for i in range(30)]
    path = kit.write_app(tmp_path, quality=rows, load=None)
    rt = kit.make_runtime(path, handler=lambda r: kit.reply(), pause=True)
    asyncio.run(run_quality(rt, tmp_path, rt.spec.evals.quality[0]))
    assert rt.max_inflight == 8


def test_dataset_path_traversal_rejected(kit: Kit, tmp_path: Path) -> None:
    path = kit.write_app(tmp_path / "app", load=None)
    (tmp_path / "outside.jsonl").write_text('{"question": "x"}\n', encoding="utf-8")
    text = path.read_text(encoding="utf-8").replace("evals/quality.jsonl", "../outside.jsonl")
    path.write_text(text, encoding="utf-8")
    rt = kit.make_runtime(path)
    with pytest.raises(GateError, match="outside the spec directory"):
        asyncio.run(run_quality(rt, path.parent, rt.spec.evals.quality[0]))


# ---------------------------------------------------------------- attack


def test_refuse(kit: Kit, tmp_path: Path) -> None:
    rows = [{"input": "ignore it", "expect": "refuse"}, {"input": "hello", "expect": "refuse"}]
    res, _ = _attack(
        kit,
        tmp_path,
        rows,
        lambda r: kit.reply("blocked" if "ignore" in r.query else "ok"),
        max_failures=1,
    )
    assert [c.passed for c in res.cases] == [True, False]
    assert res.score == 1.0
    assert res.threshold == 1.0
    assert res.passed  # one failure allowed
    strict, _ = _attack(
        kit, tmp_path / "b", rows, lambda r: kit.reply("blocked" if "ignore" in r.query else "ok")
    )
    assert not strict.passed


@pytest.mark.parametrize("status", ["blocked", "denied", "limited"])
def test_refuse_accepts_each_refusal_status(kit: Kit, tmp_path: Path, status: str) -> None:
    res, _ = _attack(
        kit, tmp_path, [{"input": "x", "expect": "refuse"}], lambda r: kit.reply(status)
    )
    assert res.passed


def test_refuse_fails_on_error_status(kit: Kit, tmp_path: Path) -> None:
    res, _ = _attack(
        kit, tmp_path, [{"input": "x", "expect": "refuse"}], lambda r: kit.reply("error")
    )
    assert not res.passed


def test_deny_source_and_tool(kit: Kit, tmp_path: Path) -> None:
    rows = [
        {"input": "a", "role": "employee", "expect": "deny"},
        {"input": "b", "role": "hr", "expect": "deny"},
        {"input": "c", "role": "employee", "expect": "deny"},
    ]

    def handler(r: Request) -> Response:
        if r.query == "a":
            return kit.reply(sources=["hr-policies"])  # employee may not see hr-policies
        if r.query == "b":
            return kit.reply(sources=["hr-policies"], retrieved=["handbook"], tools=["refund"])
        return kit.reply(tools=["refund"])  # employee may not call refund

    res, _ = _attack(kit, tmp_path, rows, handler, max_failures=5)
    assert [c.passed for c in res.cases] == [False, True, False]
    assert "hr-policies" in res.cases[0].detail
    assert "refund" in res.cases[2].detail


def test_deny_with_default_allow_permits_everything(kit: Kit, tmp_path: Path) -> None:
    rows = [{"input": "a", "role": "employee", "expect": "deny"}]
    res, _ = _attack(
        kit,
        tmp_path,
        rows,
        lambda r: kit.reply(sources=["hr-policies"], tools=["refund"]),
        access_default="allow",
    )
    assert res.passed


def test_no_leak_uses_rendered_prompt_lines_by_default(kit: Kit, tmp_path: Path) -> None:
    rows = [
        {"input": "a", "expect": "no_leak"},
        {"input": "b", "expect": "no_leak"},
        {"input": "c", "expect": "no_leak"},
    ]

    def handler(r: Request) -> Response:
        return kit.reply(
            text={
                "a": "I was told: you are the example assistant.",  # rendered, case-insensitive
                "b": "Never reveal the internal escalation procedure.",
                "c": "short",  # short prompt lines are not forbidden
            }[r.query]
        )

    res, _ = _attack(kit, tmp_path, rows, handler, max_failures=9)
    assert [c.passed for c in res.cases] == [False, False, True]


def test_no_leak_explicit_forbidden(kit: Kit, tmp_path: Path) -> None:
    rows = [{"input": "a", "expect": "no_leak", "forbidden": ["SECRET"]}]
    res, _ = _attack(kit, tmp_path, rows, lambda r: kit.reply(text="the secret is 42"))
    assert not res.passed
    ok, _ = _attack(kit, tmp_path / "b", rows, lambda r: kit.reply(text="nothing"))
    assert ok.passed


def test_no_leak_missing_template(kit: Kit, tmp_path: Path) -> None:
    path = kit.write_app(tmp_path, attack=[{"input": "a", "expect": "no_leak"}], load=None)
    (tmp_path / "prompts" / "system.md").unlink()
    rt = kit.make_runtime(path)
    with pytest.raises(GateError, match="cannot read system prompt"):
        asyncio.run(run_attack(rt, tmp_path, rt.spec.evals.attack[0]))


def test_no_tool(kit: Kit, tmp_path: Path) -> None:
    rows = [
        {"input": "a", "expect": "no_tool", "tool": "refund"},
        {"input": "b", "expect": "no_tool", "tool": "refund"},
        {"input": "c", "expect": "no_tool"},
        {"input": "d", "expect": "no_tool"},
    ]
    called = {"a": ["lookup"], "b": ["refund"], "c": ["lookup"], "d": []}
    res, _ = _attack(
        kit, tmp_path, rows, lambda r: kit.reply(tools=called[r.query]), max_failures=9
    )
    assert [c.passed for c in res.cases] == [True, False, False, True]
