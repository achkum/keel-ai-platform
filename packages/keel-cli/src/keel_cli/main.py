"""The ``keel`` command.

Six commands, as in the design: init, dev, eval, promote, diff, audit.
``init`` and ``diff`` work today. The others exit with code 2 and say so,
rather than pretending to do something.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from keel_core import SpecError, __version__, diff_specs, load_spec

app = typer.Typer(
    name="keel",
    help="Keel: one spec, one gate, one policy and trace path for LLM applications.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

EXIT_INVALID_SPEC = 1
EXIT_NOT_IMPLEMENTED = 2

SpecPath = Annotated[Path, typer.Argument(help="Path to a keel.yaml spec.", show_default=False)]


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


# ---------------------------------------------------------------- init


@app.command()
def init(
    directory: Annotated[
        Path, typer.Argument(help="Where to create the project.", file_okay=False)
    ] = Path(),
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite an existing keel.yaml.")
    ] = False,
) -> None:
    """Create a starter keel.yaml with secure defaults."""
    spec_path = directory / "keel.yaml"
    if spec_path.exists() and not force:
        typer.echo(f"{spec_path} already exists. Use --force to overwrite it.", err=True)
        raise typer.Exit(code=1)

    templates = files("keel_cli") / "templates"
    directory.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(templates.joinpath("keel.yaml").read_text(encoding="utf-8"), "utf-8")

    prompt_path = directory / "prompts" / "system.md"
    if not prompt_path.exists():
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(templates.joinpath("system.md").read_text(encoding="utf-8"), "utf-8")

    evals_path = directory / "evals" / "quality.jsonl"
    if not evals_path.exists():
        evals_path.parent.mkdir(parents=True, exist_ok=True)
        evals_path.touch()

    typer.echo(f"Created {spec_path}")


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


# ---------------------------------------------------------------- not built yet


def _not_implemented(command: str) -> NoReturn:
    typer.echo(
        f"'keel {command}' is not implemented yet. See the build order in the README.", err=True
    )
    raise typer.Exit(code=EXIT_NOT_IMPLEMENTED)


@app.command()
def dev() -> None:
    """Run the app locally with tracing. (Not implemented yet.)"""
    _not_implemented("dev")


@app.command(name="eval")
def eval_() -> None:
    """Run the eval suites declared in the spec. (Not implemented yet.)"""
    _not_implemented("eval")


@app.command()
def promote() -> None:
    """Run the gate and deploy a pinned version if it passes. (Not implemented yet.)"""
    _not_implemented("promote")


@app.command()
def audit() -> None:
    """Report which OWASP risks the spec covers. (Not implemented yet.)"""
    _not_implemented("audit")
