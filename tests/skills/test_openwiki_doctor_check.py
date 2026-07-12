"""Tests for OpenWiki doctor probes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.skills.openwiki_doctor_check import probe_openwiki_skill_checks_async


@pytest.mark.asyncio
async def test_probe_skips_when_skill_disabled(tmp_path: Path) -> None:
    """No rows when ``skills.openwiki.enabled`` is false."""
    cfg = WorkspaceConfig(schema_version=1, gateway={"token": "t"})
    rows = await probe_openwiki_skill_checks_async(cfg, content_root=tmp_path)
    assert rows == []


@pytest.mark.asyncio
async def test_probe_reports_cli_and_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enabled skill emits CLI and credential rows."""
    cfg = WorkspaceConfig(
        schema_version=1,
        skills={"openwiki": {"enabled": True, "provider": "openrouter"}},
        gateway={"token": "t"},
    )
    monkeypatch.setattr(
        "sevn.skills.openwiki_doctor_check.shutil.which", lambda _name: "/usr/bin/openwiki"
    )
    with patch(
        "sevn.skills.openwiki_doctor_check.openwiki_credentials_resolved",
        new=AsyncMock(return_value=(True, "auto-mapped assigned provider secret for 'openrouter'")),
    ):
        rows = await probe_openwiki_skill_checks_async(cfg, content_root=tmp_path)
    assert len(rows) == 2
    assert rows[0].check_id == "openwiki_cli"
    assert rows[0].ok is True
    assert rows[1].check_id == "openwiki_credentials"
    assert rows[1].ok is True


@pytest.mark.asyncio
async def test_probe_missing_cli_and_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing CLI and credentials produce warn rows with hints."""
    cfg = WorkspaceConfig(
        schema_version=1,
        skills={"openwiki": {"enabled": True}},
        gateway={"token": "t"},
    )
    monkeypatch.setattr("sevn.skills.openwiki_doctor_check.shutil.which", lambda _name: None)
    with patch(
        "sevn.skills.openwiki_doctor_check.openwiki_credentials_resolved",
        new=AsyncMock(return_value=(False, "missing credentials")),
    ):
        rows = await probe_openwiki_skill_checks_async(cfg, content_root=tmp_path)
    assert rows[0].ok is False
    assert rows[0].hint is not None
    assert rows[1].ok is False
    assert rows[1].hint is not None
