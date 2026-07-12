"""Trajectory export scaffold under ``.sevn/improve/exports/`` (`specs/33-self-improvement.md` §4.6).

Module: sevn.self_improve.export
Depends: json, pathlib, shutil, time, sevn.config.defaults, sevn.self_improve.paths

Exports:
    improve_export_dir — per-job export bundle path under .sevn/improve/exports/.
    scaffold_improve_export_bundle — write manifest + eval transcript + optional diff bundle.
    prune_stale_export_bundles — TTL prune for export directories.
"""

from __future__ import annotations

import json
import shutil
import time
from typing import TYPE_CHECKING

from sevn.config.defaults import DEFAULT_SELF_IMPROVE_EXPORT_TTL_DAYS

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.workspace.layout import WorkspaceLayout

_EXPORT_SCHEMA_VERSION = 1


def improve_export_dir(layout: WorkspaceLayout, job_id: str) -> Path:
    """Return ``<improve_root>/exports/<job_id>``.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout.
        job_id (str): Persisted job identifier.

    Returns:
        Path: Export bundle directory (may not exist yet).

    Examples:
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> list(improve_export_dir(WorkspaceLayout(Path("/w/s.json"), Path("/w")), "j1").parts[-2:])
        ['exports', 'j1']
    """
    from sevn.self_improve.paths import improve_root

    return improve_root(layout) / "exports" / job_id


def scaffold_improve_export_bundle(
    layout: WorkspaceLayout,
    job_id: str,
    *,
    eval_report_path: Path | None = None,
    patch_dir: Path | None = None,
    ttl_days: int = DEFAULT_SELF_IMPROVE_EXPORT_TTL_DAYS,
) -> Path:
    """Write versioned export artefacts for an improve job (scaffold v1).

    Creates ``manifest.json``, copies ``eval_report.json`` when present, and
    optionally mirrors a patch directory into ``diff_bundle/``.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout.
        job_id (str): Persisted job identifier.
        eval_report_path (Path | None): Source eval report to copy.
        patch_dir (Path | None): Optional patch directory to mirror.
        ttl_days (int): Retention hint stored in the manifest.

    Returns:
        Path: Export bundle root directory.

    Examples:
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> def _demo() -> bool:
        ...     td = TemporaryDirectory()
        ...     root = Path(td.name)
        ...     ly = WorkspaceLayout(root / "sevn.json", root)
        ...     eval_p = root / "eval_report.json"
        ...     _ = eval_p.write_text('{"passed": true}', encoding="utf-8")
        ...     out = scaffold_improve_export_bundle(
        ...         ly, "job-x", eval_report_path=eval_p
        ...     )
        ...     ok = (out / "manifest.json").is_file()
        ...     td.cleanup()
        ...     return ok
        >>> _demo()
        True
    """
    export_root = improve_export_dir(layout, job_id)
    export_root.mkdir(parents=True, exist_ok=True)
    artefacts: list[str] = ["manifest.json"]
    if eval_report_path is not None and eval_report_path.is_file():
        transcript = export_root / "eval_transcript.json"
        shutil.copy2(eval_report_path, transcript)
        artefacts.append("eval_transcript.json")
    if patch_dir is not None and patch_dir.is_dir():
        bundle = export_root / "diff_bundle"
        if bundle.exists():
            shutil.rmtree(bundle)
        shutil.copytree(patch_dir, bundle)
        artefacts.append("diff_bundle/")
    manifest = {
        "schema_version": _EXPORT_SCHEMA_VERSION,
        "job_id": job_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ttl_days": ttl_days,
        "artefacts": artefacts,
    }
    manifest_path = export_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return export_root


def prune_stale_export_bundles(
    exports_parent: Path,
    *,
    retention_days: int,
    now_s: float | None = None,
) -> int:
    """Remove export bundle directories older than ``retention_days``.

    Args:
        exports_parent (Path): ``.sevn/improve/exports`` directory.
        retention_days (int): Minimum age in whole days before deletion.
        now_s (float | None): Optional clock injection for tests.

    Returns:
        int: Number of directories removed.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> import time
        >>> import os
        >>> td = Path(tempfile.mkdtemp())
        >>> parent = td / "exports"
        >>> jb = parent / "old_job"
        >>> jb.mkdir(parents=True)
        >>> old = time.time() - (40 * 86400)
        >>> os.utime(jb, (old, old))
        >>> prune_stale_export_bundles(parent, retention_days=30, now_s=time.time())
        1
    """
    if retention_days <= 0 or not exports_parent.is_dir():
        return 0
    cutoff = (now_s if now_s is not None else time.time()) - float(retention_days * 86400)
    removed = 0
    for child in exports_parent.iterdir():
        if not child.is_dir():
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime <= cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed
