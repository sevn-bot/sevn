"""D15 path defaults."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _patch_platform(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    system = {"darwin": "Darwin", "linux": "Linux"}[name]
    monkeypatch.setattr(sys, "platform", name)
    monkeypatch.setattr("platform.system", lambda: system)


def _isolate_env(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("SEVN_HOME", raising=False)
    monkeypatch.delenv("SEVN_WORKSPACES", raising=False)


def test_home_default_macos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_platform(monkeypatch, "darwin")
    _isolate_env(monkeypatch, tmp_path)
    from sevn.paths import Paths

    paths = Paths.default()
    assert isinstance(paths.home, Path)
    assert paths.home == tmp_path / "Library" / "Application Support" / "sevn"
    assert paths.logs == tmp_path / "Library" / "Logs" / "sevn"
    assert paths.workspaces == tmp_path / "Sevn"


def test_home_default_linux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_platform(monkeypatch, "linux")
    _isolate_env(monkeypatch, tmp_path)
    from sevn.paths import Paths

    paths = Paths.default()
    assert paths.home == tmp_path / ".local" / "share" / "sevn"
    assert paths.logs == paths.home / "logs"
    assert paths.workspaces == paths.home / "workspaces"


def test_sevn_home_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.delenv("SEVN_WORKSPACES", raising=False)
    from sevn.paths import Paths

    paths = Paths.from_env()
    assert paths.home == tmp_path
    assert paths.db == tmp_path / "sevn.db"
    assert paths.run == tmp_path / "run"
    assert paths.secrets_file == tmp_path / "secrets.age"
    assert paths.keys == tmp_path / "keys"
    assert paths.logs == tmp_path / "logs"


def test_workspaces_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspaces = tmp_path / "ws"
    monkeypatch.setenv("SEVN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SEVN_WORKSPACES", str(workspaces))
    from sevn.paths import Paths

    assert Paths.from_env().workspaces == workspaces
