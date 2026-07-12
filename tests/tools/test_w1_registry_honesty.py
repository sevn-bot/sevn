"""Registry honesty tests: semantic_search only registers when indexer is genuinely available."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.second_brain.witchcraft_bridge import WitchcraftConfig
from sevn.tools.base import ToolExecutor
from sevn.tools.semantic_search import (
    register_semantic_search_tool,
    run_semantic_search,
    witchcraft_tool_enabled,
)

# ---------------------------------------------------------------------------
# witchcraft_tool_enabled
# ---------------------------------------------------------------------------


def test_witchcraft_tool_enabled_false_by_default() -> None:
    cfg = WorkspaceConfig.minimal()
    assert witchcraft_tool_enabled(cfg) is False


def test_witchcraft_tool_enabled_true_when_set() -> None:
    cfg = WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "witchcraft_enabled": True,
        }
    )
    assert witchcraft_tool_enabled(cfg) is True


def test_witchcraft_tool_enabled_none_config_false() -> None:
    assert witchcraft_tool_enabled(None) is False


# ---------------------------------------------------------------------------
# register_semantic_search_tool — quarantine honesty
# ---------------------------------------------------------------------------


def _make_executor() -> ToolExecutor:
    return ToolExecutor()


def _cfg_enabled() -> WorkspaceConfig:
    return WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "witchcraft_enabled": True,
        }
    )


def test_register_skipped_when_not_enabled() -> None:
    exe = _make_executor()
    cfg = WorkspaceConfig.minimal()
    register_semantic_search_tool(exe, cfg)
    names = {d.name for d in exe.definitions()}
    assert "semantic_search" not in names


def test_register_skipped_when_no_binary() -> None:
    exe = _make_executor()
    cfg = _cfg_enabled()
    with patch("sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value=None):
        register_semantic_search_tool(exe, cfg)
    names = {d.name for d in exe.definitions()}
    assert "semantic_search" not in names


def test_register_skipped_when_binary_but_db_missing(tmp_path: Path) -> None:
    exe = _make_executor()
    cfg = WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "witchcraft_enabled": True,
            "witchcraft": {"db_path": str(tmp_path / "no.sqlite")},
        }
    )
    with patch(
        "sevn.second_brain.witchcraft_bridge._witchcraft_binary",
        return_value="/usr/bin/witchcraft",
    ):
        register_semantic_search_tool(exe, cfg)
    names = {d.name for d in exe.definitions()}
    assert "semantic_search" not in names


def test_register_succeeds_when_binary_and_db_present(tmp_path: Path) -> None:
    db = tmp_path / "w.sqlite"
    db.write_bytes(b"")
    cfg = WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "witchcraft_enabled": True,
            "witchcraft": {"db_path": str(db)},
        }
    )
    exe = _make_executor()
    with patch(
        "sevn.second_brain.witchcraft_bridge._witchcraft_binary",
        return_value="/usr/bin/witchcraft",
    ):
        register_semantic_search_tool(exe, cfg)
    names = {d.name for d in exe.definitions()}
    assert "semantic_search" in names


# ---------------------------------------------------------------------------
# run_semantic_search — unavailability returns error, not raises
# ---------------------------------------------------------------------------


def test_run_semantic_search_no_binary_returns_error(tmp_path: Path) -> None:
    with patch("sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value=None):
        hits, err, _age = run_semantic_search(
            tmp_path, query="test", limit=5, mode="hybrid", source="all"
        )
    assert hits is None
    assert err is not None
    assert "unavailable" in err.lower()


def test_run_semantic_search_no_cfg_returns_error(tmp_path: Path) -> None:
    with patch(
        "sevn.second_brain.witchcraft_bridge._witchcraft_binary",
        return_value="/usr/bin/witchcraft",
    ):
        hits, err, _age = run_semantic_search(
            tmp_path, query="test", limit=5, mode="hybrid", source="all", witchcraft_cfg=None
        )
    assert hits is None
    assert err is not None


def test_run_semantic_search_with_monkeypatched_indexer(tmp_path: Path) -> None:
    db = tmp_path / "w.sqlite"
    db.write_bytes(b"")
    cfg = WitchcraftConfig(db_path=str(db))
    fake_scores = [{"origin": "user", "path": "notes.md", "score": 0.8}]
    fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(fake_scores))

    with (
        patch(
            "sevn.second_brain.witchcraft_bridge._witchcraft_binary",
            return_value="/usr/bin/witchcraft",
        ),
        patch(
            "sevn.second_brain.witchcraft_bridge.subprocess.run",
            return_value=fake_result,
        ),
    ):
        hits, err, age = run_semantic_search(
            tmp_path,
            query="notes",
            limit=5,
            mode="hybrid",
            source="all",
            witchcraft_cfg=cfg,
        )

    assert err is None
    assert hits is not None
    assert len(hits) == 1
    assert hits[0]["path"] == "notes.md"
    assert hits[0]["score"] == pytest.approx(0.8)
    assert age is not None


# ---------------------------------------------------------------------------
# Trace attr: witchcraft.index_age_s is returned
# ---------------------------------------------------------------------------


def test_run_semantic_search_returns_age_on_failure(tmp_path: Path) -> None:
    db = tmp_path / "w.sqlite"
    db.write_bytes(b"")
    cfg = WitchcraftConfig(db_path=str(db))
    with patch("sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value=None):
        _hits, _err, age = run_semantic_search(
            tmp_path, query="q", limit=5, mode="hybrid", source="all", witchcraft_cfg=cfg
        )
    assert age is None or isinstance(age, float)
