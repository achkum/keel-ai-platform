# 5. Runtime pipeline and the provenance rule

Date: 2026-11-17

## Status

Accepted

## Context

Keel promises one policy and trace path through all layers. If each layer enforces its own rules, a gap between
layers is where an attack gets through. Agents add a second problem: text the agent reads (a document, a tool
result) can contain instructions, and a model cannot reliably tell them apart from the user's request.

## Decision

`keel_core.runtime.Runtime` is the only place where layers are combined. It calls ports in a fixed order
(see `docs/architecture.md`, "Request pipeline"). It has no knowledge of any backend.

- Policy outcomes are values, not exceptions: `Response.status` is `ok`, `blocked`, `denied`, `limited` or `error`,
  with a machine-readable `blocked_by`.
- Access is checked at three points with the same policy: asking the app, retrieving a source and calling a tool.
- Provenance uses labels. Documents carry `source:<name>` and a trust label. Tool output is always untrusted.
  A tool call is refused when untrusted content is in context, unless a human approved that tool for the request.
  Tools with `requires_approval` always need that approval.
- Everything that is not allowed fails closed: a tool in the spec without an adapter is not offered.
- The query text is traced only when `observability.log_prompts` is true.

This is a simple label-and-gate version of the ideas in CaMeL and FIDES. It does not track data flow inside the model.

## Consequences

- Attack tests are easy to write: plant an instruction in a document and check that no tool ran.
- The rule is blunt. A request that retrieved a suspicious chunk cannot call any tool without approval, even a harmless one.
  This is the safe side of the trade-off and can be refined with finer labels later.
- Adding a layer means adding a step to one function and a trace event, not a new enforcement point.
