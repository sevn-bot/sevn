"""Workspace layout validation (`specs/02-config-and-workspace.md` §2.6)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from loguru import logger
from starlette.testclient import TestClient

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import (
    TraceSinkEntry,
    TracingConfig,
    WorkspaceConfig,
)
from sevn.data.skills_index import REPO_STARTER_INDEX, read_skills_index
from sevn.gateway.http_server import create_app
from sevn.onboarding.seed import seed_narrative_templates
from sevn.storage.paths import traces_sqlite_path
from sevn.workspace.layout import WorkspaceLayout
from sevn.workspace.layout_validate import (
    CANONICAL_WORKSPACE_DIRS,
    CANONICAL_WORKSPACE_MD_FILES,
    WorkspaceLayoutValidationResult,
    validate_workspace_layout,
    validate_workspace_layout_at_boot,
)

_BOOTSTRAP_COMPLETE_USER_MD = """\
## Profile

- **Name:** Alex
- **Role:** operator
- **Timezone:** UTC

## Communication

- **Style:** brief
- **Language:** English

## Preferences

- none
"""


def _write_intact_workspace(root: Path) -> None:
    for name in CANONICAL_WORKSPACE_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    for name in CANONICAL_WORKSPACE_MD_FILES:
        if name == "IDENTITY.md":
            (root / name).write_text("## Name\n\ntestmee\n", encoding="utf-8")
        elif name == "USER.md":
            (root / name).write_text(_BOOTSTRAP_COMPLETE_USER_MD, encoding="utf-8")
        else:
            (root / name).write_text(f"# {name}\n", encoding="utf-8")


def test_validate_workspace_layout_ok_when_intact(tmp_path: Path) -> None:
    _write_intact_workspace(tmp_path)
    layout = WorkspaceLayout(tmp_path / "sevn.json", tmp_path)
    result = validate_workspace_layout(layout)
    assert result.ok
    assert result.missing_dirs == ()
    assert result.missing_files == ()


def test_validate_workspace_layout_reports_missing_logs_dir(tmp_path: Path) -> None:
    _write_intact_workspace(tmp_path)
    import shutil

    shutil.rmtree(tmp_path / "logs")
    layout = WorkspaceLayout(tmp_path / "sevn.json", tmp_path)
    result = validate_workspace_layout(layout)
    assert not result.ok
    assert result.missing_dirs == ("logs",)


def test_validate_workspace_layout_reports_missing_workspace_md(tmp_path: Path) -> None:
    _write_intact_workspace(tmp_path)
    (tmp_path / "WORKSPACE.md").unlink()
    layout = WorkspaceLayout(tmp_path / "sevn.json", tmp_path)
    result = validate_workspace_layout(layout)
    assert not result.ok
    assert result.missing_files == ("WORKSPACE.md",)


def test_seed_writes_workspace_md(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    written = seed_narrative_templates(
        sevn_json,
        {
            "schema_version": 1,
            "workspace_root": ".",
            "agent": {"display_name": "Nova"},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    assert any(p.name == "WORKSPACE.md" for p in written)
    body = (tmp_path / "WORKSPACE.md").read_text(encoding="utf-8")
    assert "Canonical" in body or "canonical" in body
    assert ".sevn/" in body


@pytest.mark.asyncio
async def test_boot_emits_layout_ok_for_intact_workspace(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    _write_intact_workspace(tmp_path)
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        tracing=TracingConfig(sinks=[TraceSinkEntry.model_validate({"type": "sqlite"})]),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)
    app = create_app(workspace=workspace_cfg, layout=layout)
    with TestClient(app):
        pass
    db_path = traces_sqlite_path(layout.dot_sevn)
    conn = sqlite3.connect(db_path)
    try:
        kinds = {
            str(row[0])
            for row in conn.execute(
                "SELECT kind FROM trace_events WHERE kind LIKE 'workspace.layout%'",
            )
        }
        assert "workspace.layout_ok" in kinds
    finally:
        conn.close()


def test_boot_emits_layout_mismatch_when_logs_missing(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    _write_intact_workspace(tmp_path)
    import shutil

    shutil.rmtree(tmp_path / "logs")
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        tracing=TracingConfig(sinks=[TraceSinkEntry.model_validate({"type": "sqlite"})]),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)
    app = create_app(workspace=workspace_cfg, layout=layout)
    with TestClient(app):
        pass
    db_path = traces_sqlite_path(layout.dot_sevn)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT attrs_json FROM trace_events
            WHERE kind = 'workspace.layout_mismatch'
            ORDER BY ts_start_ns DESC LIMIT 1
            """,
        ).fetchone()
        assert row is not None
        attrs = json.loads(str(row[0]))
        assert "logs" in attrs["missing_dirs"]
    finally:
        conn.close()


