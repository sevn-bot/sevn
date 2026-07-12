"""``sevn pairing`` CLI for DM pairing approval.

Module: sevn.cli.commands.pairing_cmd
Depends: typer, sevn.gateway.pairing, sevn.cli.workspace

Exports:
    register — attach ``pairing`` subtree to root Typer app.
"""

from __future__ import annotations

import typer

from sevn.cli.errors import CliPreconditionError
from sevn.cli.workspace import load_bound_workspace
from sevn.gateway.pairing import PairingStore


def register(app: typer.Typer) -> None:
    """Attach ``sevn pairing approve`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """
    pairing = typer.Typer(help="DM pairing approval for messaging channels.")
    app.add_typer(pairing, name="pairing")

    @pairing.command("approve")
    def pairing_approve(
        channel: str = typer.Argument(..., help="Channel adapter name (e.g. discord)."),
        code: str = typer.Argument(..., help="Pairing code from the user DM."),
    ) -> None:
        """Approve a pending pairing code and add the sender to the allowlist."""
        bw = load_bound_workspace()
        if bw is None:
            raise CliPreconditionError("workspace not found — run from a configured sevn home")
        store = PairingStore(bw.layout.content_root)
        result = store.approve_code(channel.strip().lower(), code)
        if result is None:
            typer.secho("invalid or expired pairing code", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=4)
        typer.echo(f"Approved {channel} user {result['user_id']}.")
