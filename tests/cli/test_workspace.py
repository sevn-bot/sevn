"""Tests for ``sevn.cli.workspace``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.cli.errors import CliPreconditionError
from sevn.cli.workspace import bound_sevn_json_path, load_bound_workspace


def test_load_bound_workspace_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "sevnhome"
    home.mkdir()
    monkeypatch.setenv("SEVN_HOME", str(home))
    with pytest.raises(CliPreconditionError):
        load_bound_workspace()
    assert bound_sevn_json_path() == home / "workspace" / "sevn.json"


def test_load_bound_workspace_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "sevnhome"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    doc = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    (ws / "sevn.json").write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))
    bw = load_bound_workspace()
    assert bw.config.schema_version == 1
