"""CLI subcommand registration helpers.

Module: sevn.cli.commands
Depends: typer (via submodules)

Exports:
    register_unboard — attach unboard / uninstall / remove commands.
"""

from __future__ import annotations

from sevn.cli.commands.unboard import register as register_unboard

__all__ = ["register_unboard"]
