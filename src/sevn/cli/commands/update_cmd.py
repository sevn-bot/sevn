"""``sevn update`` / ``sevn upgrade`` — package and schema helpers (`specs/23-cli.md` §2.4).

Module: sevn.cli.commands.update_cmd
Depends: importlib.metadata, sys, typer, sevn.onboarding.migrate

Exports:
    register — attach ``update`` and ``upgrade`` root commands.
"""

from __future__ import annotations

import json
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version

import typer

from sevn.cli.json_util import emit_json_success
from sevn.cli.workspace import load_bound_workspace
from sevn.onboarding.migrate import describe_schema_upgrade


def register(app: typer.Typer) -> None:
    """Attach ``sevn update`` and ``sevn upgrade`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    @app.command("update")
    def update_cmd(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Show how to upgrade the installed ``sevn`` CLI package."""
        command = "sevn update"
        try:
            current = pkg_version("sevn")
        except PackageNotFoundError:
            current = "0.0.0"
        hint = "uv tool upgrade sevn  # or: pip install -U sevn"
        data = {"current_version": current, "hint": hint}
        if json_out:
            emit_json_success(command=command, data=data)
            return
        typer.echo(f"installed: {current}")
        typer.echo(hint)

    @app.command("upgrade")
    def upgrade_cmd(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Describe workspace schema upgrade posture for the bound ``sevn.json``."""
        command = "sevn upgrade"
        try:
            bound = load_bound_workspace()
        except Exception as exc:
            typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        plan = describe_schema_upgrade(bound.layout.content_root)
        data = {
            "schema_upgrade": plan,
            "hint": "Run `sevn migrate` to apply in-place schema upgrades when prompted.",
            "python_version": sys.version.split()[0],
        }
        if json_out:
            emit_json_success(command=command, data=data)
            return
        typer.echo(json.dumps(plan, indent=2, sort_keys=True))
        typer.echo("Run `sevn migrate` when an in-place schema upgrade is required.")


__all__ = ["register"]
