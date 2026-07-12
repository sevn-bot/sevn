"""Command-line interface (`specs/23-cli.md`).

Module: sevn.cli
Depends: sevn.cli.app

Exports:
    main — console script entrypoint (``sevn``).
"""

from __future__ import annotations

from sevn.cli.app import main

__all__ = ["main"]
