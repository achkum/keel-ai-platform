"""Run every declared suite and combine the results into one report."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from keel_core.runtime import Runtime
from keel_eval.load import run_load
from keel_eval.suites import run_attack, run_quality
from keel_eval.types import GateReport, SuiteResult


async def run_gate(
    runtime: Runtime,
    spec_dir: Path,
    *,
    include_load: bool = True,
    load_duration_s: float = 3.0,
    suites: frozenset[str] | None = None,
) -> GateReport:
    """Run the declared quality and attack suites (and the load suite if declared and included).

    Dataset paths in the spec are relative to ``spec_dir``. ``suites`` limits which named
    quality/attack suites run (``None`` means all).
    """
    spec = runtime.spec
    started = datetime.now(UTC)
    t0 = time.monotonic()
    results: list[SuiteResult] = []
    for q in spec.evals.quality:
        if suites is None or q.name in suites:
            results.append(await run_quality(runtime, spec_dir, q))
    for a in spec.evals.attack:
        if suites is None or a.name in suites:
            results.append(await run_attack(runtime, spec_dir, a))
    if include_load and spec.evals.load is not None:
        results.append(await run_load(runtime, spec_dir, duration_s=load_duration_s))
    return GateReport(
        app=spec.app.name,
        version=spec.app.version,
        spec_hash=runtime.spec_hash,
        passed=all(r.passed for r in results),
        suites=tuple(results),
        started_at=started.isoformat(timespec="seconds"),
        duration_s=time.monotonic() - t0,
    )
