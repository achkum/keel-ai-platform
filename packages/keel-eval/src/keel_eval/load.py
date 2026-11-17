"""Open-loop load suite: requests start on a fixed schedule whether or not earlier ones finished."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from keel_core.ports import Principal
from keel_core.runtime import Request, Runtime
from keel_eval.datasets import load_quality, resolve_in
from keel_eval.suites import all_roles
from keel_eval.types import SuiteResult


def p95(values: list[float]) -> float:
    """Nearest-rank 95th percentile."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _questions(runtime: Runtime, spec_dir: Path) -> list[str]:
    quality = runtime.spec.evals.quality
    if not quality:
        return ["ping"]
    cases = load_quality(resolve_in(spec_dir, quality[0].dataset))
    return [c.question for c in cases]


async def run_load(
    runtime: Runtime,
    spec_dir: Path,
    *,
    duration_s: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> SuiteResult:
    load = runtime.spec.evals.load
    if load is None:
        raise ValueError("spec declares no load suite")
    questions = _questions(runtime, spec_dir)
    roles = all_roles(runtime.spec)
    total = max(1, math.ceil(load.requests_per_second * duration_s))
    interval = 1.0 / load.requests_per_second
    latencies: list[float] = []
    errors = 0

    async def one(n: int) -> None:
        nonlocal errors
        request = Request(Principal(f"load-{n}", roles), questions[n % len(questions)])
        began = clock()
        try:
            resp = await runtime.handle(request)
            failed = resp.status == "error"
        except Exception:
            failed = True
        latencies.append((clock() - began) * 1000.0)
        errors += int(failed)

    start = clock()
    tasks: list[asyncio.Task[None]] = []
    for n in range(total):
        wait = start + n * interval - clock()
        if wait > 0:
            await sleep(wait)
        tasks.append(asyncio.create_task(one(n)))
    await asyncio.gather(*tasks)

    observed = p95(latencies)
    limit = float(load.max_p95_latency_ms)
    return SuiteResult(
        name="load",
        kind="load",
        passed=observed <= limit and errors == 0,
        score=round(observed, 3),
        threshold=limit,
        detail=f"{total} requests at {load.requests_per_second:g}/s, {errors} errors",
    )
