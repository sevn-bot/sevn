"""Setuptools ``sevn.tools`` entry-point group (`specs/11-tools-registry.md` §2.8).

Third-party packages register ``Tool`` factories under ``[project.entry-points."sevn.tools"]``.
The core wheel ships a no-op row so the entry-point table validates under ``uv build``.

Module: sevn.tools.entrypoints
Depends: none

Exports:
    reserved_plugin_row — setuptools hook referenced from ``pyproject.toml`` (skipped at runtime).

Examples:
    >>> reserved_plugin_row() is None
    True
"""

from __future__ import annotations


def reserved_plugin_row() -> None:
    """Reserved setuptools row for the ``sevn.tools`` group (`specs/11-tools-registry.md` §2.8).

    ``load_plugin_tools`` skips the packaged entry by name so this callable is never
    invoked during normal registry construction.

    Returns:
        None: Placeholder return for static analysis / packaging metadata only.

    Examples:
        >>> reserved_plugin_row() is None
        True
    """

    return
