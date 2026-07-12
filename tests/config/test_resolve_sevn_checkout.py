"""Tests for :func:`sevn.config.sevn_repo.resolve_sevn_checkout_for_workspace`."""

from __future__ import annotations

from pathlib import Path

from sevn.config.my_sevn import persist_my_sevn_repo_path
from sevn.config.sevn_repo import (
    resolve_sevn_checkout_for_workspace,
    resolve_sevn_checkout_with_origin,
)
from sevn.config.workspace_config import MySevnWorkspaceConfig, WorkspaceConfig


def _write_sevn_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    (path / "pyproject.toml").write_text('[project]\nname = "sevn"\n', encoding="utf-8")


def test_resolve_prefers_my_sevn_repo_path_in_sevn_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_repo = tmp_path / "configured-checkout"
    env_repo = tmp_path / "env-checkout"
    _write_sevn_repo(config_repo)
    _write_sevn_repo(env_repo)
    ws = WorkspaceConfig(
        schema_version=1,
        my_sevn=MySevnWorkspaceConfig(repo_path=str(config_repo)),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    monkeypatch.setenv("SEVN_REPO_ROOT", str(env_repo))
    assert (
        resolve_sevn_checkout_for_workspace(
            ws,
            content_root=tmp_path / "operator-ws",
        )
        == config_repo.resolve()
    )


def test_resolve_sevn_source_root_when_no_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "source"
    _write_sevn_repo(repo)
    monkeypatch.delenv("SEVN_REPO_ROOT", raising=False)
    monkeypatch.setenv("SEVN_SOURCE_ROOT", str(repo))
    assert (
        resolve_sevn_checkout_for_workspace(
            WorkspaceConfig(
                schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
            ),
            content_root=tmp_path / "ws",
        )
        == repo.resolve()
    )


def test_resolve_none_from_bare_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from sevn.config import sevn_repo as mod

    monkeypatch.delenv("SEVN_REPO_ROOT", raising=False)
    monkeypatch.delenv("SEVN_SOURCE_ROOT", raising=False)
    monkeypatch.setattr(mod, "_installed_sevn_package_root", lambda: None)
    fake_home = tmp_path / "empty-home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    assert (
        resolve_sevn_checkout_for_workspace(
            WorkspaceConfig(
                schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
            ),
            content_root=tmp_path / "fake-ws",
        )
        is None
    )


def test_installed_package_root_when_sevn_importable() -> None:
    from sevn.config.sevn_repo import _installed_sevn_package_root

    root = _installed_sevn_package_root()
    assert root is not None
    assert (root / "gateway").is_dir()


def test_search_common_dev_locations_finds_nested_checkout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from sevn.config import sevn_repo as mod

    fake_home = tmp_path / "home"
    nested = fake_home / "Documents" / "code" / "sevn"
    _write_sevn_repo(nested)

    monkeypatch.delenv("SEVN_REPO_ROOT", raising=False)
    monkeypatch.delenv("SEVN_SOURCE_ROOT", raising=False)
    monkeypatch.setattr(mod, "_installed_sevn_package_root", lambda: None)
    monkeypatch.setenv("HOME", str(fake_home))

    ws = WorkspaceConfig(
        schema_version=1,
        my_sevn=MySevnWorkspaceConfig(repo_url="https://github.com/sevn-bot/sevn"),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    found = resolve_sevn_checkout_for_workspace(
        ws,
        content_root=tmp_path / "bare-ws",
    )
    assert found == nested.resolve()


def test_search_common_dev_locations_returns_none_without_home(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from sevn.config import sevn_repo as mod

    monkeypatch.delenv("SEVN_REPO_ROOT", raising=False)
    monkeypatch.delenv("SEVN_SOURCE_ROOT", raising=False)
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setattr(mod, "_installed_sevn_package_root", lambda: None)

    found = resolve_sevn_checkout_for_workspace(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        content_root=tmp_path / "bare-ws",
    )
    assert found is None


def test_origin_pinned_for_configured_repo_path(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "configured"
    _write_sevn_repo(repo)
    ws = WorkspaceConfig(
        schema_version=1,
        my_sevn=MySevnWorkspaceConfig(repo_path=str(repo)),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    path, origin = resolve_sevn_checkout_with_origin(ws, content_root=tmp_path / "ws")
    assert path == repo.resolve()
    assert origin == "pinned"


def test_origin_env_for_env_var(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "env"
    _write_sevn_repo(repo)
    monkeypatch.setenv("SEVN_REPO_ROOT", str(repo))
    path, origin = resolve_sevn_checkout_with_origin(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        content_root=tmp_path / "ws",
    )
    assert path == repo.resolve()
    assert origin == "env"


def test_origin_scan_for_home_discovered_checkout(tmp_path: Path, monkeypatch) -> None:
    from sevn.config import sevn_repo as mod

    monkeypatch.delenv("SEVN_REPO_ROOT", raising=False)
    monkeypatch.delenv("SEVN_SOURCE_ROOT", raising=False)
    monkeypatch.setattr(mod, "_installed_sevn_package_root", lambda: None)
    home = tmp_path / "home"
    repo = home / "code" / "sevn.bot"
    _write_sevn_repo(repo)
    monkeypatch.setenv("HOME", str(home))
    path, origin = resolve_sevn_checkout_with_origin(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        content_root=tmp_path / "ws",
    )
    assert path == repo.resolve()
    assert origin == "scan"


def test_persist_repo_path_writes_and_is_idempotent(tmp_path: Path) -> None:
    import json

    sj = tmp_path / "sevn.json"
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
    repo = tmp_path / "checkout"

    assert persist_my_sevn_repo_path(sj, repo) is True
    data = json.loads(sj.read_text(encoding="utf-8"))
    assert data["my_sevn"]["repo_path"] == str(repo)
    # Other keys preserved:
    assert data["schema_version"] == 1
    assert data["workspace_root"] == "."
    # Second call with the same value rewrites nothing:
    assert persist_my_sevn_repo_path(sj, repo) is False


def test_persist_repo_path_missing_file_is_noop(tmp_path: Path) -> None:
    assert persist_my_sevn_repo_path(tmp_path / "nope.json", tmp_path / "repo") is False
