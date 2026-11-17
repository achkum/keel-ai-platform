# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Monorepo with `keel-core` and `keel-cli` as a uv workspace.
- Typed `keel.yaml` schema (`keel/v0`) for all eight layers and the eval gate, with a secure-by-default `strict` profile.
- Spec loader with safe YAML parsing, a size limit and located error messages.
- Structural spec diff.
- Layer interfaces (ports) with contract tests.
- `keel init` and `keel diff`.
- Reference spec for the knowledge assistant use case.
- CI with ruff, mypy in strict mode and pytest.
- Request pipeline (`keel_core.runtime`): access, rate limit and budget, guardrails, RAG, cache, model fallbacks and retries, tool loop with provenance and approval checks, audit log. See ADR 0005.
- Local mode (`keel-local`): in-process adapters for all eight layers and an offline extractive model. See ADR 0006.
- Eval gate (`keel-eval`): quality, attack and load suites, `promote` with pinned releases and rollback.
- `keel dev` (one request with `--ask`, or a local FastAPI server), `keel eval`, `keel promote` (with `--list` and `--rollback`) and `keel audit`.
- `keel audit` and `keel_core.audit`: scorecard against the OWASP Top 10 for LLM Applications 2025, plus agentic checks for tools.
- `keel init` now creates a project that passes `keel eval --offline`: docs, role, quality cases and an attack suite.
- Reference apps `support-agent` and `hr-assistant`; `knowledge-assistant` now has documents, role-based quality cases and attack cases.
- CI runs the gate offline and the audit for every example.

### Changed

- The `knowledge-assistant` tool uses a local Python function instead of an MCP server, so it runs in local mode.
