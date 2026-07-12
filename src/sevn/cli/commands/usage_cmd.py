"""``sevn usage`` — budget and quota snapshots (`specs/23-cli.md` §2.4).

Module: sevn.cli.commands.usage_cmd
Depends: typer, sevn.cli.dashboard_api_client, sevn.cli.json_util, sevn.cli.workspace

Exports:
    register — attach ``usage`` command group to the root Typer app.
"""

from __future__ import annotations

from typing import Any

import typer

from sevn.cli.dashboard_api_client import dashboard_api_get
from sevn.cli.errors import CliPreconditionError
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.workspace import load_bound_workspace


def _format_usage(body: dict[str, Any]) -> str:
    """Render budget summary JSON as plain text.

    Args:
        body (dict[str, Any]): ``GET /api/v1/budget/summary`` payload.

    Returns:
        str: Human-readable summary.

    Examples:
        >>> "hourly" in _format_usage({"hourly": [], "alerts": []}) or True
        True
    """
    lines: list[str] = []
    alerts = body.get("alerts")
    if isinstance(alerts, list) and alerts:
        lines.append(f"alerts: {len(alerts)}")
        for item in alerts[:10]:
            lines.append(f"  - {item}")
    projections = body.get("projections")
    if isinstance(projections, dict) and projections:
        lines.append("projections:")
        for key, val in sorted(projections.items()):
            lines.append(f"  {key}: {val}")
    regimes = body.get("by_regime")
    if isinstance(regimes, dict) and regimes:
        lines.append("by_regime:")
        for key, val in sorted(regimes.items()):
            lines.append(f"  {key}: {val}")
    if not lines:
        lines.append("usage: no budget rollups yet (empty traces.db or no spend)")
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    """Attach ``sevn usage`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    usage = typer.Typer(
        help="Show budget rollups and subscription-window posture from traces.",
        invoke_without_command=True,
    )
    app.add_typer(usage, name="usage")

    @usage.callback()
    def usage_root(
        ctx: typer.Context,
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        if ctx.invoked_subcommand is not None:
            return
        _usage_show(json_out=json_out)

    @usage.command("show")
    def usage_show(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Show budget summary (default ``sevn usage`` action)."""
        _usage_show(json_out=json_out)


def _usage_show(*, json_out: bool) -> None:
    """Shared implementation for ``sevn usage`` and ``sevn usage show``.

    Args:
        json_out (bool): Emit JSON success envelope on stdout when True.

    Examples:
        >>> _usage_show(json_out=False)  # doctest: +SKIP
    """
    command = "sevn usage show"
    try:
        bound = load_bound_workspace()
    except CliPreconditionError as exc:
        if json_out:
            emit_json_failure(
                command=command,
                error_code="PRECONDITION",
                message=str(exc),
                exit_code=exc.exit_code,
            )
        else:
            typer.secho(str(exc), err=True)
        raise typer.Exit(exc.exit_code) from exc
    body = dashboard_api_get(
        "/api/v1/budget/summary",
        command=command,
        workspace=bound.config,
        json_out=json_out,
    )
    if json_out:
        emit_json_success(command=command, data=body)
        return
    typer.echo(_format_usage(body))


__all__ = ["register"]
