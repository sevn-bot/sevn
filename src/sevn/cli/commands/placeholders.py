"""Stub subcommands that exit ``4`` with actionable text (`specs/23-cli.md` §10.1).

Module: sevn.cli.commands.placeholders
Depends: typer

Exports:
    register — attach deferred command trees (no silent success).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import typer


def register(app: typer.Typer) -> None:
    """Attach any remaining deferred §2.4 command trees to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> import typer
        >>> register(typer.Typer()) is None
        True
    """
    _ = app
