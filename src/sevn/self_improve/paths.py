"""Filesystem layout for ``.sevn/improve/`` artefacts (`specs/33-self-improvement.md` §3.5).

Module: sevn.self_improve.paths
Depends: pathlib, sevn.workspace.layout

Exports:
    improve_root — base directory under the workspace layout.
    job_bundle_dir — per-job artefact directory.
    self_improve_audit_path — append-only audit JSONL path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.workspace.layout import WorkspaceLayout


def improve_root(layout: WorkspaceLayout) -> Path:
    """Return ``<content_root>/.sevn/improve``.

    Args:
    layout (WorkspaceLayout): Resolved workspace layout.

    Returns:
        Path: Improve artefact root (may not exist yet).

    Examples:
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> ly = WorkspaceLayout(Path("/tmp/x/sevn.json"), Path("/tmp/x"))
        >>> improve_root(ly).name
        'improve'
    """
    return layout.dot_sevn / "improve"


def job_bundle_dir(layout: WorkspaceLayout, job_id: str) -> Path:
    """Return ``<improve_root>/<job_id>``.

    Args:
    layout (WorkspaceLayout): Resolved workspace layout.
    job_id (str): Persisted job identifier.

    Returns:
        Path: Directory reserved for shortlists, patches, and eval outputs.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> ly = WorkspaceLayout(Path("/w/sevn.json"), Path("/w"))
        >>> job_bundle_dir(ly, "j1").name
        'j1'
    """
    return improve_root(layout) / job_id


def self_improve_audit_path(layout: WorkspaceLayout) -> Path:
    """Return the merge/revert audit JSONL path.

    Args:
    layout (WorkspaceLayout): Resolved workspace layout.

    Returns:
        Path: Append-only audit file (created on first promotion).

    Examples:
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> self_improve_audit_path(WorkspaceLayout(Path("/w/s.json"), Path("/w"))).name
        'self_improve_audit.jsonl'
    """
    return improve_root(layout) / "self_improve_audit.jsonl"
