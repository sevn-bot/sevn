"""`sevn sessions` — list and history from gateway SQLite (`specs/23-cli.md` §2.7).

Module: sevn.cli.commands.sessions
Depends: sqlite3, typer, sevn.config.workspace_config, sevn.storage

Exports:
    register — attach ``sessions`` Typer subtree.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import typer

from sevn.config.loader import find_sevn_json
from sevn.config.workspace_config import parse_workspace_config
from sevn.storage import open_sevn_sqlite
from sevn.workspace.layout import WorkspaceLayout


def _resolve_db() -> tuple[sqlite3.Connection, Path]:
    """Open ``sevn.db`` for the workspace bound to cwd ``sevn.json``.

    Returns:
        tuple[sqlite3.Connection, Path]: SQLite handle and ``content_root`` path.

    Raises:
        typer.Exit: Exit code 2 when no ``sevn.json`` is found upward from cwd.

    Examples:
        >>> import typer
        >>> try:
        ...     _resolve_db()
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
    return conn, layout.content_root


def register(app: typer.Typer) -> None:
    """Register ``sessions list`` and ``sessions history`` commands.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> import typer
        >>> register(typer.Typer())
    """
    sess = typer.Typer(help="Gateway session history (SQLite source of truth).")
    app.add_typer(sess, name="sessions")

    @sess.command("list")
    def sessions_list(
        limit: int = typer.Option(50, "--limit", "-n", min=1, max=500),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """List gateway sessions for the bound workspace."""
        conn, _ = _resolve_db()
        try:
            rows = conn.execute(
                """
                SELECT session_id, scope_key, channel, user_id, updated_at
                FROM gateway_sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            items = [
                {
                    "session_id": str(r[0]),
                    "scope_key": str(r[1]),
                    "channel": str(r[2]),
                    "user_id": str(r[3]),
                    "updated_at": str(r[4]),
                }
                for r in rows
            ]
            if json_out:
                typer.echo(
                    json.dumps(
                        {"ok": True, "command": "sessions list", "data": {"items": items}},
                    ),
                )
                return
            if not items:
                typer.echo("No sessions.")
                return
            for it in items:
                typer.echo(
                    f"{it['session_id']}\t{it['channel']}\t{it['scope_key']}\t{it['updated_at']}",
                )
        finally:
            conn.close()

    @sess.command("history")
    def sessions_history(
        session_id: str = typer.Argument(..., help="Gateway session id"),
        limit: int = typer.Option(100, "--limit", "-n", min=1, max=2000),
        full: bool = typer.Option(False, "--full"),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Show message history for one session."""
        conn, content_root = _resolve_db()
        try:
            rows = conn.execute(
                """
                SELECT id, role, kind, content, status, created_at
                FROM gateway_messages
                WHERE session_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
            messages = []
            for mid, role, kind, content, status, created_at in rows:
                body = str(content or "")
                if not full and len(body) > 200:
                    body = body[:200] + "…"
                messages.append(
                    {
                        "id": int(mid),
                        "role": str(role),
                        "kind": str(kind),
                        "content": body,
                        "status": str(status),
                        "created_at": str(created_at),
                    },
                )
            mirror_hint = content_root / "sessions" / "_index.json"
            data: dict[str, object] = {
                "session_id": session_id,
                "messages": messages,
                "mirror_index": str(mirror_hint) if mirror_hint.is_file() else None,
            }
            if json_out:
                typer.echo(
                    json.dumps(
                        {
                            "ok": True,
                            "command": "sessions history",
                            "data": data,
                        },
                    ),
                )
                return
            for m in messages:
                typer.echo(f"[{m['created_at']}] {m['role']}/{m['kind']}: {m['content']}")
        finally:
            conn.close()
