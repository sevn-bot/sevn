"""Wave B regression tests for ``sevn secrets`` + migrate helpers (`specs/06-secrets.md`)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner as ClickCliRunner
from starlette.testclient import TestClient
from typer.main import get_command

import sevn.cli.secrets_gateway_client as secrets_gateway_client_mod
from sevn.cli.app import app
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.http_server import create_app
from sevn.secrets.fingerprint import fingerprint_sha256_hex
from sevn.secrets.migrate import LEGACY_PLAINTEXT_JSON, promote_legacy_plaintext_to_encrypted_store
from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend
from sevn.security.secrets.factory import resolve_primary_encrypted_store_path
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


_GW_TOKEN = "test-gw-token"


def _install_workspace(tmp_home: Path) -> Path:
    ws = tmp_home / "workspace"
    ws.mkdir(parents=True)
    # These tests seal/open the encrypted store with SEVN_SECRETS_MASTER_KEY, so the workspace
    # must declare key_source=master_key (default is passphrase; ``specs/06-secrets.md`` §5).
    (ws / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "secrets_backend": {
                    "chain": [
                        {
                            "type": "encrypted_file",
                            "path": ".sevn/secrets/store.enc",
                            "key_source": "master_key",
                        }
                    ],
                },
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    return tmp_home


def _patch_secrets_gateway(
    monkeypatch: pytest.MonkeyPatch,
    home: Path,
    request: pytest.FixtureRequest,
) -> None:
    """Route CLI secrets HTTP through an in-process ASGI gateway (delegation path)."""
    sevn_json = home / "workspace" / "sevn.json"
    cfg = parse_workspace_config(json.loads(sevn_json.read_text(encoding="utf-8")))
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    # The autouse conftest fixture exports SEVN_GATEWAY_TOKEN="a"*64; env wins at boot, so
    # pin it to _GW_TOKEN BEFORE the gateway boots or the in-process app would resolve a
    # different bearer than the CLI sends (→ 403 → exit 4).
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", _GW_TOKEN)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_migrations(conn)
        return conn

    gw_app = create_app(
        workspace=cfg,
        layout=layout,
        sqlite_connection_factory=factory,
        process_settings=ProcessSettings(gateway_token=_GW_TOKEN),
    )
    client_cm = TestClient(gw_app, raise_server_exceptions=True)
    tc = client_cm.__enter__()
    tc.get("/health")
    request.addfinalizer(lambda: client_cm.__exit__(None, None, None))
    headers = {"Authorization": f"Bearer {_GW_TOKEN}"}

    def _via_test_client(
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        **kwargs: object,
    ) -> object:
        _ = kwargs
        verb = method.upper()
        if verb == "GET":
            return tc.get(path, headers=headers)
        if verb == "PUT":
            return tc.put(path, headers=headers, json=json_body)
        if verb == "DELETE":
            return tc.request("DELETE", path, headers=headers, json=json_body)
        msg = f"unsupported method {method}"
        raise ValueError(msg)

    monkeypatch.setattr(secrets_gateway_client_mod, "gateway_json_request", _via_test_client)
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", _GW_TOKEN)


def test_promote_legacy_plaintext_writes_store_enc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy plaintext.json promotes into encrypted ``store.enc``."""
    home = _install_workspace(tmp_path / "h")
    ws = home / "workspace"
    sec = ws / ".sevn" / "secrets"
    sec.mkdir(parents=True)
    (sec / LEGACY_PLAINTEXT_JSON).write_text(
        json.dumps({"providers.demo.token": "abc"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)

    from sevn.cli.workspace import load_bound_workspace

    bw = load_bound_workspace()

    result = asyncio.run(
        promote_legacy_plaintext_to_encrypted_store(
            content_root=bw.layout.content_root,
            workspace_config=bw.config,
        ),
    )
    assert result.keys_written == 1
    store = sec / "store.enc"
    assert store.is_file()
    assert not (sec / LEGACY_PLAINTEXT_JSON).exists()


def test_doctor_migrate_secrets_cli_removes_legacy(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``doctor --migrate-secrets --yes`` completes migrate path."""
    home = _install_workspace(tmp_path / "h2")
    ws = home / "workspace"
    sec = ws / ".sevn" / "secrets"
    sec.mkdir(parents=True)
    (sec / LEGACY_PLAINTEXT_JSON).write_text(
        json.dumps({"k.cli": "v"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "01" * 32)

    r = runner.invoke(
        get_command(app),
        ["doctor", "--migrate-secrets", "--yes"],
        env={
            "SEVN_HOME": str(home),
            "SEVN_SECRETS_MASTER_KEY": "01" * 32,
        },
    )
    assert r.exit_code == 0
    assert not (sec / LEGACY_PLAINTEXT_JSON).exists()


def test_secrets_put_rm_confirm_roundtrip(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """``put`` overwrite requires fingerprint match; ``rm`` matches alias + fingerprint."""
    home = _install_workspace(tmp_path / "h3")
    monkeypatch.setenv("SEVN_HOME", str(home))
    mk_hex = "ff" * 32
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", mk_hex)
    _patch_secrets_gateway(monkeypatch, home, request)

    base_env = {
        "SEVN_HOME": str(home),
        "SEVN_SECRETS_MASTER_KEY": mk_hex,
        "SEVN_GATEWAY_TOKEN": _GW_TOKEN,
    }

    r1 = runner.invoke(
        get_command(app),
        ["secrets", "put", "slot.one", "--value", "first"],
        env=base_env,
    )
    assert r1.exit_code == 0

    r_bad = runner.invoke(
        get_command(app),
        ["secrets", "put", "slot.one", "--value", "second"],
        env=base_env,
    )
    assert r_bad.exit_code == 4

    fp1 = fingerprint_sha256_hex("first")
    r2 = runner.invoke(
        get_command(app),
        ["secrets", "put", "slot.one", "--value", "second", "--confirm-fingerprint", fp1],
        env=base_env,
    )
    assert r2.exit_code == 0

    fp2 = fingerprint_sha256_hex("second")
    r_rm_bad = runner.invoke(
        get_command(app),
        [
            "secrets",
            "rm",
            "slot.one",
            "--confirm-alias",
            "other",
            "--confirm-fingerprint",
            fp2,
        ],
        env=base_env,
    )
    assert r_rm_bad.exit_code == 4

    r_rm = runner.invoke(
        get_command(app),
        [
            "secrets",
            "rm",
            "slot.one",
            "--confirm-alias",
            "slot.one",
            "--confirm-fingerprint",
            fp2,
        ],
        env=base_env,
    )
    assert r_rm.exit_code == 0


def test_onboard_config_normalizes_encrypted_file_paths(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sevn onboard --config`` persists paired ``encrypted_file`` paths."""
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {
                    "host": "127.0.0.1",
                    "port": 3001,
                    "queue_mode": "cancel",
                    "token": "${SECRET:keychain:sevn.gateway.token}",
                },
                "secrets_backend": {"chain": [{"type": "encrypted_file"}]},
            }
        ),
        encoding="utf-8",
    )
    with patch(
        "sevn.onboarding.service_restart.restart_services_after_promote",
        return_value={"ok": True, "message": "started"},
    ):
        result = runner.invoke(
            get_command(app),
            [
                "onboard",
                "--config",
                str(cfg_path),
                "--no-prompt-bot-name",
                "--bot-name",
                "SecretsBot",
            ],
            env={"SEVN_HOME": str(home)},
        )
    assert result.exit_code == 0, result.stdout + result.stderr
    sevn_json = home / "workspace" / "sevn.json"
    doc = json.loads(sevn_json.read_text(encoding="utf-8"))
    assert doc["secrets_backend"]["encrypted_file"]["path"] == ".sevn/secrets/store.enc"
    assert doc["secrets_backend"]["chain"][0]["path"] == ".sevn/secrets/store.enc"


