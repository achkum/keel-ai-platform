# keel-core

The core of Keel: the typed `keel.yaml` schema, the spec loader, the spec diff and the layer interfaces (ports).

```python
from keel_core import load_spec

spec = load_spec("keel.yaml")
print(spec.app.name, spec.model.name)
```

`load_spec` raises `keel_core.SpecError` with one issue per problem, each with a location such as `model.timeout_s`.

Status: pre-alpha. The spec format (`keel/v0`) will change before v1.0.
