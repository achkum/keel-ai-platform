# Keel – AI Platform

[![CI](https://github.com/achkum/keel-ai-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/achkum/keel-ai-platform/actions/workflows/ci.yml)
![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange)
![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue)

Keel is an open-source Python platform for taking an AI application from prototype to governed production.
A developer defines the whole application in one versioned spec. No change ships until its quality, attack and load tests pass.

> **Status: pre-alpha.** Keel is a working title. The spec, the runtime pipeline, local-mode adapters for all
> eight layers, the eval gate and all six CLI commands work on one machine with no external services.
> Production backends (Postgres, Redis, OIDC, OpenTelemetry export) are not built yet. See [What works today](#what-works-today).

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
| Typed `keel.yaml` schema for all eight layers and the eval gate; `strict` profile | Done |
| Spec loader with safe YAML parsing and located errors; structural spec diff | Done |
| Layer interfaces (ports) with contract tests | Done |
| Request pipeline: access, rate limit and budget, guardrails, RAG, cache, tools with provenance and approval, audit | Done |
| Local mode: in-process adapters for all eight layers (BM25 RAG, role policy, exact cache, JSONL traces and audit log) | Done |
| Offline extractive model, so evals and the quickstart need no API key | Done |
| Eval gate: quality, attack and load suites; `promote` pins a release, `--rollback` restores one | Done |
| `keel init`, `dev`, `eval`, `promote`, `diff`, `audit` | Done |
| `keel audit` scorecard against the OWASP Top 10 for LLM Applications 2025 | Done |
| Real model providers through LiteLLM (optional extra, needs an API key) | Done, untested against live APIs |
| Semantic cache, MCP servers, OIDC login, Postgres, Redis, OpenTelemetry export | Not built yet |

## Try it

You need [uv](https://docs.astral.sh/uv/) and Python 3.12 or newer. No API key is needed.

```bash
git clone https://github.com/achkum/keel-ai-platform.git
cd keel-ai-platform
uv sync
uv run keel init my-app
uv run keel eval my-app/keel.yaml --offline        # quality and attack suites
uv run keel dev my-app/keel.yaml --offline --role reader --ask "When is support available?"
uv run keel promote my-app/keel.yaml --offline     # full gate, then pins release 0.1.0
uv run keel audit my-app/keel.yaml                 # OWASP LLM Top 10 scorecard
```

Run the reference apps the same way:

```bash
uv run keel eval examples/knowledge-assistant/keel.yaml --offline
uv run keel eval examples/support-agent/keel.yaml --offline
uv run keel eval examples/hr-assistant/keel.yaml --offline
```

Exit codes: `0` success, `1` a check failed or the spec is invalid, `3` a `dev --ask` request was not
answered, `4` the gate could not run (for example a missing dataset).
`keel dev` without `--ask` serves a local HTTP API on `127.0.0.1`. It trusts the identity in the request
body, so use it for development only.

State (traces, audit log, releases, reports) is written to a `.keel/` folder next to the spec.

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
  keel-core/   spec schema, loader, diff, layer interfaces, request pipeline, audit
  keel-local/  in-process adapters for all eight layers (local mode)
  keel-eval/   eval gate, promote and rollback
  keel-cli/    the keel command and the dev server
examples/      reference apps (knowledge-assistant, support-agent, hr-assistant)
docs/          architecture and decision records (ADRs)
```

## Build order

1. Spec and core (done)
2. Request pipeline and local mode (done)
3. Eval runner and gate (done)
4. Production backends: Postgres, Redis, OIDC, OpenTelemetry, MCP, semantic cache ← *next*
5. Console, docs and hardening

Observability and the gate come early because every later layer is checked by them.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Report security issues as described in [SECURITY.md](SECURITY.md).

## Licence

[Apache 2.0](LICENSE)
