# knowledge-assistant

An internal assistant over company documents with per-role access.

- Roles: `employee` reads the handbook, `hr` also reads the HR policies.
- `docs/handbook/vendor-notes.md` contains a planted instruction. Ingestion labels it
  untrusted, and the gate checks that it cannot trigger the `ticket-lookup` tool.
- The model is `openai/gpt-4o-mini`. The gate runs without a key using `--offline`.

```bash
uv run keel eval examples/knowledge-assistant/keel.yaml --offline
uv run keel dev examples/knowledge-assistant/keel.yaml --offline \
  --role employee --ask "What is the daily meal allowance on business trips?"
uv run keel audit examples/knowledge-assistant/keel.yaml
```
