from __future__ import annotations

import io
import json
import tarfile
import time
from pathlib import Path

from sevn.config.workspace_config import SandboxConfig, WorkspaceConfig
from sevn.security.sandbox_runtime import (
    load_snapshot_manifest_version,
    prune_workspace_snapshots,
    snapshot_tarball_format_supported,
    write_workspace_snapshot_tarball,
)
from sevn.workspace.layout import WorkspaceLayout


def _tarball_with_format_version(path: Path, *, format_version: int) -> Path:
    manifest = {
        "format_version": format_version,
        "created_unix_s": 0,
        "workspace_root": "/tmp",
        "exclude_llmignore": True,
    }
    with tarfile.open(path, mode="w:gz") as tar:
        raw = json.dumps(manifest, sort_keys=True).encode("utf-8")
        info = tarfile.TarInfo(name="snapshot-manifest.json")
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))
    return path


def test_snapshot_writes_manifest_roundtrip(tmp_path: Path) -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    cfg_path = tmp_path / "sevn.json"
    lay = WorkspaceLayout.from_config(cfg_path, cfg)
    ws = lay.content_root
    (ws / ".llmignore").mkdir()
    (ws / ".llmignore" / "secret.bin").write_bytes(b"zzz")
    (ws / "visible.txt").write_text("ok", encoding="utf-8")
    tarball = write_workspace_snapshot_tarball(lay, workspace_root=ws)
    assert tarball.is_file()
    assert load_snapshot_manifest_version(tarball) == 1
    assert snapshot_tarball_format_supported(tarball) is True


def test_unsupported_snapshot_format_not_supported(tmp_path: Path) -> None:
    snap_dir = tmp_path / "old.tar.gz"
    _tarball_with_format_version(snap_dir, format_version=99)
    assert load_snapshot_manifest_version(snap_dir) == 99
    assert snapshot_tarball_format_supported(snap_dir) is False


def test_prune_workspace_snapshots_keeps_newest(tmp_path: Path) -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        sandbox=SandboxConfig(snapshot_retention_count=2),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    cfg_path = tmp_path / "sevn.json"
    lay = WorkspaceLayout.from_config(cfg_path, cfg)
    base = lay.dot_sevn / "sandbox-snapshots"
    base.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(4):
        p = base / f"snapshot-test-{i}.tar.gz"
        p.write_bytes(b"")
        time.sleep(0.01)
        paths.append(p)
    removed = prune_workspace_snapshots(lay, cfg, glob_pattern="snapshot-test-*.tar.gz")
    assert len(removed) == 2
    remaining = list(base.glob("snapshot-test-*.tar.gz"))
    assert len(remaining) == 2
    assert set(remaining) == {paths[2], paths[3]}
