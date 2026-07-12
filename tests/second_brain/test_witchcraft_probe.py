"""Tests for WitchcraftConfig parsing and witchcraft_indexer_available probe."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from sevn.second_brain.witchcraft_bridge import (
    WitchcraftConfig,
    build_wiki_index,
    index_age_seconds,
    maybe_reindex_on_startup,
    maybe_semantic_scores,
    semantic_mode_allowed,
    witchcraft_indexer_available,
)

# ---------------------------------------------------------------------------
# WitchcraftConfig.from_workspace_config
# ---------------------------------------------------------------------------


class _FakeConfig:
    """Minimal workspace config stand-in with model_extra."""

    def __init__(self, extra: dict) -> None:
        self.model_extra = extra


def test_from_workspace_config_none_returns_none() -> None:
    assert WitchcraftConfig.from_workspace_config(None) is None


def test_from_workspace_config_not_enabled_returns_none() -> None:
    cfg = _FakeConfig({"witchcraft_enabled": False})
    assert WitchcraftConfig.from_workspace_config(cfg) is None


def test_from_workspace_config_enabled_defaults() -> None:
    cfg = _FakeConfig({"witchcraft_enabled": True})
    wc = WitchcraftConfig.from_workspace_config(cfg)
    assert wc is not None
    assert wc.db_path == ".sevn/witchcraft.sqlite"
    assert wc.reindex_on_startup is False
    assert wc.index_messages is False
    assert wc.model_backend == "default"


def test_from_workspace_config_custom_fields() -> None:
    cfg = _FakeConfig(
        {
            "witchcraft_enabled": True,
            "witchcraft": {
                "db_path": "/custom/w.db",
                "reindex_on_startup": True,
                "index_messages": True,
                "model_backend": "fast",
            },
        }
    )
    wc = WitchcraftConfig.from_workspace_config(cfg)
    assert wc is not None
    assert wc.db_path == "/custom/w.db"
    assert wc.reindex_on_startup is True
    assert wc.index_messages is True
    assert wc.model_backend == "fast"


def test_from_workspace_config_bad_witchcraft_dict_falls_back_to_defaults() -> None:
    cfg = _FakeConfig({"witchcraft_enabled": True, "witchcraft": "not-a-dict"})
    wc = WitchcraftConfig.from_workspace_config(cfg)
    assert wc is not None
    assert wc.db_path == ".sevn/witchcraft.sqlite"


# ---------------------------------------------------------------------------
# witchcraft_indexer_available — no binary
# ---------------------------------------------------------------------------


def test_indexer_available_no_binary_returns_false() -> None:
    with patch("sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value=None):
        assert witchcraft_indexer_available() is False


def test_indexer_available_binary_no_cfg_returns_true() -> None:
    with patch(
        "sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value="/usr/bin/witchcraft"
    ):
        assert witchcraft_indexer_available() is True


def test_indexer_available_binary_cfg_db_missing_returns_false(tmp_path: Path) -> None:
    cfg = WitchcraftConfig(db_path="no.sqlite")
    with patch(
        "sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value="/usr/bin/witchcraft"
    ):
        assert witchcraft_indexer_available(cfg, tmp_path) is False


def test_indexer_available_binary_cfg_db_present_returns_true(tmp_path: Path) -> None:
    db = tmp_path / "w.sqlite"
    db.write_bytes(b"")
    cfg = WitchcraftConfig(db_path="w.sqlite")
    with patch(
        "sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value="/usr/bin/witchcraft"
    ):
        assert witchcraft_indexer_available(cfg, tmp_path) is True


# ---------------------------------------------------------------------------
# semantic_mode_allowed — freshness gate
# ---------------------------------------------------------------------------


def test_semantic_mode_allowed_no_binary_false() -> None:
    with patch("sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value=None):
        assert semantic_mode_allowed() is False


def test_semantic_mode_allowed_no_cfg_false() -> None:
    with patch(
        "sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value="/usr/bin/witchcraft"
    ):
        assert semantic_mode_allowed() is False


def test_semantic_mode_allowed_stale_db_false(tmp_path: Path) -> None:
    db = tmp_path / "w.sqlite"
    db.write_bytes(b"")
    old_mtime = time.time() - 400  # > 5 min stale
    import os

    os.utime(db, (old_mtime, old_mtime))
    cfg = WitchcraftConfig(db_path="w.sqlite")
    with patch(
        "sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value="/usr/bin/witchcraft"
    ):
        assert semantic_mode_allowed(cfg, tmp_path) is False


def test_semantic_mode_allowed_fresh_db_true(tmp_path: Path) -> None:
    db = tmp_path / "w.sqlite"
    db.write_bytes(b"")
    cfg = WitchcraftConfig(db_path="w.sqlite")
    with patch(
        "sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value="/usr/bin/witchcraft"
    ):
        assert semantic_mode_allowed(cfg, tmp_path) is True


# ---------------------------------------------------------------------------
# index_age_seconds
# ---------------------------------------------------------------------------


def test_index_age_seconds_missing_db_none(tmp_path: Path) -> None:
    cfg = WitchcraftConfig(db_path="missing.sqlite")
    assert index_age_seconds(cfg, tmp_path) is None


def test_index_age_seconds_fresh_db_small(tmp_path: Path) -> None:
    db = tmp_path / "w.sqlite"
    db.write_bytes(b"")
    cfg = WitchcraftConfig(db_path="w.sqlite")
    age = index_age_seconds(cfg, tmp_path)
    assert age is not None
    assert age < 5


# ---------------------------------------------------------------------------
# maybe_semantic_scores — graceful failure paths
# ---------------------------------------------------------------------------


def test_maybe_semantic_scores_no_binary_none(tmp_path: Path) -> None:
    with patch("sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value=None):
        result = maybe_semantic_scores(tmp_path, query="q", _shared_wiki=None)
    assert result is None


def test_maybe_semantic_scores_stale_index_none(tmp_path: Path) -> None:
    db = tmp_path / "w.sqlite"
    db.write_bytes(b"")
    import os

    os.utime(db, (time.time() - 400, time.time() - 400))
    cfg = WitchcraftConfig(db_path="w.sqlite")
    with patch(
        "sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value="/usr/bin/witchcraft"
    ):
        result = maybe_semantic_scores(
            tmp_path, query="q", _shared_wiki=None, witchcraft_cfg=cfg, workspace_path=tmp_path
        )
    assert result is None


def test_maybe_semantic_scores_binary_failure_none(tmp_path: Path) -> None:
    db = tmp_path / "w.sqlite"
    db.write_bytes(b"")
    cfg = WitchcraftConfig(db_path="w.sqlite")
    with (
        patch(
            "sevn.second_brain.witchcraft_bridge._witchcraft_binary",
            return_value="/usr/bin/witchcraft",
        ),
        patch(
            "sevn.second_brain.witchcraft_bridge.subprocess.run",
            side_effect=OSError("binary error"),
        ),
    ):
        result = maybe_semantic_scores(
            tmp_path, query="q", _shared_wiki=None, witchcraft_cfg=cfg, workspace_path=tmp_path
        )
    assert result is None


def test_maybe_semantic_scores_parses_json(tmp_path: Path) -> None:
    import json
    import subprocess

    db = tmp_path / "w.sqlite"
    db.write_bytes(b"")
    cfg = WitchcraftConfig(db_path="w.sqlite")
    fake_output = json.dumps([{"origin": "user", "path": "notes/a.md", "score": 0.9}])
    fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=fake_output)
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
        result = maybe_semantic_scores(
            tmp_path, query="notes", _shared_wiki=None, witchcraft_cfg=cfg, workspace_path=tmp_path
        )
    assert result == {("user", "notes/a.md"): 0.9}


# ---------------------------------------------------------------------------
# build_wiki_index
# ---------------------------------------------------------------------------


def test_build_wiki_index_no_binary_false(tmp_path: Path) -> None:
    cfg = WitchcraftConfig(db_path="w.sqlite")
    with patch("sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value=None):
        assert build_wiki_index(tmp_path, witchcraft_cfg=cfg, workspace_path=tmp_path) is False


def test_build_wiki_index_binary_success(tmp_path: Path) -> None:
    import subprocess

    cfg = WitchcraftConfig(db_path=".sevn/w.sqlite")
    fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
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
        result = build_wiki_index(tmp_path, witchcraft_cfg=cfg, workspace_path=tmp_path)
    assert result is True


# ---------------------------------------------------------------------------
# maybe_reindex_on_startup
# ---------------------------------------------------------------------------


def test_maybe_reindex_on_startup_none_cfg_noop(tmp_path: Path) -> None:
    with patch("sevn.second_brain.witchcraft_bridge.build_wiki_index") as mock_build:
        maybe_reindex_on_startup(None, tmp_path)
    mock_build.assert_not_called()


def test_maybe_reindex_on_startup_not_enabled_noop(tmp_path: Path) -> None:
    cfg = WitchcraftConfig(reindex_on_startup=False)
    with patch("sevn.second_brain.witchcraft_bridge.build_wiki_index") as mock_build:
        maybe_reindex_on_startup(cfg, tmp_path)
    mock_build.assert_not_called()


def test_maybe_reindex_on_startup_enabled_no_binary_noop(tmp_path: Path) -> None:
    cfg = WitchcraftConfig(reindex_on_startup=True)
    with (
        patch("sevn.second_brain.witchcraft_bridge._witchcraft_binary", return_value=None),
        patch("sevn.second_brain.witchcraft_bridge.build_wiki_index") as mock_build,
    ):
        maybe_reindex_on_startup(cfg, tmp_path)
    mock_build.assert_not_called()


def test_maybe_reindex_on_startup_enabled_calls_build(tmp_path: Path) -> None:
    cfg = WitchcraftConfig(reindex_on_startup=True)
    with (
        patch(
            "sevn.second_brain.witchcraft_bridge._witchcraft_binary",
            return_value="/usr/bin/witchcraft",
        ),
        patch("sevn.second_brain.witchcraft_bridge.build_wiki_index") as mock_build,
    ):
        maybe_reindex_on_startup(cfg, tmp_path)
    mock_build.assert_called_once()
