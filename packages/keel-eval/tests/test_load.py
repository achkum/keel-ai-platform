from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from keel_eval.load import p95, run_load

if TYPE_CHECKING:
    from conftest import Kit


def _run(kit: Kit, tmp_path: Path, *, delay_s: float, handler=None, duration: float = 2.0, **kw):  # type: ignore[no-untyped-def]
    path = kit.write_app(tmp_path, **kw)
    clock = kit.clock()
    rt = kit.make_runtime(path, clock=clock, delay_s=delay_s)
    if handler is not None:
        rt.handler = handler
    res = asyncio.run(run_load(rt, tmp_path, duration_s=duration, clock=clock, sleep=clock.sleep))
    return res, rt, clock


def test_p95_nearest_rank() -> None:
    assert p95([5.0]) == 5.0
    assert p95([float(i) for i in range(1, 21)]) == 19.0  # ceil(0.95*20) = 19th value
    assert p95([3.0, 1.0, 2.0]) == 3.0


def test_load_passes_and_paces_requests(kit: Kit, tmp_path: Path) -> None:
    res, rt, clock = _run(kit, tmp_path, delay_s=0.05, load=(10.0, 100))
    assert res.passed
    assert res.kind == "load"
    assert res.score == pytest.approx(50.0)
    assert res.threshold == 100.0
    assert len(rt.seen) == 20  # 10 rps * 2 s
    assert [r.principal.user_id for r in rt.seen][:3] == ["load-0", "load-1", "load-2"]
    assert rt.seen[0].principal.roles == frozenset({"employee", "hr"})
    assert clock.t >= 1.9  # open loop: scheduled over the whole duration
    assert "0 errors" in res.detail


def test_load_fails_on_latency(kit: Kit, tmp_path: Path) -> None:
    res, _, _ = _run(kit, tmp_path, delay_s=0.5, load=(10.0, 100))
    assert not res.passed
    assert res.score == pytest.approx(500.0)


def test_load_fails_on_any_error(kit: Kit, tmp_path: Path) -> None:
    def handler(request):  # type: ignore[no-untyped-def]
        return kit.reply("error" if request.principal.user_id == "load-3" else "ok")

    res, _, _ = _run(kit, tmp_path, delay_s=0.0, handler=handler)
    assert not res.passed
    assert "1 errors" in res.detail


def test_load_counts_exceptions_as_errors(kit: Kit, tmp_path: Path) -> None:
    def handler(request):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    res, _, _ = _run(kit, tmp_path, delay_s=0.0, handler=handler, duration=0.5)
    assert not res.passed


def test_load_questions_and_ping_fallback(kit: Kit, tmp_path: Path) -> None:
    rows = [{"question": "first"}, {"question": "second"}]
    _, rt, _ = _run(kit, tmp_path / "a", delay_s=0.0, quality=rows, duration=0.4)
    assert [r.query for r in rt.seen] == ["first", "second", "first", "second"]
    _, rt2, _ = _run(kit, tmp_path / "b", delay_s=0.0, duration=0.1, with_quality=False)
    assert {r.query for r in rt2.seen} == {"ping"}
    assert len(rt2.seen) == 1


def test_load_requires_declared_suite(kit: Kit, tmp_path: Path) -> None:
    path = kit.write_app(tmp_path, load=None)
    rt = kit.make_runtime(path)
    with pytest.raises(ValueError, match="no load suite"):
        asyncio.run(run_load(rt, tmp_path, duration_s=1.0))
