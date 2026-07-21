"""``status`` — local CLI and session diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from proton_cli import __version__
from proton_cli.account import session as session_store

if TYPE_CHECKING:
    from proton_cli.app import App

app = typer.Typer(
    name="status",
    invoke_without_command=True,
    no_args_is_help=False,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def status_main(ctx: typer.Context) -> None:
    """Show proton-cli install and session status (no secrets)."""
    proton_app: App = ctx.obj
    uid, access, _refresh = proton_app.api.tokens()
    loaded = session_store.load(proton_app.profile)
    session_path = session_store.session_path(proton_app.profile or "default")
    payload = {
        "version": __version__,
        "profile": proton_app.profile,
        "authenticated": bool(uid and access),
        "user_configured": bool(proton_app.creds.user),
        "session_file": str(session_path),
        "session_exists": session_path.is_file(),
        "session_loaded": loaded is not None,
    }
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object(payload)
        return
    proton_app.renderer.table(
        ["KEY", "VALUE"],
        [[k, str(v)] for k, v in payload.items()],
    )
