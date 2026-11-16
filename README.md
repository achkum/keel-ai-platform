# Keel – AI Platform

[![CI](https://github.com/achkum/keel-ai-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/achkum/keel-ai-platform/actions/workflows/ci.yml)
![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange)
![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue)

Keel is an open-source Python platform for taking an AI application from prototype to governed production.
A developer defines the whole application in one versioned spec. No change ships until its quality, attack and load tests pass.

> **Status: pre-alpha.** Keel is a working title. The spec schema, loader, diff and layer interfaces exist.
> The runtime, the eval gate and the layer adapters are not built yet. See [What works today](#what-works-today).

## The problem

Most AI applications are built for the demo. A team connects a model to a prompt, adds retrieval or a few tools, and ships.
Security, scaling, reliability and structure are left for later.
The cost arrives after launch. Answers get worse after a change and nobody notices. Token bills and latency grow with traffic.
An agent does something it was never allowed to do. The glue code becomes too tangled to change safely.

Keel builds these concerns in from the first day.

## Five core properties

| Property | What it means in Keel |
|---|---|
| Secure | Secure by default. Untrusted content cannot trigger actions. Users reach only what their policy allows. |
| Scalable | Handles growth in traffic, tenants and cost without code changes. |
| Reliable | No silent regressions. Keeps serving when a provider fails. |
| Simple | One spec, six CLI commands and safe defaults. No security or operations expertise needed. |
| Clean architecture | The core depends only on interfaces. Each layer is a swappable adapter. |

## Three mechanisms

1. **One spec.** A single `keel.yaml` defines the whole app. It is validated, diffed in pull requests and versioned.
2. **One gate.** `keel promote` runs quality, attack and load tests. If any of them fails, the version cannot ship.
3. **One policy and trace path.** Every layer passes through the same path. Access is enforced, provenance labels are checked, budgets are applied and every step is traced.

## Eight layers

| # | Layer | Done when |
|---|---|---|
| 01 | Model | Swapping provider is a one-line spec change |
| 02 | System prompt | Every production answer links to an exact prompt version |
| 03 | RAG | Answers cite sources and respect per-user document permissions |
| 04 | Tools · MCP | A tool added to the spec is callable with tracing and access checks |
| 05 | Access | A user can never retrieve or call what their policy forbids |
| 06 | Guardrails | Each check is configurable per app and logged on every block |
| 07 | Cache + router | Routing rules and budgets are enforced and visible per request |
| 08 | Observability | Any answer can be replayed from its trace |

See [docs/architecture.md](docs/architecture.md) for the full design.

## What works today

| Piece | Status |
|---|---|
| Typed `keel.yaml` schema for all eight layers and the eval gate | Done |
| `strict` profile: default-deny access, prompt-injection checks, no prompt logging | Done |
| Spec loader with safe YAML parsing and located errors | Done |
| Structural spec diff | Done |
| Layer interfaces (ports) with contract tests | Done |
| `keel init`, `keel diff` | Done |
| `keel dev`, `keel eval`, `keel promote`, `keel audit` | Not built yet |
| Runtime, eval gate, layer adapters | Not built yet |

## Try it

You need [uv](https://docs.astral.sh/uv/) and Python 3.12 or newer.

```bash
git clone https://github.com/achkum/keel-ai-platform.git
cd keel-ai-platform
uv sync
uv run keel init my-app
uv run keel diff my-app/keel.yaml examples/knowledge-assistant/keel.yaml
```

A spec looks like this ([full example](examples/knowledge-assistant/keel.yaml)):

```yaml
keel: keel/v0
app:
  name: knowledge-assistant
  version: 0.1.0
profile: strict
model:
  provider: openai
  name: gpt-4o-mini
system_prompt:
  template: prompts/system.md
access:
  default: deny
guardrails:
  input: [prompt_injection, pii]
evals:
  quality:
    - name: faithfulness
      dataset: evals/quality.jsonl
      min_score: 0.85
```

## Repository layout

```
packages/
  keel-core/   spec schema, loader, diff, layer interfaces
  keel-cli/    the keel command
examples/      reference apps
docs/          architecture and decision records (ADRs)
```

## Build order

1. Spec and core ← *in progress*
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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Report security issues as described in [SECURITY.md](SECURITY.md).

## Licence

[Apache 2.0](LICENSE)
