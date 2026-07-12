"""``sevn gateway`` service manager façade (`specs/23-cli.md` §2.4, §4.2).

Module: sevn.cli.commands.gateway
Depends: typer, sevn.cli.daemon_control

Exports:
    register — attach ``gateway`` subcommands.
"""

from __future__ import annotations

import typer

from sevn.cli.daemon_control import register_daemon_subcommands


def register(app: typer.Typer) -> None:
    """Attach ``sevn gateway`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    gw = typer.Typer(help="Control the gateway launchd or systemd user service unit.")
    app.add_typer(gw, name="gateway")
    register_daemon_subcommands(gw, service="gateway")
    from sevn.cli.commands.gateway_set_token import register_set_gateway_token

    register_set_gateway_token(gw)

    @gw.command("logs")
    def logs_cmd(
        lines: int = typer.Option(50, "--lines", "-n", help="Lines of history before follow."),
        no_follow: bool = typer.Option(
            False,
            "--no-follow",
            help="Print tail only and exit (no continuous follow).",
        ),
    ) -> None:
        """Stream gateway logs until Ctrl+C or the gateway stops."""
        from sevn.cli.log_follow import run_gateway_logs

        run_gateway_logs(lines=lines, follow=not no_follow)
