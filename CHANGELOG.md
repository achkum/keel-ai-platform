# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Monorepo with `keel-core` and `keel-cli` as a uv workspace.
- Typed `keel.yaml` schema (`keel/v0`) for all eight layers and the eval gate, with a secure-by-default `strict` profile.
- Spec loader with safe YAML parsing, a size limit and located error messages.
- Structural spec diff.
- Layer interfaces (ports) with contract tests.
- `keel init` and `keel diff`. The other four commands are declared and exit with code 2.
- Reference spec for the knowledge assistant use case.
- CI with ruff, mypy in strict mode and pytest.
