"""Workspace path guards for bundled ``pdf`` skill scripts.

Module: sevn.pdf.paths
Depends: pathlib, sevn.workspace.artifact_output

Exports:
    resolve_path_under_workspace — resolve a path and ensure it stays under workspace root.
"""

from __future__ import annotations

import os
from pathlib import Path

from sevn.workspace.artifact_output import (
    artifact_output_prefix_from_env,
    rebase_artifact_relative_path,
)


def resolve_path_under_workspace(
    workspace: Path,
    raw: str,
    *,
    artifact: bool = False,
    output_prefix: str | None = None,
) -> Path:
    """Resolve ``raw`` under ``workspace`` and reject escapes.

    Relative paths are joined under ``workspace`` and guarded against ``..``
    traversal **lexically** — they are deliberately *not* passed through
    :meth:`Path.resolve`. Skill scripts run inside a shadow workspace that is a
    symlink farm pointing back into the real workspace (see
    ``sevn.security.sandbox_runtime.materialize_shadow_workspace``); resolving a
    relative path would follow those symlinks out of the shadow root and trip a
    spurious "escapes workspace root" error for every legitimate path. Joining
    under ``workspace`` keeps the returned path inside the shadow so the OS
    transparently follows the entry symlink on read/write, and so callers can
    still ``relative_to(workspace)`` the result.

    When ``artifact`` is true, bare relative paths are rebased under
    ``output_prefix`` (or ``SEVN_ARTIFACT_OUTPUT_PREFIX`` from the skill runner)
    so generated files cannot litter the workspace root.

    Args:
        workspace (Path): Workspace content root.
        raw (str): Relative or absolute path under the workspace.
        artifact (bool, optional): When true, confine writes under the artifact
            output prefix. Defaults to ``False``.
        output_prefix (str | None, optional): Workspace-relative output prefix.
            Defaults to the skill-runner env var when ``artifact`` is true.

    Returns:
        Path: Absolute path under ``workspace`` (symlinks left unresolved).

    Raises:
        ValueError: When the path traverses outside ``workspace``.

    Examples:
        >>> import tempfile
        >>> ws = Path(tempfile.mkdtemp())
        >>> child = ws / "docs" / "a.pdf"
        >>> child.parent.mkdir(parents=True)
        >>> resolve_path_under_workspace(ws, "docs/a.pdf") == child.resolve()
        True
        >>> # A symlinked entry pointing outside the shadow stays accepted.
        >>> real = Path(tempfile.mkdtemp())
        >>> _ = (real / "out").mkdir()
        >>> shadow = Path(tempfile.mkdtemp())
        >>> (shadow / "out").symlink_to(real / "out")
        >>> resolve_path_under_workspace(shadow, "out/x.pdf") == shadow.resolve() / "out" / "x.pdf"
        True
        >>> resolve_path_under_workspace(ws, "../etc/passwd")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ValueError: pdf: path '../etc/passwd' escapes workspace root
        >>> p = resolve_path_under_workspace(ws, "page.pdf", artifact=True, output_prefix="out/sess")
        >>> p.name
        'page.pdf'
        >>> p.parent.name
        'sess'
    """
    rel = raw
    if artifact:
        prefix = (output_prefix or artifact_output_prefix_from_env() or "out").strip()
        rel = rebase_artifact_relative_path(raw, prefix)
    root = workspace.resolve()
    candidate = Path(rel).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
        if resolved != root and root not in resolved.parents:
            msg = f"pdf: path {raw!r} escapes workspace root"
            raise ValueError(msg)
        return resolved
    normalized = os.path.normpath(rel)
    if (
        normalized == os.pardir
        or normalized.startswith(os.pardir + os.sep)
        or os.path.isabs(normalized)
    ):
        msg = f"pdf: path {raw!r} escapes workspace root"
        raise ValueError(msg)
    return root / normalized
