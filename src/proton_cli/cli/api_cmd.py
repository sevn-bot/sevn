"""``api`` — raw authenticated Proton API requests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import typer

from proton_cli.proton.client import Request
from proton_cli.proton.errors import APIError

if TYPE_CHECKING:
    from proton_cli.app import App

app = typer.Typer(name="api", no_args_is_help=True, add_completion=False)


def _run(ctx: typer.Context) -> App:
    proton_app: App = ctx.obj
    proton_app.authenticate()
    return proton_app


@app.callback()
def api_main(
    ctx: typer.Context,
    method: str = typer.Argument(..., help="HTTP method (GET, POST, PUT, DELETE)"),
    path: str = typer.Argument(..., help="API path e.g. /calendar/v1"),
    query: list[str] = typer.Option([], "--query", help="Query param key=value (repeatable)"),
    body: str = typer.Option("", "--body", help="JSON request body"),
) -> None:
    """Make an authenticated raw API request."""
    proton_app = _run(ctx)
    q: dict[str, str] = {}
    for kv in query:
        if "=" not in kv:
            raise typer.BadParameter(f"invalid --query {kv!r} (expected key=value)")
        key, value = kv.split("=", 1)
        q[key] = value
    payload: dict | list | str | None = None
    if body:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(f"invalid JSON --body: {exc}") from exc
    try:
        resp = proton_app.api.do(
            Request(method=method.upper(), path=path, query=q or None, body=payload),
        )
    except APIError as exc:
        if exc.raw_body:
            proton_app.renderer.json_body(exc.raw_body)
        raise
    proton_app.renderer.json_body(resp.body)
