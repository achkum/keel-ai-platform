# Contributing to Keel

Keel is in an early design stage. Issues and discussion about the design are the most useful contribution right now.

## Development setup

You need [uv](https://docs.astral.sh/uv/) and Python 3.12 or newer.

```bash
uv sync
uv run pre-commit install
```

## Checks

Every pull request must pass the same checks as CI:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

Coverage must stay at or above 90 %.

On locked-down Windows machines the `.exe` launchers in the virtual environment can be blocked.
Run the tools as modules instead, for example `uv run python -m pytest`, `uv run python -m ruff check .`,
`uv run python -m mypy` and `uv run python -m keel_cli eval examples/hr-assistant/keel.yaml --offline`.

## Pull requests

- Keep each pull request focused on one change.
- Add or update tests with every behaviour change.
- If you change the spec format, update `examples/` and the CLI template (`packages/keel-cli/src/keel_cli/templates`) in the same pull request.
- Record significant design decisions as an ADR in `docs/adr/`.

## Conduct

This project follows the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md).
