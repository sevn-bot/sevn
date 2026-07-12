"""``sevn channels`` — channel health and config (`specs/23-cli.md` §2.4).

Module: sevn.cli.commands.channels_cmd
Depends: typer, sevn.cli.dashboard_api_client, sevn.cli.json_util, sevn.cli.workspace

Exports:
    register — attach ``channels`` command group to the root Typer app.
"""

from __future__ import annotations

from typing import Any

import typer

from sevn.cli.dashboard_api_client import dashboard_api_get
from sevn.cli.errors import CliPreconditionError
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.workspace import load_bound_workspace


def _format_channels_status(body: dict[str, Any]) -> str:
    """Render channel status JSON as plain text.

    Args:
        body (dict[str, Any]): ``GET /api/v1/channels/status`` payload.

    Returns:
        str: Human-readable summary.

    Examples:
        >>> "channels" in _format_channels_status({"channels": []})
        True
    """
    rows = body.get("channels")
    if not isinstance(rows, list) or not rows:
        return "channels: 0"
    lines = [f"channels: {len(rows)}"]
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name") or row.get("channel") or "?"
        enabled = row.get("enabled")
        health = row.get("health") or row.get("connection_state") or "?"
        sessions = row.get("session_count", 0)
        lines.append(f"  {name}: enabled={enabled} health={health} sessions={sessions}")
    return "\n".join(lines)


def _format_channels_config(body: dict[str, Any]) -> str:
    """Render channel config JSON as plain text.

    Args:
        body (dict[str, Any]): ``GET /api/v1/channels/config`` payload.

    Returns:
        str: Human-readable summary.

    Examples:
        >>> _format_channels_config({"channels": {}})
        'channels config loaded'
    """
    channels = body.get("channels")
    if isinstance(channels, dict) and channels:
        lines = ["channels:"]
        for name, blob in sorted(channels.items()):
            enabled = blob.get("enabled") if isinstance(blob, dict) else None
            lines.append(f"  {name}: enabled={enabled}")
        return "\n".join(lines)
    return "channels config loaded"


def register(app: typer.Typer) -> None:
    """Attach ``sevn channels`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    channels = typer.Typer(
        help="Inspect messaging channel health, sessions, and configuration.",
        invoke_without_command=True,
    )
    app.add_typer(channels, name="channels")

    @channels.callback()
    def channels_root(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is not None:
            return
        typer.echo(ctx.get_help())

    @channels.command("status")
    def channels_status(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Show runtime channel health and session counts."""
        command = "sevn channels status"
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
            "/api/v1/channels/status",
            command=command,
            workspace=bound.config,
            json_out=json_out,
        )
        if json_out:
            emit_json_success(command=command, data=body)
            return
        typer.echo(_format_channels_status(body))

    @channels.command("config")
    def channels_config(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Show editable channel enablement from ``sevn.json``."""
        command = "sevn channels config"
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
            "/api/v1/channels/config",
            command=command,
            workspace=bound.config,
            json_out=json_out,
        )
        if json_out:
            emit_json_success(command=command, data=body)
            return
        typer.echo(_format_channels_config(body))


__all__ = ["register"]
