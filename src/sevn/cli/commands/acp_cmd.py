"""``sevn acp`` — Agent Client Protocol stdio runtime (#72, W31.1).

Module: sevn.cli.commands.acp_cmd
Depends: typer, sevn.acp.runtime, sevn.cli.workspace

Exports:
    register — attach ``acp`` command group to the root Typer app.
"""

from __future__ import annotations

import sys

import typer

from sevn.acp.runtime import run_acp_stdio_session
from sevn.cli.workspace import load_bound_workspace


def _workspace_snapshot() -> dict[str, object]:
    """Build a turn-bridge snapshot from the bound workspace when available.

    Returns:
        dict[str, object]: Snapshot for :func:`~sevn.acp.turn_bridge.run_acp_prompt_turn`.

    Examples:
        >>> isinstance(_workspace_snapshot(), dict)
        True
    """
    try:
        bound = load_bound_workspace()
    except Exception:
        return {}
    layout = bound.layout
    return {
        "content_root": str(layout.content_root),
        "sevn_json": str(layout.sevn_json_path),
        "workspace": bound.config.model_dump(mode="python"),
    }


def register(app: typer.Typer) -> None:
    """Attach ``sevn acp`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """
    acp = typer.Typer(
        help=(
            "Run the sevn Agent Client Protocol (ACP) runtime over stdio for Buzz "
            "and other ACP hosts (``buzz-acp`` managed runtime)."
        ),
    )
    app.add_typer(acp, name="acp")

    @acp.callback(invoke_without_command=True)
    def acp_runtime() -> None:
        """Speak JSON-RPC NDJSON on stdin/stdout (spawned by Buzz ``buzz-acp``)."""
        snapshot = _workspace_snapshot()
        run_acp_stdio_session(workspace_config=dict(snapshot), stdout=sys.stdout)


__all__ = ["register"]
