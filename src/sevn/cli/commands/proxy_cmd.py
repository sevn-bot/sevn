"""``sevn proxy`` service manager façade (`specs/23-cli.md` §2.4, §4.2).

Module: sevn.cli.commands.proxy_cmd
Depends: typer, sevn.cli.daemon_control

Exports:
    register — attach ``proxy`` subcommands.
"""

from __future__ import annotations

import typer

from sevn.cli.daemon_control import register_daemon_subcommands


def register(app: typer.Typer) -> None:
    """Attach ``sevn proxy`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    px = typer.Typer(help="Control the egress proxy launchd or systemd user service unit.")
    app.add_typer(px, name="proxy")
    register_daemon_subcommands(px, service="proxy")

    @px.command("logs")
    def logs_cmd(
        lines: int = typer.Option(50, "--lines", "-n", help="Lines of history before follow."),
        no_follow: bool = typer.Option(
            False,
            "--no-follow",
            help="Print tail only and exit (no continuous follow).",
        ),
    ) -> None:
        """Stream proxy logs until Ctrl+C or the proxy stops."""
        from sevn.cli.log_follow import run_service_logs

        run_service_logs(service="proxy", lines=lines, follow=not no_follow)
