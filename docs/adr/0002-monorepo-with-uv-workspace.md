# 2. One monorepo with a uv workspace

Date: 2026-11-16

## Status

Accepted

## Context

Keel ships several packages: `keel-core`, `keel-cli`, later a console and one adapter package per layer backend.
They change together, especially while the spec format is still moving.

## Decision

Keep all packages in one repository under `packages/`, managed as a uv workspace with one lock file.
Each package has its own `pyproject.toml` and can be published to PyPI on its own.
Lint, type check and tests run from the root for every package.

## Consequences

A change to the spec and the CLI that uses it lands in one pull request.
CI runs everything on every change, which will need splitting once the repository grows.
