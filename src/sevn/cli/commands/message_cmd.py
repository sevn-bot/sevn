"""``sevn message`` — post messages to gateway sessions (`specs/23-cli.md` §2.4).

Module: sevn.cli.commands.message_cmd
Depends: typer, sevn.cli.json_util, sevn.gateway.sessions_query, sevn.storage

Exports:
    register — attach ``message`` command group to the root Typer app.
"""

from __future__ import annotations

import json

import typer

from sevn.cli.commands.sessions import _resolve_db
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.gateway.sessions_query import send_to_session


def register(app: typer.Typer) -> None:
    """Attach ``sevn message`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    msg = typer.Typer(help="Post outbound lines to a gateway session history.")
    app.add_typer(msg, name="message")

    @msg.command("send")
    def message_send(
        session_id: str = typer.Option(..., "--session-id", help="Target gateway session id."),
        text: str = typer.Option(..., "--text", help="Message body to append."),
        role: str = typer.Option("user", "--role", help="Stored role: user or system."),
        caller_session_id: str | None = typer.Option(
            None,
            "--caller-session-id",
            help="Visibility guard session id (defaults to SEVN_SESSION_ID).",
        ),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Append one line to another session via workspace ``sevn.db``."""
        command = "sevn message send"
        conn, _ = _resolve_db()
        try:
            result = send_to_session(
                conn,
                session_id.strip(),
                text,
                caller_session_id=caller_session_id,
                role=role,
            )
        except ValueError as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="VALIDATION_ERROR",
                    message=str(exc),
                    exit_code=4,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        finally:
            conn.close()
        if json_out:
            emit_json_success(command=command, data=result)
            return
        typer.echo(json.dumps(result, sort_keys=True))


__all__ = ["register"]
