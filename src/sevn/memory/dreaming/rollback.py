"""Rollback helpers (`specs/31-memory-dreaming.md` §2.1 `rollback_last_auto_batch`).

Module: sevn.memory.dreaming.rollback
Depends: json, pathlib

Exports:
    latest_promoted_manifest — newest promoted JSON path.
    rollback_manifest — truncate ``MEMORY.md`` for one manifest.
    rollback_last_auto_batch — operator shortcut for last auto batch.
"""

from __future__ import annotations

import json
from pathlib import Path

from sevn.memory.dreaming.models import PromotedBatchManifest
from sevn.memory.dreaming.promoter import dreams_dir


def latest_promoted_manifest(workspace_root: Path) -> Path | None:
    """Return newest ``promoted/*.json`` by mtime or None.

    Args:
        workspace_root (Path): Workspace content root.

    Returns:
        Path | None: Manifest path when any exist.

    Examples:
        >>> from pathlib import Path
        >>> latest_promoted_manifest(Path("/nonexistent")) is None
        True
    """
    prom = dreams_dir(workspace_root) / "promoted"
    if not prom.is_dir():
        return None
    files = sorted(prom.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def rollback_manifest(workspace_root: Path, manifest_path: Path) -> None:
    """Truncate ``MEMORY.md`` using manifest pre-bytes.

    Args:
        workspace_root (Path): Workspace content root.
        manifest_path (Path): ``promoted/<run_id>.json`` file.

    Examples:
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> from sevn.memory.dreaming.models import PromotedBatchManifest, PromotedManifestRow, MemoryMdAnchor
        >>> with TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     m = root / "MEMORY.md"
        ...     _ = m.write_text("abcd", encoding="utf-8")
        ...     man = root / "man.json"
        ...     payload = PromotedBatchManifest(
        ...         run_id="r",
        ...         mode="auto",
        ...         memory_md_pre_bytes=2,
        ...         memory_md_post_bytes=4,
        ...         rows=[],
        ...     )
        ...     _ = man.write_text(payload.model_dump_json(), encoding="utf-8")
        ...     rollback_manifest(root, man)
        ...     m.read_text(encoding="utf-8")
        'ab'
    """
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = PromotedBatchManifest.model_validate(data)
    memory_path = workspace_root / "MEMORY.md"
    if not memory_path.is_file():
        return
    raw = memory_path.read_bytes()
    cut = manifest.memory_md_pre_bytes
    memory_path.write_bytes(raw[:cut])


def rollback_last_auto_batch(workspace_root: Path) -> None:
    """Restore ``MEMORY.md`` using the latest promoted manifest.

    Args:
        workspace_root (Path): Workspace content root.

    Examples:
        >>> from pathlib import Path
        >>> rollback_last_auto_batch(Path(".")) is None
        True
    """
    path = latest_promoted_manifest(workspace_root)
    if path is None:
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    manifest = PromotedBatchManifest.model_validate(data)
    if manifest.mode != "auto":
        return
    rollback_manifest(workspace_root, path)
