# keel-eval

The Keel gate. It runs the quality, attack and load suites declared in `keel.yaml` and
promotes a pinned version only if every suite passes.

- `run_gate(runtime, spec_dir)` runs the suites and returns a `GateReport`.
- `promote(spec_path)` builds the runtime, runs the gate, writes the report to
  `<state>/reports/` and, on a pass, records `<state>/releases/<version>.json` and `CURRENT`.
  A version that was promoted with a different spec is refused: bump `app.version`.
- `list_releases(state_dir)` and `rollback(state_dir, version)` manage what is current.
- `trace_to_case(events)` turns a recorded request into an attack case.

Datasets are JSONL files under the spec directory (max 10 MB). Quality cases take
`question`, `role`/`roles`, `expected_sources`, `must_include`. Attack cases take `input`,
`expect` (`refuse`, `deny`, `no_leak`, `no_tool`), `role`/`roles`, `tool`, `forbidden`.
The load suite is open-loop: requests start on schedule, and p95 latency plus a zero
error rate decide the result.
