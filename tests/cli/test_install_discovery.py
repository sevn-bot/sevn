"""Install discovery for onboarding reuse (`specs/22-onboarding.md` §4.1)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from sevn.cli.install_discovery import (
    InstallCandidate,
    discover_operator_homes,
    resolve_keystore_path,
    workspace_has_artifacts,
)
from sevn.onboarding.install_gate import (
    InstallResolution,
    apply_install_resolution,
    install_gate_state,
    replace_keystore,
    resolve_install_action,
    wipe_operator_home,
)
from sevn.onboarding.web_app import create_onboarding_app


def _install_home(base: Path, *, name: str = ".sevn") -> Path:
    home = base / name
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "agent": {"display_name": "ReuseBot"},
                "onboarding": {"applied_profile": "full_free"},
                "secrets_backend": {
                    "encrypted_file": {"path": ".sevn/secrets/store.enc"},
                    "chain": [{"type": "encrypted_file", "path": ".sevn/secrets/store.enc"}],
                },
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    store = ws / ".sevn" / "secrets"
    store.mkdir(parents=True)
    (store / "store.enc").write_bytes(b"enc")
    return home


def test_discover_operator_homes_finds_multiple(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "userhome"
    fake_home.mkdir()
    _install_home(fake_home, name=".sevn")
    _install_home(fake_home, name=".sevn2")
    monkeypatch.setattr("sevn.cli.install_discovery.Path.home", lambda: fake_home)
    rows = discover_operator_homes()
    assert len(rows) == 2
    assert all(isinstance(row, InstallCandidate) for row in rows)
    assert rows[0].has_keystore is True
    assert rows[0].keystore_path is not None


def test_resolve_keystore_path_missing_file(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
        encoding="utf-8",
    )
    assert resolve_keystore_path(sevn_json=sevn_json) is None


def test_install_gate_state_show_when_candidate_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "userhome"
    fake_home.mkdir()
    op = _install_home(fake_home)
    monkeypatch.setenv("SEVN_HOME", str(op))
    monkeypatch.delenv("SEVN_ONBOARD_GATE_RESOLVED", raising=False)
    monkeypatch.setattr("sevn.onboarding.install_gate.Path.home", lambda: fake_home)
    monkeypatch.setattr("sevn.cli.install_discovery.Path.home", lambda: fake_home)
    state = install_gate_state()
    assert state.show_gate is True
    assert len(state.candidates) == 1


def test_apply_install_resolution_sets_reuse_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".sevn"
    home.mkdir()
    monkeypatch.delenv("SEVN_ONBOARD_REUSE", raising=False)
    monkeypatch.delenv("SEVN_ONBOARD_GATE_RESOLVED", raising=False)
    bound = apply_install_resolution(InstallResolution(home=home, reuse=True))
    assert bound == home.resolve()
    assert os.environ["SEVN_ONBOARD_REUSE"] == "1"
    assert os.environ["SEVN_ONBOARD_GATE_RESOLVED"] == "1"


def test_resolve_install_action_wipe_requires_delete(tmp_path: Path) -> None:
    home = _install_home(tmp_path)
    with pytest.raises(ValueError, match="DELETE"):
        resolve_install_action(action="wipe", home=home, confirm="nope")


def test_wipe_operator_home_removes_tree(tmp_path: Path) -> None:
    home = _install_home(tmp_path)
    with (
        patch("sevn.cli.service_manager.stop_paired_units"),
        patch("sevn.cli.service_manager.remove_paired_unit_files"),
    ):
        wipe_operator_home(home)
    assert not home.exists()


def test_wipe_operator_home_survives_finder_ds_store_race(tmp_path: Path) -> None:
    """macOS Finder re-creates ``.DS_Store`` while ``rmtree`` is walking.

    The retry loop in ``_robust_rmtree`` sweeps the residue and tries again.
    Reference: the user-reported traceback on ``sevn onboard`` (2026-05-27)
    where ``shutil.rmtree`` died with ``ENOTEMPTY`` on
    ``/Users/alex/.sevn/workspace`` because ``.DS_Store`` was recreated
    mid-walk by Finder.
    """
    import errno
    import shutil as _shutil

    home = _install_home(tmp_path)
    inner = home / "workspace"
    inner.mkdir(exist_ok=True)
    (inner / "real-file").write_text("payload")
    real_rmtree = _shutil.rmtree
    calls = {"n": 0}

    def _flaky_rmtree(target: object, *args: object, **kwargs: object) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            # Simulate Finder racing in to recreate .DS_Store after the
            # walk emptied the directory but before rmdir succeeded.
            for sub in (inner, home):
                if sub.exists():
                    (sub / ".DS_Store").write_text("Finder")
            raise OSError(errno.ENOTEMPTY, "Directory not empty", str(target))
        real_rmtree(target, *args, **kwargs)

    with (
        patch("sevn.cli.service_manager.stop_paired_units"),
        patch("sevn.cli.service_manager.remove_paired_unit_files"),
        patch("sevn.onboarding.install_gate.shutil.rmtree", side_effect=_flaky_rmtree),
    ):
        wipe_operator_home(home)
    assert not home.exists()
    assert calls["n"] >= 2  # the retry did fire


def test_replace_keystore_deletes_store(tmp_path: Path) -> None:
    home = _install_home(tmp_path)
    sevn_json = home / "workspace" / "sevn.json"
    removed = replace_keystore(sevn_json=sevn_json)
    assert removed is not None
    assert not removed.is_file()


def test_workspace_has_artifacts_keystore_only(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    store = ws / ".sevn" / "secrets"
    store.mkdir(parents=True)
    (store / "store.enc").write_bytes(b"enc")
    assert workspace_has_artifacts(ws) is True


def test_install_gate_state_show_when_workspace_artifacts_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "userhome"
    fake_home.mkdir()
    op = fake_home / ".sevn"
    ws = op / "workspace"
    store = ws / ".sevn" / "secrets"
    store.mkdir(parents=True)
    (store / "store.enc").write_bytes(b"enc")
    monkeypatch.setattr("sevn.cli.install_discovery.Path.home", lambda: fake_home)
    monkeypatch.setenv("SEVN_HOME", str(op))
    monkeypatch.delenv("SEVN_ONBOARD_GATE_RESOLVED", raising=False)
    state = install_gate_state()
    assert state.show_gate is True
    assert state.active_has_workspace_artifacts is True
    assert state.active_has_config is False
    assert state.active_has_keystore is True
    assert state.candidates == ()


def test_web_existing_config_gate_required_without_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = tmp_path / "workspace"
    store = ws / ".sevn" / "secrets"
    store.mkdir(parents=True)
    (store / "store.enc").write_bytes(b"enc")
    sevn_json = ws / "sevn.json"
    monkeypatch.delenv("SEVN_ONBOARD_GATE_RESOLVED", raising=False)
    client = TestClient(create_onboarding_app("tok", sevn_json_path=sevn_json))
    r = client.get("/api/existing-config", params={"onboard_token": "tok"})
    assert r.status_code == 200
    body = r.json()
    assert body["gate_required"] is True
    assert body["should_prefill_secrets"] is False
    assert body["exists"] is False


def test_web_discover_partial_workspace_and_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    op = tmp_path / ".sevn"
    ws = op / "workspace"
    store = ws / ".sevn" / "secrets"
    store.mkdir(parents=True)
    (store / "store.enc").write_bytes(b"enc")
    sevn_json = ws / "sevn.json"
    monkeypatch.setenv("SEVN_HOME", str(op))
    monkeypatch.delenv("SEVN_ONBOARD_GATE_RESOLVED", raising=False)
    client = TestClient(create_onboarding_app("tok", sevn_json_path=sevn_json))
    discover = client.get("/api/discover-install", params={"onboard_token": "tok"})
    assert discover.status_code == 200
    body = discover.json()
    assert body["show_gate"] is True
    assert body["active_has_workspace_artifacts"] is True
    assert body["active_has_config"] is False
    resolved = client.post(
        "/api/resolve-install",
        params={"onboard_token": "tok"},
        json={"action": "reuse", "home": str(op)},
    )
    assert resolved.status_code == 200
    assert resolved.json()["reuse"] is True
    with patch(
        "sevn.onboarding.web_app.credentials_status",
        new=AsyncMock(return_value={"ready_for_handoff": False}),
    ):
        existing = client.get("/api/existing-config", params={"onboard_token": "tok"})
    assert existing.json()["should_prefill_secrets"] is True
    assert existing.json().get("gate_required") is not True


def test_web_discover_and_resolve_reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    op = _install_home(tmp_path, name=".sevn-test")
    sevn_json = op / "workspace" / "sevn.json"
    monkeypatch.setenv("SEVN_HOME", str(op))
    monkeypatch.delenv("SEVN_ONBOARD_GATE_RESOLVED", raising=False)
    client = TestClient(create_onboarding_app("tok", sevn_json_path=sevn_json))
    discover = client.get("/api/discover-install", params={"onboard_token": "tok"})
    assert discover.status_code == 200
    assert discover.json()["show_gate"] is True
    resolved = client.post(
        "/api/resolve-install",
        params={"onboard_token": "tok"},
        json={"action": "reuse", "home": str(op)},
    )
    assert resolved.status_code == 200
    assert resolved.json()["reuse"] is True
    with patch(
        "sevn.onboarding.web_app.credentials_status",
        new=AsyncMock(return_value={"ready_for_handoff": False}),
    ):
        existing = client.get("/api/existing-config", params={"onboard_token": "tok"})
    body = existing.json()
    assert body["reuse"] is True
    assert body["config"]["agent"]["display_name"] == "ReuseBot"
    assert body["has_keystore"] is True


def test_web_existing_config_includes_credentials_status(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    sevn_json = ws / "sevn.json"
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
    client = TestClient(create_onboarding_app("tok", sevn_json_path=sevn_json))
    with patch(
        "sevn.onboarding.web_app.credentials_status",
        new=AsyncMock(return_value={"ready_for_handoff": False}),
    ):
        r = client.get("/api/existing-config", params={"onboard_token": "tok"})
    assert r.status_code == 200
    assert "credentials_status" in r.json()
