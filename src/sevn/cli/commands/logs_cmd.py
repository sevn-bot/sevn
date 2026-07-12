"""Unified ``sevn logs`` command (`specs/23-cli.md` §2.4, D9).

Module: sevn.cli.commands.logs_cmd
Depends: typer, sevn.cli.log_follow, sevn.cli.render.console

Exports:
    register — attach ``logs`` command to the root Typer app.
"""

from __future__ import annotations

import typer

from sevn.cli.log_follow import LogSource, run_unified_logs
from sevn.cli.render.console import configure_render


def register(app: typer.Typer) -> None:
    """Attach ``sevn logs`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    @app.command(
        "logs",
        rich_help_panel="Observability",
        help=(
            "Tail and follow unified workspace logs (gateway, proxy, agent, cli) "
            "with an insight summary header."
        ),
    )
    def logs_cmd(
        source: LogSource = typer.Option(
            "all",
            "--source",
            "-s",
            help="Log source: gateway, proxy, agent, cli, or all.",
        ),
        all_sources: bool = typer.Option(
            False,
            "--all",
            help="Shorthand for --source all.",
        ),
        lines: int = typer.Option(50, "--lines", "-n", help="Lines of history before follow."),
        follow: bool = typer.Option(False, "--follow", "-f", help="Follow new log lines."),
        since: str | None = typer.Option(
            None,
            "--since",
            help="Lookback window (e.g. 1h, 30m, 2d) or ISO timestamp.",
        ),
        grep: str | None = typer.Option(None, "--grep", help="Case-insensitive pattern filter."),
        level: str | None = typer.Option(
            None,
            "--level",
            help="Minimum level: TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Emit a JSON envelope with summary + lines on stdout.",
        ),
        no_summary: bool = typer.Option(
            False,
            "--no-summary",
            help="Suppress the insight summary header.",
        ),
    ) -> None:
        """Stream merged workspace logs with optional insight summary."""
        configure_render(json_mode=json_out)
        selected: LogSource = "all" if all_sources else source
        run_unified_logs(
            source=selected,
            lines=lines,
            follow=follow,
            since=since,
            grep=grep,
            level=level,
            json_mode=json_out,
            include_summary=not no_summary,
        )


__all__ = ["register"]
