# 3. The spec is the single source of truth

Date: 2026-11-16

## Status

Accepted. The format itself is provisional (`keel/v0`).

## Context

Configuration for LLM applications is usually spread across code, environment variables and vendor dashboards.
Nobody can say exactly what runs in production, and security settings are easy to miss.

## Decision

One `keel.yaml` describes the whole application across the eight layers plus its eval suites.

- The schema is typed with Pydantic v2 and rejects unknown keys, so typos fail loudly.
- A loaded spec is immutable.
- Cross-references are checked at load time, for example a role may only grant tools and sources that are declared.
- The `strict` profile is the default. It requires default-deny access, prompt-injection checks on input,
  no prompt logging, and an attack suite for any app with tools.
- YAML is parsed with `safe_load` and spec files are capped in size.

## Consequences

What is not declared cannot run, which makes the spec both the simplicity boundary and the security boundary.
The format will change before v1.0. Every change to it must update `examples/` and the CLI template, which CI validates.
