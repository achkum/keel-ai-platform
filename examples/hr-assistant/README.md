# hr-assistant

An HR assistant over sensitive documents.

- `employee` reads `docs/policies`. `hr-partner` also reads `docs/confidential`.
- The attack suite asks employees for salary bands and open cases and expects no confidential
  source to be retrieved or cited.

```bash
uv run keel eval examples/hr-assistant/keel.yaml --offline
uv run keel dev examples/hr-assistant/keel.yaml --offline --role hr-partner \
  --ask "When do salary reviews take place?"
```
