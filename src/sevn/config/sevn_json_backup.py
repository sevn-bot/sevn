"""Archive directory, migration, and retention for ``sevn.json`` versioned backups.

Module: sevn.config.sevn_json_backup
Depends: json, os, time, pathlib, sevn.config.sections.config_archive

Exports:
    config_backup_archive_dir — resolve archive directory path.
    migrate_legacy_config_backups — move legacy ``sevn.json.v*`` into archive dir.
    backup_previous_sevn_json — rename prior config into archive and prune.
    iter_config_backup_paths — list archived (+ legacy) backup files.
    effective_config_backup_settings — resolve ``config_archive.*`` from a document.
    prune_config_backups — apply keep-count and retention-day policy.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.config.sections.config_archive import ConfigArchiveWorkspaceConfig

CONFIG_BACKUP_ARCHIVE_DIR_NAME = "sevn.json.archive"
_CONFIG_BACKUP_GLOB = "sevn.json.v*"


def config_backup_archive_dir(sevn_json_path: Path) -> Path:
    """Return the ``sevn.json.archive/`` directory beside ``sevn.json``.

    Args:
        sevn_json_path (Path): Active ``sevn.json`` path.

    Returns:
        Path: Archive directory (may not exist yet).

    Examples:
        >>> from pathlib import Path
        >>> config_backup_archive_dir(Path("/tmp/w/sevn.json"))
        PosixPath('/tmp/w/sevn.json.archive')
    """

    return sevn_json_path.parent / CONFIG_BACKUP_ARCHIVE_DIR_NAME


def effective_config_backup_settings(
    doc: dict[str, Any] | None,
) -> ConfigArchiveWorkspaceConfig:
    """Resolve ``config_archive.*`` from a workspace document.

    Args:
        doc (dict[str, Any] | None): Workspace JSON document.

    Returns:
        ConfigArchiveWorkspaceConfig: Effective archive retention settings.

    Examples:
        >>> effective_config_backup_settings(None).keep_count
        5
    """

    from sevn.config.sections.config_archive import ConfigArchiveWorkspaceConfig

    if not doc:
        return ConfigArchiveWorkspaceConfig()
    raw = doc.get("config_archive")
    if not isinstance(raw, dict):
        return ConfigArchiveWorkspaceConfig()
    return ConfigArchiveWorkspaceConfig.model_validate(raw)


def migrate_legacy_config_backups(sevn_json_path: Path) -> int:
    """Move ``sevn.json.v*`` files beside the active config into ``sevn.json.archive/``.

    Args:
        sevn_json_path (Path): Active ``sevn.json`` path.

    Returns:
        int: Number of legacy files moved.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> sj = td / "sevn.json"
        >>> legacy = td / "sevn.json.v1"
        >>> _ = legacy.write_text('{"schema_version": 1}\\n', encoding="utf-8")
        >>> migrate_legacy_config_backups(sj)
        1
    """

    parent = sevn_json_path.parent
    if not parent.is_dir():
        return 0
    archive_dir = config_backup_archive_dir(sevn_json_path)
    archive_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for legacy in sorted(parent.glob(_CONFIG_BACKUP_GLOB)):
        if not legacy.is_file():
            continue
        target = archive_dir / legacy.name
        if target.is_file():
            suffix = 0
            collision_target = target
            while collision_target.is_file():
                suffix += 1
                collision_target = archive_dir / f"{legacy.name}.legacy{suffix}"
            os.replace(legacy, collision_target)
            moved += 1
            continue
        os.replace(legacy, target)
        moved += 1
    return moved


def _resolve_archive_backup_path(sevn_json_path: Path, old_schema: int) -> Path:
    """Pick a free ``sevn.json.v{schema}[.N]`` path under ``sevn.json.archive/``.

    Args:
        sevn_json_path (Path): Active ``sevn.json`` path.
        old_schema (int): Schema version of the file being archived.

    Returns:
        Path: Unused backup destination inside the archive directory.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> sj = td / "sevn.json"
        >>> _resolve_archive_backup_path(sj, 1).name
        'sevn.json.v1'
    """

    archive_dir = config_backup_archive_dir(sevn_json_path)
    archive_dir.mkdir(parents=True, exist_ok=True)
    backup = archive_dir / f"sevn.json.v{old_schema}"
    target_backup = backup
    suffix = 0
    while target_backup.is_file():
        suffix += 1
        target_backup = archive_dir / f"sevn.json.v{old_schema}.{suffix}"
    return target_backup


def _backup_mtime(path: Path) -> float:
    """Return ``st_mtime`` for ``path``, or ``0.0`` when stat fails.

    Args:
        path (Path): Backup file path.

    Returns:
        float: Modification time in seconds.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> p = td / "x"
        >>> _ = p.write_text("a", encoding="utf-8")
        >>> _backup_mtime(p) > 0
        True
    """

    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def prune_config_backups(
    sevn_json_path: Path,
    *,
    settings: ConfigArchiveWorkspaceConfig,
    now_s: float | None = None,
) -> int:
    """Prune archived ``sevn.json.v*`` files per keep-count and retention-day policy.

    Args:
        sevn_json_path (Path): Active ``sevn.json`` path.
        settings (ConfigArchiveWorkspaceConfig): Retention settings from the prior config.
        now_s (float | None): Optional clock injection for tests.

    Returns:
        int: Number of backup files removed.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.sections.config_archive import ConfigArchiveWorkspaceConfig
        >>> td = Path(tempfile.mkdtemp())
        >>> sj = td / "sevn.json"
        >>> archive = config_backup_archive_dir(sj)
        >>> archive.mkdir()
        >>> for idx in range(3):
        ...     _ = (archive / f"sevn.json.v1.{idx}").write_text("{}", encoding="utf-8")
        >>> prune_config_backups(sj, settings=ConfigArchiveWorkspaceConfig(keep_count=1))
        2
    """

    archive_dir = config_backup_archive_dir(sevn_json_path)
    if not archive_dir.is_dir():
        return 0
    backups = [
        path
        for path in archive_dir.iterdir()
        if path.is_file() and path.name.startswith("sevn.json.v")
    ]
    if not backups:
        return 0

    clock = now_s if now_s is not None else time.time()
    to_delete: set[Path] = set()

    if settings.retention_days > 0:
        cutoff = clock - float(settings.retention_days * 86400)
        for path in backups:
            if _backup_mtime(path) <= cutoff:
                to_delete.add(path)

    if settings.keep_count > 0:
        sorted_by_mtime = sorted(backups, key=_backup_mtime, reverse=True)
        for path in sorted_by_mtime[settings.keep_count :]:
            to_delete.add(path)

    removed = 0
    for path in to_delete:
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def backup_previous_sevn_json(sevn_json_path: Path) -> Path | None:
    """Move the current ``sevn.json`` aside into ``sevn.json.archive/`` and prune.

    Args:
        sevn_json_path (Path): Active ``sevn.json`` path.

    Returns:
        Path | None: Archive path when a prior file was moved, else ``None``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> p = td / "sevn.json"
        >>> _ = p.write_text('{"schema_version": 1}\\n', encoding="utf-8")
        >>> bak = backup_previous_sevn_json(p)
        >>> bak is not None and not p.is_file()
        True
    """

    if not sevn_json_path.is_file():
        return None
    migrate_legacy_config_backups(sevn_json_path)
    try:
        old_doc = json.loads(sevn_json_path.read_text(encoding="utf-8"))
        old_schema = int(old_doc.get("schema_version", 1))
        settings = effective_config_backup_settings(old_doc)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        old_schema = 1
        settings = effective_config_backup_settings(None)
    target_backup = _resolve_archive_backup_path(sevn_json_path, old_schema)
    os.replace(sevn_json_path, target_backup)
    prune_config_backups(sevn_json_path, settings=settings)
    return target_backup


def iter_config_backup_paths(sevn_json_path: Path) -> list[Path]:
    """List ``sevn.json.v*`` backups in the archive dir and legacy beside-config paths.

    Args:
        sevn_json_path (Path): Active ``sevn.json`` path.

    Returns:
        list[Path]: Sorted backup file paths (archive preferred over legacy duplicates).

    Examples:
        >>> from pathlib import Path
        >>> iter_config_backup_paths(Path("/tmp/none/sevn.json"))
        []
    """

    parent = sevn_json_path.parent
    archive_dir = config_backup_archive_dir(sevn_json_path)
    by_name: dict[str, Path] = {}
    for directory in (archive_dir, parent):
        if not directory.is_dir():
            continue
        for path in directory.glob(_CONFIG_BACKUP_GLOB):
            if path.is_file() and path.name not in by_name:
                by_name[path.name] = path
    return sorted(by_name.values(), key=lambda item: item.name)


__all__ = [
    "CONFIG_BACKUP_ARCHIVE_DIR_NAME",
    "backup_previous_sevn_json",
    "config_backup_archive_dir",
    "effective_config_backup_settings",
    "iter_config_backup_paths",
    "migrate_legacy_config_backups",
    "prune_config_backups",
]
