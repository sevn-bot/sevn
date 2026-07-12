"""Reserved setuptools entry-point row for ``sevn.skills`` (`specs/12-skills-system.md` §2.1).

Third-party wheels register discoverable skill roots via ``[project.entry-points."sevn.skills"]``.
This module exists so the core distribution carries a documented anchor row.

Module: sevn.skills.entrypoints
Depends: (none)

Exports:
    reserved_skills_plugin_row — no-op anchor referenced from ``pyproject.toml``.

Examples:
    >>> reserved_skills_plugin_row() is None
    True
"""

from __future__ import annotations


def reserved_skills_plugin_row() -> None:
    """No-op anchor for packaging metadata (not invoked at runtime).

    Returns:
        None: Always.

    Examples:
        >>> reserved_skills_plugin_row() is None
        True
    """

    return


__all__ = ["reserved_skills_plugin_row"]
