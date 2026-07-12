"""Cloudflare D1 backend protocol sketch (`specs/03-storage.md` §3.3).

Exports:
    D1Backend — operator-selectable remote SQL protocol (not wired by default).
"""

from __future__ import annotations

from typing import Protocol


class D1Backend(Protocol):
    """Protocol for optional D1 worker sync (`specs/03-storage.md` §3.3)."""

    def apply_migration(self, version: int, sql: str) -> None:
        """Apply one migration statement batch.

        Args:
            version (int): Migration version number.
            sql (str): D1-compatible SQL.

        Returns:
            None: Always.

        Examples:
            >>> class _M:
            ...     def apply_migration(self, version: int, sql: str) -> None:
            ...         pass
            >>> _M().apply_migration(1, "SELECT 1")
        """
        ...

    def query(self, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
        """Run a read query.

        Args:
            sql (str): Parameterised SQL.
            params (tuple[object, ...], optional): Bind parameters.

        Returns:
            list[dict[str, object]]: Row dicts.

        Examples:
            >>> class _Q:
            ...     def query(self, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
            ...         return []
            >>> _Q().query("SELECT 1")
            []
        """
        ...


__all__ = ["D1Backend"]
