"""``sevn gui`` — Mission Control surface helpers (`specs/23-cli.md` §2.4).

Module: sevn.cli.commands.gui_cmd
Depends: typer, sevn.cli.json_util

Exports:
    register — attach ``gui`` command group to the root Typer app.
"""

from __future__ import annotations

import typer

from sevn.cli.json_util import emit_json_failure


def register(app: typer.Typer) -> None:
    """Attach ``sevn gui`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    gui = typer.Typer(
        help="Mission Control GUI links and migration helpers.",
        invoke_without_command=True,
    )
    app.add_typer(gui, name="gui")

    @gui.callback()
    def gui_root(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is not None:
            return
        typer.echo(ctx.get_help())

    @gui.command("migrate")
    def gui_migrate(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Describe GUI migration handoff (Mission Control surfaces tab)."""
        command = "sevn gui migrate"
        msg = (
            "GUI layout migration is handled in Mission Control (Surfaces tab) or via "
            "`sevn dashboard --open`. No standalone CLI migrator ships in v1."
        )
        if json_out:
            emit_json_failure(
                command=command,
                error_code="NOT_IMPLEMENTED",
                message=msg,
                exit_code=4,
            )
        else:
            typer.secho(msg, err=True)
        raise typer.Exit(4)


__all__ = ["register"]
