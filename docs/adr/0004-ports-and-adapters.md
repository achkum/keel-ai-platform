# 4. Ports and adapters for every layer

Date: 2026-11-16

## Status

Accepted

## Context

Each layer has mature open-source backends, for example LiteLLM for models, pgvector for retrieval and Presidio for PII.
Keel should integrate them rather than rebuild them, without tying the core to any one of them.

## Decision

`keel_core.ports` defines one small protocol per layer. The core depends only on these protocols.
Concrete backends live in separate adapter packages. Contract tests in `keel-core` check that a minimal
adapter satisfies each protocol.

Rule of thumb: if a component is not part of the spec, the gate or the policy and trace path, integrate it.

## Consequences

Swapping a backend is a spec change, not a code change. Every adapter passes through the same policy and
tracing hooks. The protocols will grow as each layer is built, and adapters must follow.
