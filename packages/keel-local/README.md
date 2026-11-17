# keel-local

In-process adapters for every layer, so a Keel app runs on one machine with no Postgres, Redis or API keys.

`keel_local.build_runtime(spec_path, offline=False)` reads `keel.yaml` and wires:

| Layer | Adapter | Module |
|---|---|---|
| Model | `ExtractiveModel` (offline, deterministic), `LiteLLMModel` (needs `keel-local[litellm]`) | `models` |
| System prompt | `FilePromptRegistry`, content-hash versions, secret check | `prompts` |
| RAG | `LocalRetriever`: `file://` sources, paragraph chunks, BM25 | `retrieval` |
| Tools | `PythonTool` for `python://module:function`, with `tools.lock` | `tools` |
| Access | `RbacPolicy` from `access` | `policy` |
| Guardrails | PII, prompt injection, toxicity; topic and schema are pass-through for now | `guardrails` |
| Cache and router | `InMemoryCache` (TTL, LRU, per user), `InMemoryQuota` | `cache`, `quota` |
| Observability | JSONL and console tracers, hash-chained audit log | `observability` |

State lives in `<spec dir>/.keel/`: `traces.jsonl`, `audit.jsonl`, `tools.lock`.

Limits of local mode:

- `cache: semantic` uses the same exact-match cache.
- `exporter: otlp` writes `traces.jsonl`; real OTLP export is a later adapter.
- `mcp://` tools are not reachable and are left out (fail closed) with a warning.
- Guardrails are heuristics, not classifiers.
