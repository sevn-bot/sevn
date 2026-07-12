"""Workspace paths and layout derived from ``sevn.json``.

Module: sevn.workspace
Depends: sevn.workspace.layout

Exports:
    WorkspaceLayout — content root, ``.sevn``, logs, trace dir helper.

Note:
    ``tools_md`` registry sync lives in ``sevn.workspace.tools_md`` (import directly).

Examples:
    >>> from sevn.workspace import WorkspaceLayout
    >>> from pathlib import Path
    >>> WorkspaceLayout(Path("/x/s.json"), Path("/r")).dot_sevn == Path("/r/.sevn")
    True
"""

from __future__ import annotations

from sevn.workspace.layout import WorkspaceLayout

__all__ = ["WorkspaceLayout"]
