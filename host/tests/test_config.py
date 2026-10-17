"""Settings toml source and the session queue default."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_config_toml_overrides_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        "[protocol]\nsession_queue_limit = 5\n",
        encoding="utf-8",
    )
    from sevn.config import Settings

    assert Settings.load().protocol.session_queue_limit == 5


def test_session_queue_limit_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.delenv("SEVN_PROTOCOL__SESSION_QUEUE_LIMIT", raising=False)
    from sevn.config import Settings

    assert Settings.load().protocol.session_queue_limit == 1000


def test_invalid_config_names_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        '[protocol]\nsession_queue_limit = "x"\n',
        encoding="utf-8",
    )
    from sevn.config import Settings
    from sevn.errors import ConfigError

    with pytest.raises(ConfigError) as exc:
        Settings.load()
    assert "protocol.session_queue_limit" in str(exc.value)
