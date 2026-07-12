"""Adapter for the roam-code CLI (`specs/28-code-understanding.md` §2.2).

Module: sevn.code_understanding.roam_code_adapter
Depends: pathlib, sevn.code_understanding.roam_runner

Exports:
    RoamCodeAdapter — path Q&A bridge to allowlisted ``roam`` subcommands.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — public API stores Path

from sevn.code_understanding.roam_runner import run_roam_query


class RoamCodeAdapter:
    """Lightweight path Q&A via the upstream ``roam`` CLI.

    When a query is provided, dispatches ``roam retrieve``; otherwise runs
    ``roam understand`` for a codebase briefing. Failures prefix ``roam_code:``.

    Attributes:
        root: Absolute repository root the adapter queries.

    Example:
        >>> from pathlib import Path
        >>> RoamCodeAdapter(Path("/r")).root.as_posix()
        '/r'
    """

    def __init__(self, root: Path) -> None:
        """Construct the adapter with a repository root.

        Args:
            root (Path): Repository root the adapter targets.

        Examples:
            >>> from pathlib import Path
            >>> RoamCodeAdapter(Path("/r")).root.as_posix()
            '/r'
        """
        self.root: Path = root

    def query(self, q: str | None) -> str:
        """Run ``roam retrieve`` or ``roam understand`` for ``root``.

        Args:
            q (str | None): Free-form natural-language query; ``None`` runs briefing.

        Returns:
            str: Prefixed stdout text or a ``roam_code:`` error message.

        Examples:
            >>> from pathlib import Path
            >>> isinstance(RoamCodeAdapter(Path("/r")).query("how does foo work?"), str)
            True
        """
        _ok, text = run_roam_query(self.root, q)
        return text