def test_doctor_migrate_rejects_unexpected_files_without_yes(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected sibling files require explicit ``--yes`` review bypass."""
    home = _install_workspace(tmp_path / "h4")
    ws = home / "workspace"
    sec = ws / ".sevn" / "secrets"
    sec.mkdir(parents=True)
    (sec / LEGACY_PLAINTEXT_JSON).write_text(json.dumps({"a": "b"}), encoding="utf-8")
    (sec / "notes.txt").write_text("not a secret file", encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "aa" * 32)

    r = runner.invoke(
        get_command(app),
        ["doctor", "--migrate-secrets"],
        env={
            "SEVN_HOME": str(home),
            "SEVN_SECRETS_MASTER_KEY": "aa" * 32,
        },
    )
    assert r.exit_code == 4
    out = (r.stderr + r.stdout).lower()
    assert "unexpected files" in out


def test_legacy_dot_secret_files_merge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``*.secret`` stems promote without ``plaintext.json``."""
    home = _install_workspace(tmp_path / "h5")
    ws = home / "workspace"
    sec = ws / ".sevn" / "secrets"
    sec.mkdir(parents=True)
    (sec / "from.file.secret").write_text(" value-with-space \n", encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "bb" * 32)

    from sevn.cli.workspace import load_bound_workspace

    bw = load_bound_workspace()
    asyncio.run(
        promote_legacy_plaintext_to_encrypted_store(
            content_root=bw.layout.content_root,
            workspace_config=bw.config,
        ),
    )

    path = resolve_primary_encrypted_store_path(bw.layout.content_root, bw.config.secrets_backend)
    backend = EncryptedFileBackend(path, master_key=bytes.fromhex("bb" * 32))

    async def _read() -> str | None:
        return await backend.get("from.file")

    raw = asyncio.run(_read())
    assert raw == "value-with-space"
