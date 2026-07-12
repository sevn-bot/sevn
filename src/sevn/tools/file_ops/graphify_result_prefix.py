"""Graphify search-tool prefix injection (`specs/28-code-understanding.md` §2.5).

Module: sevn.tools.file_ops.graphify_result_prefix
Depends: sevn.code_understanding.graphify, sevn.code_understanding.models

Exports:
    graphify_prefix_for_search_path — prepend text when scope is under a profile root.
"""

from __future__ import annotations

from pathlib import Path

from sevn.code_understanding.graphify import (
    graph_json_path,
    profile_covers,
    search_tool_prefix,
)
from sevn.code_understanding.models import GraphifyProfile


def graphify_prefix_for_search_path(
    profiles: list[GraphifyProfile],
    search_base: Path,
) -> str:
    """Return the §2.5 prefix when ``search_base`` lies under a profile with ``graph.json``.

    Args:
        profiles (list[GraphifyProfile]): Active Graphify profiles (report on disk).
        search_base (Path): Resolved absolute directory or file being searched.

    Returns:
        str: Prefix string plus blank line, or ``""`` when no profile applies.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.code_understanding.models import GraphifyProfile
        >>> graphify_prefix_for_search_path([], Path("/tmp"))
        ''
    """
    if not profiles:
        return ""
    base = search_base.resolve()
    if base.is_file():
        base = base.parent
    for profile in profiles:
        if not profile_covers(profile, base):
            continue
        if graph_json_path(profile).is_file():
            return search_tool_prefix(profile) + "\n\n"
    return ""


__all__ = ["graphify_prefix_for_search_path"]
