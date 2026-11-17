# 6. Local mode

Date: 2026-11-17

## Status

Accepted

## Context

A developer should be able to try Keel, run the gate in CI and write attack tests without Postgres, Redis, an
identity provider or an API key. Architecture decision 4 already separates the core from backends through ports.

## Decision

The `keel-local` package implements every port in process and wires them from the spec in one composition root,
`build_runtime`:

- Retrieval reads `file://` sources and ranks chunks with BM25. Chunks that look like planted instructions are labelled untrusted.
- The policy engine reads the roles in the spec.
- Quota, cache, traces and the audit log are in memory or JSONL files in a `.keel/` folder next to the spec.
  The audit log is hash-chained so changes are detectable.
- Tools are Python functions (`python://module:function`). MCP servers are not reachable in local mode: such a tool is left out and fails closed.
- Models go through LiteLLM, imported only when used. With `--offline` every model is replaced by a built-in extractive model that answers from the retrieved text. It is deterministic, free and good enough to test access control, citations and provenance. It does not test answer quality of a real model.

The eval gate and the CLI use the same runtime that production will use. Only the adapters differ.

## Consequences

- The quickstart and CI need no secrets or services.
- A passing offline gate shows that the spec's access, guardrail and provenance settings work. Quality scores from the offline model say little about a real model, so run the gate once with the real provider before promoting.
- Production adapters (Postgres, Redis, OIDC, OpenTelemetry) are separate packages that implement the same ports.
- The dev server trusts identity from the request body. This is acceptable only on `127.0.0.1`. Real identity comes with the access layer.
