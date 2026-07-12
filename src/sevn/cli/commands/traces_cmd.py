"""``sevn traces`` span-grouped trace viewer (`specs/23-cli.md` §2.4, D9).

Module: sevn.cli.commands.traces_cmd
Depends: pathlib, typer, sevn.cli.render.console, sevn.cli.render.tree, sevn.cli.traces_read

Exports:
    register — attach ``traces`` command to the root Typer app.
    run_traces — load and render span-grouped turns.
"""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

import typer

from sevn.cli.errors import CliPreconditionError
from sevn.cli.json_util import emit_json_success
from sevn.cli.render.console import configure_render, plain_echo
from sevn.cli.render.tree import render_span_tree
from sevn.cli.traces_read import load_trace_turns, turn_to_span_tree_node
from sevn.cli.workspace import sevn_home_dir
from sevn.config.loader import load_workspace


def run_traces(
    *,
    session: str | None = None,
    last: int = 5,
    since: str | None = None,
    json_mode: bool = False,
    operator_home: Path | None = None,
    json_stream: TextIO | None = None,
) -> None:
    """Load and render span-grouped trace turns from ``traces.db``.

    Args:
        session (str | None): Filter to one gateway session id.
        last (int): Number of recent turns to show.
        since (str | None): Lookback window (e.g. ``1h``, ``24h``).
        json_mode (bool): Emit structured JSON instead of a span tree.
        operator_home (Path | None): ``SEVN_HOME`` override for tests.
        json_stream (TextIO | None): Optional stream for JSON tests.

    Returns:
        None

    Raises:
        typer.Exit: On workspace precondition failures.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> td = Path(tempfile.mkdtemp())
        >>> ws = td / "workspace"
        >>> ws.mkdir()
        >>> _ = (ws / "sevn.json").write_text(
        ...     '{"schema_version": 1, "workspace_root": ".", '
        ...     '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        ...     encoding="utf-8",
        ... )
        >>> (ws / ".sevn").mkdir(exist_ok=True)
        >>> with patch("sevn.cli.commands.traces_cmd.typer.echo"):
        ...     run_traces(last=1, operator_home=td, json_mode=True)
    """
    try:
        home = (operator_home or sevn_home_dir()).expanduser().resolve()
        _cfg, layout = load_workspace(sevn_json=home / "workspace" / "sevn.json")
    except CliPreconditionError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(getattr(exc, "exit_code", 4)) from exc

    turns = load_trace_turns(
        layout.dot_sevn,
        session_id=session,
        last=last,
        since=since,
    )

    if json_mode:
        emit_json_success(
            command="sevn traces",
            data={"turns": turns, "count": len(turns)},
            stream=json_stream,
        )
        return

    if not turns:
        plain_echo("No trace turns found for the selected window.")
        if session:
            plain_echo(f"Session filter: {session}")
        return

    for turn in turns:
        tree = turn_to_span_tree_node(turn)
        render_span_tree(tree, title=tree.label)
        plain_echo("")


def register(app: typer.Typer) -> None:
    """Attach ``sevn traces`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    @app.command(
        "traces",
        rich_help_panel="Observability",
        help="Show span-grouped trace turns from traces.db (session/turn tree).",
    )
    def traces_cmd(
        session: str | None = typer.Option(
            None,
            "--session",
            help="Filter to one gateway session id.",
        ),
        last: int = typer.Option(5, "--last", "-n", help="Number of recent turns to show."),
        since: str | None = typer.Option(
            None,
            "--since",
            help="Lookback window (e.g. 1h, 30m, 2d) or ISO timestamp.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Emit a JSON envelope with nested span trees.",
        ),
    ) -> None:
        """Render span-grouped turns (triage → tier-B → tool calls)."""
        configure_render(json_mode=json_out)
        run_traces(session=session, last=last, since=since, json_mode=json_out)


__all__ = ["register", "run_traces"]
