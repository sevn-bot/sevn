"""Tests for rotated service log retention sweeper."""

from __future__ import annotations

import os
import time
from pathlib import Path

from sevn.config.workspace_config import LoggingWorkspaceConfig, WorkspaceConfig
from sevn.logging.retention import (
    archive_rotated_log,
    effective_logging_config,
    iter_expired_rotated_logs,
    sweep_rotated_service_logs,
)


def _backdate(path: Path, *, days: float) -> None:
    old = time.time() - (days * 86400)
    os.utime(path, (old, old))


def test_iter_expired_rotated_logs_respects_retention_days(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    expired = logs / "gateway-20260101T000000Z.log"
    fresh = logs / "proxy-20260102T000000Z.log"
    active = logs / "gateway.log"
    expired.write_text("old\n", encoding="utf-8")
    fresh.write_text("new\n", encoding="utf-8")
    active.write_text("active\n", encoding="utf-8")
    _backdate(expired, days=20)
    _backdate(fresh, days=1)

    found = iter_expired_rotated_logs(logs, retention_days=10, now_s=time.time())

    assert expired in found
    assert fresh not in found
    assert active not in found


def test_sweep_delete_mode_removes_expired_rotated_logs(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    old = logs / "gateway-20260101T000000Z.log"
    old.write_text("x", encoding="utf-8")
    _backdate(old, days=1)
    ws = WorkspaceConfig(
        schema_version=1,
        logging=LoggingWorkspaceConfig(retention_days=0, archive_mode="delete"),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )

    result = sweep_rotated_service_logs(
        logs,
        content_root=tmp_path,
        workspace=ws,
        now_s=time.time(),
    )

    assert result.archived == 1
    assert not old.exists()


def test_sweep_copy_mode_archives_then_deletes_source(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    old = logs / "proxy-20260101T000000Z.log"
    old.write_text("proxy line\n", encoding="utf-8")
    _backdate(old, days=1)
    ws = WorkspaceConfig(
        schema_version=1,
        logging=LoggingWorkspaceConfig(
            retention_days=0,
            archive_mode="copy",
            archive_destination="logs/archive",
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )

    result = sweep_rotated_service_logs(
        logs,
        content_root=tmp_path,
        workspace=ws,
        now_s=time.time(),
    )

    archived = tmp_path / "logs" / "archive" / old.name
    assert result.archived == 1
    assert not old.exists()
    assert archived.read_text(encoding="utf-8") == "proxy line\n"


def test_archive_rotated_log_r2_stub_keeps_local_file(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    src = logs / "gateway-20260101T000000Z.log"
    src.write_text("keep\n", encoding="utf-8")
    cfg = LoggingWorkspaceConfig(
        archive_mode="r2",
        cloud={"r2": {"bucket_ref": "${SECRET:logs/r2-bucket}"}},
    )

    removed = archive_rotated_log(src, content_root=tmp_path, logging_cfg=cfg)

    assert removed is False
    assert src.exists()


def test_effective_logging_config_applies_defaults() -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    cfg = effective_logging_config(ws)
    assert cfg.retention_days == 10
    assert cfg.archive_mode == "copy"
    assert cfg.archive_destination == "logs/archive"