def test_boot_seeds_skills_index_when_missing(tmp_path: Path) -> None:
    """Gateway boot copies ``skills/INDEX.md`` when the workspace lacks one."""
    if not REPO_STARTER_INDEX.is_file():
        pytest.skip("starter INDEX not available in this checkout")
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    _write_intact_workspace(tmp_path)
    ws_index = tmp_path / "skills" / "INDEX.md"
    assert not ws_index.is_file()
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        tracing=TracingConfig(sinks=[TraceSinkEntry.model_validate({"type": "sqlite"})]),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)
    app = create_app(workspace=workspace_cfg, layout=layout)
    with TestClient(app):
        pass
    assert ws_index.is_file()
    seeded = read_skills_index(workspace_root=tmp_path)
    assert len(seeded) > 0


@pytest.mark.asyncio
async def test_boot_layout_logs_per_path_and_skips_warning_when_intact(
    tmp_path: Path,
) -> None:
    _write_intact_workspace(tmp_path)
    layout = WorkspaceLayout(tmp_path / "sevn.json", tmp_path)
    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="INFO")
    try:
        result = await validate_workspace_layout_at_boot(
            layout=layout,
            trace=NullTraceSink(),
        )
        assert result.ok
        seeded_lines = [m for m in messages if "workspace_layout seeded" in m]
        assert any("path=logs status=exists" in m for m in seeded_lines)
        assert not any("workspace layout mismatch" in m for m in messages)
    finally:
        logger.remove(handler_id)


@pytest.mark.asyncio
async def test_boot_layout_warns_only_for_post_seed_missing_paths(tmp_path: Path) -> None:
    # Wave 6: "workspace layout mismatch" was downgraded from WARNING to INFO so that
    # the agent is not baited into chasing index regeneration when reading logs.
    # The assertion now checks the INFO sink instead of the WARNING sink.
    _write_intact_workspace(tmp_path)
    import shutil

    shutil.rmtree(tmp_path / "logs")
    layout = WorkspaceLayout(tmp_path / "sevn.json", tmp_path)
    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="INFO")
    warning_messages: list[str] = []
    warn_id = logger.add(warning_messages.append, format="{message}", level="WARNING")

    try:
        result = await validate_workspace_layout_at_boot(
            layout=layout,
            trace=NullTraceSink(),
        )
        assert not result.ok
        assert "logs" in result.missing_dirs
        assert any("path=logs status=skipped" in m for m in messages)
        # Downgraded from WARNING to INFO (Wave 6: stop baiting the agent with
        # actionable-sounding WARNING lines it cannot fix during a turn).
        assert any("workspace layout mismatch" in m for m in messages)
        assert not any("workspace layout mismatch" in m for m in warning_messages)
    finally:
        logger.remove(handler_id)
        logger.remove(warn_id)


def test_boot_layout_validation_invoked(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)
    mock_validate = AsyncMock(return_value=WorkspaceLayoutValidationResult((), ()))
    with patch(
        "sevn.gateway.http_server.run_workspace_layout_validation",
        new=mock_validate,
    ):
        app = create_app(workspace=workspace_cfg, layout=layout)
        with TestClient(app):
            pass
        assert mock_validate.await_count == 1
