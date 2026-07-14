"""Shared symbol record types for README scanner and render paths.

Module: sevn.docs.readme.symbols
Depends: typing

Exports:
    SymbolRecord — typed symbol inventory row.
    symbol_names — normalize symbol records to bare names.

Examples:
    >>> from sevn.docs.readme.symbols import symbol_names
    >>> symbol_names([{"name": "Foo.bar", "lineno": 3}])
    ['Foo.bar']
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

README_MAX_SYMBOL_FILES = 12


class SymbolRecord(TypedDict):
    """One public class/function symbol with its definition line."""

    name: str
    lineno: int


def symbol_names(entries: Sequence[object]) -> list[str]:
    """Normalize symbol records to bare names for inline prose.

        Args:
    entries (list[SymbolRecord | dict[str, int | str] | str | object]): Symbol records or legacy strings.

        Returns:
            list[str]: Symbol names in scan order.

        Examples:
            >>> symbol_names([{"name": "Foo.bar", "lineno": 3}])
            ['Foo.bar']
    """
    names: list[str] = []
    for entry_item in entries:
        if isinstance(entry_item, dict):
            name = str(entry_item.get("name", "")).strip()
            if name:
                names.append(name)
        elif isinstance(entry_item, str) and entry_item:
            names.append(entry_item)
    return names
