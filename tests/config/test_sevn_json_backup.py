"""Unit tests for ``sevn.config.sevn_json_backup`` retention and migration."""

from __future__ import annotations

import json
import time
from pathlib import Path

from sevn.config.sections.config_archive import ConfigArchiveWorkspaceConfig
from sevn.config.sevn_json_backup import (
    backup_previous_sevn_json,
    config_backup_archive_dir,
    migrate_legacy_config_backups,
    prune_config_backups,
)


def test_migrate_legacy_collision_preserves_both_files(tmp_path: Path) -> None:
    """Legacy migration must not unlink an archive file when names collide."""
    sevn_json = tmp_path / "sevn.json"
    legacy = tmp_path / "sevn.json.v1"
    archive_dir = config_backup_archive_dir(sevn_json)
    archive_dir.mkdir(parents=True)
    existing = archive_dir / "sevn.json.v1"
    existing.write_text('{"schema_version": 1, "note": "archived"}\n', encoding="utf-8")
    legacy.write_text('{"schema_version": 1, "note": "legacy"}\n', encoding="utf-8")

    moved = migrate_legacy_config_backups(sevn_json)

    assert moved == 1
    assert existing.read_text(encoding="utf-8") == '{"schema_version": 1, "note": "archived"}\n'
    preserved = list(archive_dir.glob("sevn.json.v1*"))
    assert len(preserved) == 2
    assert legacy.exists() is False


def test_prune_config_backups_keep_count(tmp_path: Path) -> None:
    """Keep-count pruning removes oldest backups beyond the limit."""
    sevn_json = tmp_path / "sevn.json"
    archive_dir = config_backup_archive_dir(sevn_json)
    archive_dir.mkdir(parents=True)
    now = time.time()
    for idx in range(4):
        path = archive_dir / f"sevn.json.v1.{idx}"
        path.write_text("{}", encoding="utf-8")
        path.touch()
        os_mtimes = now - float(idx * 3600)
        import os

        os.utime(path, (os_mtimes, os_mtimes))

    removed = prune_config_backups(
        sevn_json,
        settings=ConfigArchiveWorkspaceConfig(keep_count=2),
        now_s=now,
    )

    assert removed == 2
    remaining = sorted(p.name for p in archive_dir.iterdir() if p.is_file())
    assert len(remaining) == 2


def test_keep_count_zero_disables_count_pruning(tmp_path: Path) -> None:
    """``keep_count: 0`` means unlimited by count; only retention_days applies."""
    sevn_json = tmp_path / "sevn.json"
    archive_dir = config_backup_archive_dir(sevn_json)
    archive_dir.mkdir(parents=True)
    for idx in range(3):
        (archive_dir / f"sevn.json.v1.{idx}").write_text("{}", encoding="utf-8")

    removed = prune_config_backups(
        sevn_json,
        settings=ConfigArchiveWorkspaceConfig(keep_count=0),
    )

    assert removed == 0
    assert len(list(archive_dir.iterdir())) == 3


def test_backup_previous_archives_and_prunes(tmp_path: Path) -> None:
    """Backup moves active config into archive and applies retention."""
    sevn_json = tmp_path / "sevn.json"
    doc = {
        "schema_version": 1,
        "config_archive": {"keep_count": 1, "retention_days": 0},
    }
    sevn_json.write_text(json.dumps(doc) + "\n", encoding="utf-8")
    archive_dir = config_backup_archive_dir(sevn_json)
    archive_dir.mkdir(parents=True)
    (archive_dir / "sevn.json.v1.old").write_text("{}\n", encoding="utf-8")

    backup_path = backup_previous_sevn_json(sevn_json)

    assert backup_path is not None
    assert sevn_json.exists() is False
    assert backup_path.parent == archive_dir
    remaining = [p for p in archive_dir.iterdir() if p.is_file()]
    assert len(remaining) == 1
