"""``sevn capabilities`` — channel stub vs implemented inventory (#151).

Module: sevn.cli.commands.capabilities_cmd
Depends: typer, sevn.gateway.capabilities_inventory

Exports:
    register — attach ``capabilities`` command to the root Typer app.
"""

from __future__ import annotations

import json
from typing import Any

import typer

from sevn.gateway.capabilities_inventory import build_channel_capabilities_inventory


def _format_capabilities(body: dict[str, Any]) -> str:
    """Render capability inventory JSON as plain text.

    Args:
        body (dict[str, Any]): Inventory payload from
            :func:`~sevn.gateway.capabilities_inventory.build_channel_capabilities_inventory`.

    Returns:
        str: Human-readable summary.

    Examples:
        >>> text = _format_capabilities({"channels": [{"name": "telegram", "status": "implemented"}]})
        >>> "telegram" in text and "implemented" in text
        True
    """
    rows = body.get("channels")
    if not isinstance(rows, list) or not rows:
        return "capabilities: 0 channels"
    lines = [f"capabilities: {len(rows)} channels"]
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "?")
        status = str(row.get("status") or "?")
        label = str(row.get("label") or name)
        source = str(row.get("source") or "")
        suffix = f" ({source})" if source else ""
        lines.append(f"  {name}: {status} — {label}{suffix}")
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    """Attach ``sevn capabilities`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    @app.command("capabilities")
    def capabilities_cmd(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON inventory on stdout."),
    ) -> None:
        """List messaging channels as implemented, stub, or unavailable."""
        body = build_channel_capabilities_inventory()
        if json_out:
            typer.echo(json.dumps(body, indent=2, sort_keys=True))
            return
        typer.echo(_format_capabilities(body))


__all__ = ["register"]
