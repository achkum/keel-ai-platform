# Keel architecture

**Status: in design.** Names and details may change.

## Overview

The spec feeds a control plane. The control plane compiles the spec, runs the gate on quality, attack and load tests, and deploys a pinned version to the runtime.
In the runtime each request passes through the declared layers in order.
Every layer runs through the same policy and trace path. Failing traces flow back into the gate as new eval cases.

```mermaid
flowchart TB
    Spec["1 · One spec (keel.yaml)<br/>all 8 layers, access rules,<br/>budgets and eval suites"]
    Gate["2 · One gate in the control plane<br/>keel promote: quality, attack and load tests must pass<br/>then a pinned version deploys · rollback by version"]
    Spec --> Gate
    Gate -->|deploys| Access

    subgraph Runtime["Runtime: each request passes the declared layers in order"]
        Access[Access] --> InG[Input guardrails] --> CR[Cache + router] --> SP[System prompt] --> RAG[RAG retrieval] --> Model[Model]
        Model <-->|tool calls| Tools[Tools · MCP]
        Model --> OutG[Output guardrails] --> Resp[Response]
    end

    Path["3 · One policy and trace path<br/>provenance labels checked · access enforced<br/>budgets and rate limits applied · every step traced"]
    Runtime -.-> Path
    Path -.->|failing traces become eval cases| Gate
```

## Five properties, three mechanisms

| Property | Delivered by | Checked by |
|---|---|---|
| Secure | Provenance policy, one policy engine at retrieval and tool-call time, guardrails, tamper-evident audit log | Attack suites in the gate |
| Scalable | Stateless async runtime, semantic cache, cost- and latency-based routing, per-tenant budgets and rate limits | Load tests |
| Reliable | Eval gate, pinned spec versions, rollback, fallbacks, retries, timeouts, replay from traces | Quality suites and fault-injection tests |
| Simple | One spec, six CLI commands, secure defaults, `keel audit` scorecard | Quickstart under 10 minutes |
| Clean architecture | Core depends only on interfaces; each layer is a port with adapters | Architecture tests in CI |

The mechanisms reinforce each other:

- The spec is both the simplicity boundary and the security boundary. What is not declared cannot run.
- The gate proves security, reliability and scale together. Attack, quality and load tests block the same promotion.
- Clean interfaces make security and scaling uniform. Whatever backend a layer uses, it passes through the same policy and tracing hooks.

## Provenance policy

Every piece of data the agent reads carries a label for its source and sensitivity.
One policy decides which labels may reach which action or output.
The idea comes from CaMeL (Google DeepMind, 2025) and FIDES (Microsoft, 2025). Keel implements a simple label-and-gate version.

## Request pipeline

`keel_core.runtime.Runtime.handle` runs every request through the same steps. Each step records a trace event with the
same trace id. Policy outcomes (blocked, denied, limited) come back as a status, never as an exception.

1. **Request.** The trace id is the caller's request id or a new one. The query is traced only if `observability.log_prompts` is true.
2. **Access.** The policy must allow `ask` on the app. Otherwise the status is `denied` (`access:app`).
3. **Rate limit and budget.** Over the per-minute limit or the daily budget gives `limited` (`rate_limit`, `budget`). Both are keyed by tenant, or by user when there is no tenant. The cost of every model call is added to the budget.
4. **Input guardrails**, in spec order. A failed check gives `blocked` (`guardrail:<name>`). A check that redacts passes the redacted text on.
5. **System prompt.** The template is rendered and gets a version, which is returned with the answer.
6. **RAG.** Only sources the principal may `retrieve` are searched. Documents from other sources are dropped and traced. The runtime labels each document with `source:<name>`.
7. **Cache.** The key covers the spec hash, prompt version, query and the retrieved document refs. The cache is scoped per principal, so one user never gets another user's cached answer.
8. **Model and tools.** Models are tried in order (primary, then fallbacks), each with retries and a timeout. Only tools the principal may `call` and that are available are offered. Each tool call is checked for provenance and approval (below). The loop stops after `max_tool_steps` rounds with `blocked` (`step_limit`).
9. **Output guardrails.** Same rules as input.
10. **Citations.** Documents whose `[n]` marker appears in the answer. If the answer has no markers, all documents in context.
11. **Audit.** One entry per request: trace id, spec hash, user, tenant, status, blocked-by, model, prompt version, cost, sources and tools.

### Provenance rule for tools

Every document and tool output has labels. Text from a suspicious chunk (it looks like an instruction planted in a document) is labelled `trust:untrusted`. Output of any tool is always `trust:untrusted`.
If any untrusted label is in the context, a tool call is stopped with `blocked` (`provenance:tool:<name>`) unless a human approved that tool for this request.
A tool with `requires_approval` is always stopped (`approval:tool:<name>`) without that approval.
So content the agent reads can never start an action on its own. The attack suites in the gate check this with planted-instruction documents.

## Layer scope

| # | Layer | Scope |
|---|---|---|
| 01 | Model | Provider-agnostic calls, streaming, structured output, fallbacks, retries, timeouts, cost accounting |
| 02 | System prompt | Versioned templates, variables, few-shot sets, prompt registry |
| 03 | RAG | Ingestion, chunking, embeddings, hybrid search, reranking, citations |
| 04 | Tools · MCP | MCP client and server, tool registry, sandboxed execution, agent loop with step limits |
| 05 | Access | OIDC, API keys, RBAC and attribute policies, multi-tenancy |
| 06 | Guardrails | PII, prompt injection, toxicity, topic filters, human approval, provenance policy |
| 07 | Cache + router | Exact and semantic cache, cost and latency routing, rate limits, budgets |
| 08 | Observability | OpenTelemetry traces, logs, metrics, eval runner, regression reports |

Security controls are designed against the OWASP Top 10 for LLM Applications 2026 and the Top 10 for Agentic Applications 2026.

## Build or integrate

Build the spec compiler, CLI, control plane, eval gate, policy engine, audit log and a thin provenance policy.
Integrate mature components behind Keel interfaces: LiteLLM for model calls, pgvector or Qdrant for vectors, the MCP Python SDK, Presidio for PII, Ragas or DeepEval for metrics, OPA or Casbin as rule evaluator, and OpenTelemetry for tracing.

Rule of thumb: if a component is not part of the spec, the gate or the policy and trace path, integrate it.

## Build order

1. Spec and core
2. Observability
3. Model and system prompt
4. Eval runner and gate
5. RAG
6. Tools · MCP
7. Access
8. Guardrails
9. Cache and router
10. Console, docs and hardening

Observability and the gate come early because every later layer is checked by them.

## Open questions

- Final project name
- Serve all three audiences at v1.0, or lead with one?
- Web console in Next.js, or Python-only with HTMX?
- Self-hosted only, or also a one-command local mode?
