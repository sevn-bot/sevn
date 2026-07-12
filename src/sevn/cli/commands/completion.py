"""``sevn completion`` (`specs/23-cli.md` §2.8).

Module: sevn.cli.commands.completion
Depends: sys, typer, sevn.cli.completion_util, sevn.cli.json_util

Exports:
    register — attach ``completion`` subcommands.
"""

from __future__ import annotations

import sys

import typer

from sevn.cli.completion_util import (
    completion_install,
    completion_show_script,
    completion_uninstall,
    normalize_shell,
)
from sevn.cli.json_util import emit_json_failure


def register(app: typer.Typer) -> None:
    """Attach ``sevn completion`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    comp = typer.Typer(help="Shell completion (Typer/Click scripts for bash, zsh, fish).")
    app.add_typer(comp, name="completion")

    @comp.command("install")
    def completion_install_cmd(
        shell: str = typer.Argument(
            ...,
            help="Target shell for completion scripts: bash, zsh, or fish.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON failure envelope to stdout instead of plain stderr text.",
        ),
    ) -> None:
        """Install completion script to conventional paths (idempotent)."""
        try:
            shell_name = normalize_shell(shell)
        except ValueError as exc:
            if json_out:
                emit_json_failure(
                    command="sevn completion install",
                    error_code="USAGE",
                    message=str(exc),
                    exit_code=2,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(2) from exc
        installed_shell, path = completion_install(shell=shell_name)  # nosec B604
        typer.secho(
            f"{installed_shell} completion installed at {path}",
            fg=typer.colors.GREEN,
        )
        typer.echo("Completion will take effect once you restart the terminal")
        raise typer.Exit(0)

    @comp.command("show")
    def completion_show(
        shell: str = typer.Argument(
            ...,
            help="Target shell for completion scripts: bash, zsh, or fish.",
        ),
    ) -> None:
        """Print Typer completion script to stdout."""
        try:
            shell_name = normalize_shell(shell)
        except ValueError as exc:
            typer.secho(str(exc), err=True)
            raise typer.Exit(2) from exc
        script = completion_show_script(shell=shell_name)  # nosec B604
        sys.stdout.write(script)
        if not script.endswith("\n"):
            sys.stdout.write("\n")
        raise typer.Exit(0)

    @comp.command("uninstall")
    def completion_uninstall_cmd(
        shell: str = typer.Argument(
            ...,
            help="Target shell for completion scripts: bash, zsh, or fish.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON failure envelope to stdout instead of plain stderr text.",
        ),
    ) -> None:
        """Remove managed completion script (idempotent)."""
        try:
            shell_name = normalize_shell(shell)
        except ValueError as exc:
            if json_out:
                emit_json_failure(
                    command="sevn completion uninstall",
                    error_code="USAGE",
                    message=str(exc),
                    exit_code=2,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(2) from exc
        removed_shell, path = completion_uninstall(shell=shell_name)  # nosec B604
        typer.secho(f"{removed_shell} completion removed ({path})", fg=typer.colors.GREEN)
        raise typer.Exit(0)
