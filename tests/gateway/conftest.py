"""Shared fixtures for gateway tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sevn.config.loader import load_workspace

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.workspace.layout import WorkspaceLayout


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Iterator[tuple[WorkspaceConfig, WorkspaceLayout]]:
    root = tmp_path / "repo"
    root.mkdir()
    sj = root / "sevn.json"
    sj.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    cfg, layout = load_workspace(sevn_json=sj)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)
    return cfg, layout
