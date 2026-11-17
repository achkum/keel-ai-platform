"""The ``keel`` command.

Six commands: init, dev, eval, promote, diff, audit.

Exit codes: 0 success, 1 a failed check or an invalid spec, 3 a ``dev --ask`` request that was
not answered, 4 the gate or runtime could not run at all (missing dataset, missing resource).
"""

from __future__ import annotations

import asyncio
import json
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import typer

from keel_core import KeelError, SpecError, __version__, diff_specs, load_spec
from keel_core.audit import audit_spec
from keel_core.ports import Principal
from keel_core.runtime import Request, Runtime
from keel_eval import GateError, list_releases, rollback, run_gate
from keel_eval import promote as promote_release
from keel_local import build_runtime, state_dir_for

app = typer.Typer(
    name="keel",
    help="Keel: one spec, one gate, one policy and trace path for LLM applications.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

EXIT_INVALID_SPEC = 1
EXIT_REQUEST_FAILED = 3
EXIT_CANNOT_RUN = 4

SpecPath = Annotated[Path, typer.Argument(help="Path to a keel.yaml spec.", show_default=False)]
OfflineOpt = Annotated[
    bool,
    typer.Option("--offline", help="Use the built-in extractive model. No API keys needed."),
]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"keel {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """Keel command-line interface."""


def _fail(message: str, code: int) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code=code)


def _runtime(spec: Path, *, offline: bool) -> Runtime:
    """Build the local runtime, turning Keel errors into exit codes."""
    try:
        return build_runtime(spec, offline=offline)
    except SpecError as exc:
        raise _fail(str(exc), EXIT_INVALID_SPEC) from None
    except KeelError as exc:
        raise _fail(f"error: {exc}", EXIT_CANNOT_RUN) from None


# ---------------------------------------------------------------- init

_STARTER_FILES: tuple[tuple[str, str], ...] = (
    ("system.md", "prompts/system.md"),
    ("handbook.md", "docs/handbook.md"),
    ("quality.jsonl", "evals/quality.jsonl"),
    ("attack.jsonl", "evals/attack.jsonl"),
)


@app.command()
def init(
    directory: Annotated[
        Path, typer.Argument(help="Where to create the project.", file_okay=False)
    ] = Path(),
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite an existing keel.yaml.")
    ] = False,
) -> None:
    """Create a starter project: a spec, a prompt, a small docs folder and eval cases.

    The project passes `keel eval keel.yaml --offline` as created.
    """
    spec_path = directory / "keel.yaml"
    if spec_path.exists() and not force:
        typer.echo(f"{spec_path} already exists. Use --force to overwrite it.", err=True)
        raise typer.Exit(code=1)

    templates = files("keel_cli") / "templates"
    directory.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(templates.joinpath("keel.yaml").read_text(encoding="utf-8"), "utf-8")

    # Everything except the spec is written only when missing, so --force never loses your work.
    for template, target in _STARTER_FILES:
        path = directory / target
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(templates.joinpath(template).read_text(encoding="utf-8"), "utf-8")

    typer.echo(f"Created {spec_path}")
    typer.echo(f"Next: keel eval {spec_path} --offline")


# ---------------------------------------------------------------- diff


@app.command()
def diff(
    old: SpecPath,
    new: SpecPath,
    exit_code: Annotated[
        bool, typer.Option("--exit-code", help="Exit with 1 if the specs differ.")
    ] = False,
) -> None:
    """Show which settings changed between two spec versions."""
    try:
        changes = diff_specs(load_spec(old), load_spec(new))
    except SpecError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=EXIT_INVALID_SPEC) from None

    if not changes:
        typer.echo("No changes.")
        return
    for change in changes:
        typer.echo(str(change))
    if exit_code:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------- dev


@app.command()
def dev(
    spec: SpecPath,
    offline: OfflineOpt = False,
    host: Annotated[str, typer.Option(help="Interface to bind. Keep the default.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8000,
    ask: Annotated[
        str | None, typer.Option("--ask", help="Run one request, print the result and exit.")
    ] = None,
    user: Annotated[str, typer.Option("--user", help="User id for --ask.")] = "dev",
    role: Annotated[
        list[str] | None, typer.Option("--role", help="Role for --ask. Repeatable.")
    ] = None,
    tenant: Annotated[str | None, typer.Option("--tenant", help="Tenant for --ask.")] = None,
    approve: Annotated[
        list[str] | None,
        typer.Option("--approve", help="Approve a tool that needs approval. Repeatable."),
    ] = None,
) -> None:
    """Run the app locally with tracing, in process and with no external services.

    With --ask, send one request as the given user and roles and print the answer
    (exit 3 if it was not answered). Without it, serve the HTTP API (POST /v1/ask,
    GET /healthz, GET /v1/spec). The API trusts the identity in the request body, so it
    is for development only and binds to 127.0.0.1 by default.
    """
    runtime = _runtime(spec, offline=offline)
    if ask is None:
        import uvicorn  # imported here so the other commands start fast

        from keel_cli.server import create_app

        typer.echo(f"Serving {runtime.spec.app.name} on http://{host}:{port} (dev identity)")
        uvicorn.run(create_app(runtime), host=host, port=port)
        return

    request = Request(
        principal=Principal(user_id=user, roles=frozenset(role or ()), tenant=tenant),
        query=ask,
        approved_tools=frozenset(approve or ()),
    )
    response = asyncio.run(runtime.handle(request))
    typer.echo(f"status:         {response.status}")
    if response.blocked_by:
        typer.echo(f"blocked by:     {response.blocked_by}")
    typer.echo(f"answer:         {response.text}")
    if response.citations:
        typer.echo("citations:")
        for citation in response.citations:
            typer.echo(f"  - {citation.source}: {citation.ref}")
    typer.echo(f"trace id:       {response.trace_id}")
    typer.echo(f"model:          {response.model or '-'}")
    typer.echo(f"prompt version: {response.prompt_version or '-'}")
    typer.echo(f"cost (USD):     {response.cost_usd:.6f}")
    if response.status != "ok":
        raise typer.Exit(code=EXIT_REQUEST_FAILED)


# ---------------------------------------------------------------- eval


@app.command(name="eval")
def eval_(
    spec: SpecPath,
    offline: OfflineOpt = False,
    suite: Annotated[
        list[str] | None, typer.Option("--suite", help="Run only this suite. Repeatable.")
    ] = None,
    load: Annotated[
        bool, typer.Option("--load/--no-load", help="Also run the load suite.")
    ] = False,
    load_duration: Annotated[
        float, typer.Option("--load-duration", help="Seconds to run the load suite.")
    ] = 3.0,
    json_path: Annotated[
        Path | None, typer.Option("--json", help="Write the report as JSON to this file.")
    ] = None,
    markdown_path: Annotated[
        Path | None, typer.Option("--markdown", help="Write the report as Markdown to this file.")
    ] = None,
) -> None:
    """Run the quality and attack suites declared in the spec.

    Exit codes: 0 all suites passed, 1 at least one failed, 4 the gate could not run.
    """
    runtime = _runtime(spec, offline=offline)
    try:
        report = asyncio.run(
            run_gate(
                runtime,
                spec.resolve().parent,
                include_load=load,
                load_duration_s=load_duration,
                suites=frozenset(suite) if suite else None,
            )
        )
    except (GateError, KeelError) as exc:
        raise _fail(f"error: {exc}", EXIT_CANNOT_RUN) from None

    markdown = report.to_markdown()
    typer.echo(markdown)
    if json_path is not None:
        json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    if markdown_path is not None:
        markdown_path.write_text(markdown, encoding="utf-8")
    if not report.passed:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------- promote


@app.command()
def promote(
    spec: SpecPath,
    offline: OfflineOpt = False,
    load_duration: Annotated[
        float, typer.Option("--load-duration", help="Seconds to run the load suite.")
    ] = 3.0,
    list_: Annotated[bool, typer.Option("--list", help="List promoted releases and exit.")] = False,
    rollback_to: Annotated[
        str | None,
        typer.Option("--rollback", help="Make this earlier promoted VERSION current again."),
    ] = None,
) -> None:
    """Run the full gate, including load, and pin the spec as a release only if it passes.

    Exit codes: 0 promoted (or --list/--rollback done), 1 refused, 4 the gate could not run.
    """
    try:
        load_spec(spec)
    except SpecError as exc:
        raise _fail(str(exc), EXIT_INVALID_SPEC) from None
    state_dir = state_dir_for(spec)
    try:
        if list_:
            releases = list_releases(state_dir)
            if not releases:
                typer.echo("No releases yet.")
            for release in releases:
                marker = "*" if release.current else " "
                typer.echo(
                    f"{marker} {release.version}  {release.spec_hash[:12]}  {release.promoted_at}"
                )
            return
        if rollback_to is not None:
            release = rollback(state_dir, rollback_to)
            typer.echo(f"Rolled back: {release.version} is current ({release.spec_hash[:12]}).")
            return
        result = promote_release(spec, offline=offline, load_duration_s=load_duration)
    except (GateError, KeelError) as exc:
        raise _fail(f"error: {exc}", EXIT_CANNOT_RUN) from None

    typer.echo(result.report.to_markdown())
    typer.echo(result.message)
    if not result.promoted:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------- audit


@app.command()
def audit(
    spec: SpecPath,
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
    fail_on_open: Annotated[
        bool, typer.Option("--fail-on-open", help="Exit with 1 if any risk is open.")
    ] = False,
) -> None:
    """Map the spec to the OWASP Top 10 for LLM Applications (2025) and tool checks.

    Reads only the spec. "covered" means the settings are on; the gate proves they work.
    """
    try:
        report = audit_spec(load_spec(spec))
    except SpecError as exc:
        raise _fail(str(exc), EXIT_INVALID_SPEC) from None
    typer.echo(json.dumps(report.to_dict(), indent=2) if as_json else report.to_text())
    if fail_on_open and report.open_items:
        raise typer.Exit(code=1)
