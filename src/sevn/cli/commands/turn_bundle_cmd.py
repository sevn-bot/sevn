"""``sevn turn-bundle`` — offline bundle export and explorer (`specs/23-cli.md`).

Module: sevn.cli.commands.turn_bundle_cmd
Depends: json, sqlite3, typer, sevn.config.loader, sevn.gateway.turn_bundle, sevn.storage

Exports:
    register — attach ``turn-bundle`` Typer subtree.
"""

from __future__ import annotations

import json
import sqlite3
from typing import cast

import typer

from sevn.config.loader import find_sevn_json
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.turn_bundle import (
    TurnBundleViewSection,
    TurnBundleViewStream,
    export_turn_bundles,
    view_turn_bundle,
)
from sevn.storage import open_sevn_sqlite
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.query.traces import ensure_trace_connection
from sevn.workspace.layout import WorkspaceLayout


def _resolve_workspace() -> tuple[sqlite3.Connection, WorkspaceLayout]:
    """Open ``sevn.db`` and layout for the workspace bound to cwd ``sevn.json``.

    Returns:
        tuple[sqlite3.Connection, WorkspaceLayout]: SQLite handle and layout.

    Raises:
        typer.Exit: Exit code 2 when no ``sevn.json`` is found upward from cwd.

    Examples:
        >>> import typer
        >>> try:
        ...     _resolve_workspace()
        ... except typer.Exit as exc:
        ...     exc.exit_code == 2
        ... else:
        ...     False
        True
    """
    sevn_json = find_sevn_json()
    if sevn_json is None:
        typer.echo("No sevn.json found; run from a workspace directory.", err=True)
        raise typer.Exit(2)
    cfg = parse_workspace_config(json.loads(sevn_json.read_text(encoding="utf-8")))
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    conn = open_sevn_sqlite(layout.dot_sevn)
    return conn, layout


_VALID_VIEW_STREAMS = frozenset({"log", "message", "trace"})
_VALID_VIEW_SECTIONS = frozenset({"meta", "summary"})


def register(app: typer.Typer) -> None:
    """Register ``turn-bundle export`` and ``turn-bundle view`` subcommands.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> import typer
        >>> register(typer.Typer())
    """
    bundle = typer.Typer(help="Per-turn diagnostic JSONL bundles under .sevn/turns/.")
    app.add_typer(bundle, name="turn-bundle")

    @bundle.command("export")
    def turn_bundle_export(
        turn: str | None = typer.Option(None, "--turn", help="Export one correlation id."),
        session: str | None = typer.Option(
            None, "--session", help="Export all turns in a session."
        ),
        since: str | None = typer.Option(
            None,
            "--since",
            help="Export turns whose first message is at or after this ISO timestamp.",
        ),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Backfill or refresh turn bundles from sevn.db, traces.db, and gateway.log."""
        if turn is None and session is None and since is None:
            typer.echo("Specify at least one of --turn, --session, or --since.", err=True)
            raise typer.Exit(2)

        conn, layout = _resolve_workspace()
        trace_conn: sqlite3.Connection | None = None
        try:
            traces_path = traces_sqlite_path(layout.dot_sevn)
            if traces_path.is_file():
                trace_conn = ensure_trace_connection(traces_path)
            try:
                written = export_turn_bundles(
                    conn,
                    trace_conn,
                    content_root=layout.content_root,
                    turn_id=turn,
                    session_id=session,
                    since=since,
                )
            except ValueError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(2) from exc
        finally:
            if trace_conn is not None:
                trace_conn.close()
            conn.close()

        items = [
            {
                "turn_id": paths.turn_id,
                "bundle_path": str(paths.bundle_path),
                "safe_turn_id": paths.safe_turn_id,
            }
            for paths in written
        ]
        if json_out:
            typer.echo(
                json.dumps(
                    {
                        "ok": True,
                        "command": "turn-bundle export",
                        "data": {"count": len(items), "items": items},
                    },
                    sort_keys=True,
                ),
            )
            return
        if not items:
            typer.echo("No turns exported.")
            return
        for item in items:
            typer.echo(f"{item['turn_id']}\t{item['bundle_path']}")

    @bundle.command("view")
    def turn_bundle_view(
        turn_id: str = typer.Argument(..., help="Turn correlation id."),
        stream: str | None = typer.Option(
            None,
            "--stream",
            help="Filter to one stream: log, message, or trace.",
        ),
        grep: str | None = typer.Option(None, "--grep", help="Regex filter on output lines."),
        errors_only: bool = typer.Option(
            False,
            "--errors-only",
            help="Show only error-indicating log, message, and trace rows.",
        ),
        section: str | None = typer.Option(
            None,
            "--section",
            help="Show only meta header or a compact summary.",
        ),
    ) -> None:
        """Read one indexed turn bundle with optional filters (W3 explorer)."""
        if stream is not None and stream not in _VALID_VIEW_STREAMS:
            typer.echo(
                f"Invalid --stream {stream!r}; expected one of: log, message, trace.",
                err=True,
            )
            raise typer.Exit(2)
        if section is not None and section not in _VALID_VIEW_SECTIONS:
            typer.echo(
                f"Invalid --section {section!r}; expected one of: meta, summary.",
                err=True,
            )
            raise typer.Exit(2)
        if stream is not None and section is not None:
            typer.echo("Use either --stream or --section, not both.", err=True)
            raise typer.Exit(2)

        _conn, layout = _resolve_workspace()
        _conn.close()
        try:
            lines = view_turn_bundle(
                layout.content_root,
                turn_id,
                stream=cast("TurnBundleViewStream", stream) if stream is not None else None,
                grep=grep,
                errors_only=errors_only,
                section=cast("TurnBundleViewSection", section) if section is not None else None,
            )
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(2) from exc

        if not lines:
            typer.echo("No matching bundle lines.")
            return
        for line in lines:
            typer.echo(line)
