"""TTL pruning for improve bundles (`specs/33-self-improvement.md` §3.5-§10.2).

Module: sevn.self_improve.retention
Depends: pathlib, shutil, time

Exports:
    prune_stale_job_bundles — delete aged ``<job_id>/`` directories under ``improve/``.
"""

from __future__ import annotations

import shutil
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def prune_stale_job_bundles(
    improve_dir: Path,
    *,
    retention_days: int,
    now_s: float | None = None,
) -> int:
    """Remove job bundle directories older than ``retention_days``.

    Never deletes ``self_improve_audit.jsonl`` or ``retention.toml`` at the root.

        Args:
        improve_dir (Path): ``.sevn/improve`` directory.
        retention_days (int): Minimum age in whole days before deletion elapses.
        now_s (float | None): Optional clock injection for tests.

        Returns:
            int: Number of directories removed.

        Examples:
            >>> from pathlib import Path
            >>> import tempfile
            >>> import time
            >>> td = Path(tempfile.mkdtemp())
            >>> root = td / "improve"
            >>> jb = root / "job_a"
            >>> jb.mkdir(parents=True)
            >>> old = time.time() - (40 * 86400)
            >>> import os
            >>> os.utime(jb, (old, old))
            >>> prune_stale_job_bundles(root, retention_days=30, now_s=time.time())
            1
    """
    if retention_days <= 0 or not improve_dir.is_dir():
        return 0
    cutoff = (now_s if now_s is not None else time.time()) - float(retention_days * 86400)
    removed = 0
    for child in improve_dir.iterdir():
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
