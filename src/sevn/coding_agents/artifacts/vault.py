"""ALRCA artifact vault — Markdown/text files under workspace/coding_agents/artifacts/ (CA6.2).

Module: sevn.coding_agents.artifacts.vault
Depends: pathlib

Exports:
    write_artifact — persist one artifact file.
    list_run_artifacts — list artifact entries for a run_id.
    list_all_runs — list all run ids with artifact counts.
    read_artifact — read raw text of one artifact.

Vault layout:
    ``<workspace>/coding_agents/artifacts/<run_id>/<filename>``

MC renders an HTML summary from the vault entries returned by :func:`list_run_artifacts`.

Examples:
    >>> import tempfile, pathlib
    >>> with tempfile.TemporaryDirectory() as t:
    ...     p = write_artifact("run-1", "summary.md", "# Summary\\nDone.", pathlib.Path(t))
    ...     p.exists()
    True
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

JsonDict = dict[str, Any]

_ARTIFACTS_DIR = "coding_agents/artifacts"


def _artifacts_root(workspace_path: Path) -> Path:
    """Return the vault root directory, creating it when absent.

    Args:
        workspace_path (Path): Operator workspace root.

    Returns:
        Path: ``<workspace>/coding_agents/artifacts/``

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as t:
        ...     r = _artifacts_root(pathlib.Path(t))
        ...     r.is_dir()
        True
    """
    d = workspace_path / _ARTIFACTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_artifact(
    run_id: str,
    filename: str,
    content: str,
    workspace_path: Path,
) -> Path:
    """Write ``content`` to ``<vault>/<run_id>/<filename>``.

    Args:
        run_id (str): ALRCA run identifier.
        filename (str): Artifact filename (e.g. ``summary.md``, ``verifier.log``).
        content (str): Text content to persist.
        workspace_path (Path): Operator workspace root.

    Returns:
        Path: Written file path.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as t:
        ...     p = write_artifact("r1", "result.md", "done", pathlib.Path(t))
        ...     p.read_text()
        'done'
    """
    run_dir = _artifacts_root(workspace_path) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / filename
    target.write_text(content, encoding="utf-8")
    return target


def read_artifact(run_id: str, filename: str, workspace_path: Path) -> str | None:
    """Read one artifact from the vault.

    Args:
        run_id (str): ALRCA run identifier.
        filename (str): Artifact filename.
        workspace_path (Path): Operator workspace root.

    Returns:
        str | None: Text content or ``None`` when not found.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as t:
        ...     _ = write_artifact("r1", "x.md", "hello", pathlib.Path(t))
        ...     read_artifact("r1", "x.md", pathlib.Path(t))
        'hello'
    """
    target = _artifacts_root(workspace_path) / run_id / filename
    if not target.is_file():
        return None
    return target.read_text(encoding="utf-8")


def list_run_artifacts(run_id: str, workspace_path: Path) -> list[JsonDict]:
    """List artifact metadata for a given run_id.

    Args:
        run_id (str): ALRCA run identifier.
        workspace_path (Path): Operator workspace root.

    Returns:
        list[JsonDict]: Artifact entries with ``name``, ``size_bytes``, ``path``.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as t:
        ...     _ = write_artifact("r1", "log.txt", "data", pathlib.Path(t))
        ...     entries = list_run_artifacts("r1", pathlib.Path(t))
        ...     entries[0]["name"]
        'log.txt'
    """
    run_dir = _artifacts_root(workspace_path) / run_id
    if not run_dir.is_dir():
        return []
    entries: list[JsonDict] = []
    for f in sorted(run_dir.iterdir()):
        if f.is_file():
            entries.append(
                {
                    "name": f.name,
                    "size_bytes": f.stat().st_size,
                    "path": str(f),
                },
            )
    return entries


def list_all_runs(workspace_path: Path) -> list[JsonDict]:
    """List all run directories in the artifact vault.

    Args:
        workspace_path (Path): Operator workspace root.

    Returns:
        list[JsonDict]: Run summaries with ``run_id`` and ``artifact_count``.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as t:
        ...     _ = write_artifact("r1", "f.md", "x", pathlib.Path(t))
        ...     runs = list_all_runs(pathlib.Path(t))
        ...     runs[0]["run_id"]
        'r1'
    """
    root = _artifacts_root(workspace_path)
    runs: list[JsonDict] = []
    for d in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if d.is_dir():
            count = sum(1 for f in d.iterdir() if f.is_file())
            runs.append({"run_id": d.name, "artifact_count": count})
    return runs


__all__ = [
    "list_all_runs",
    "list_run_artifacts",
    "read_artifact",
    "write_artifact",
]
