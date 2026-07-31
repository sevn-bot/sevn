"""``sevn browser`` — profile auth reset and persistence helpers (`specs/23-cli.md`).

Module: sevn.cli.commands.browser_cmd
Depends: json, typer, sevn.browser.persistence, sevn.cli.workspace

Exports:
    register — attach ``browser`` Typer subtree.
"""

from __future__ import annotations

import json

import typer

from sevn.browser.persistence import clear_browser_auth_state
from sevn.cli.workspace import load_bound_workspace


def register(app: typer.Typer) -> None:
    """Register ``browser clear-auth`` on ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> import typer
        >>> register(typer.Typer())
    """
    browser = typer.Typer(help="Browser profile auth state (CDP Chrome profiles).")
    app.add_typer(browser, name="browser")

    @browser.command("clear-auth")
    def browser_clear_auth(
        session_id: str | None = typer.Option(
            None,
            "--session",
            "-s",
            help="Clear only this gateway session's browser profile.",
        ),
        include_configured_profile: bool = typer.Option(
            False,
            "--include-configured-profile",
            help="Also remove skills.browser.profile_dir when explicitly configured.",
        ),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Clear saved browser auth state (cookies, profiles, CDP registries)."""
        bound = load_bound_workspace()
        content_root = bound.layout.content_root
        from sevn.storage import open_sevn_sqlite

        conn = open_sevn_sqlite(bound.layout.dot_sevn)
        try:
            summary = clear_browser_auth_state(
                content_root,
                bound.config,
                session_id=session_id,
                include_configured_profile=include_configured_profile,
                conn=conn,
            )
        finally:
            conn.close()
        if json_out:
            typer.echo(
                json.dumps(
                    {
                        "ok": True,
                        "command": "browser clear-auth",
                        "data": summary,
                    },
                    sort_keys=True,
                ),
            )
            return
        removed = summary.get("removed") or []
        closed = summary.get("sessions_closed", 0)
        scope = f"session {session_id}" if session_id else "all sessions"
        typer.echo(
            f"Cleared browser auth for {scope}: {len(removed)} artefact(s), {closed} browser(s) closed."
        )


__all__ = ["register"]
