"""Export/import ``.env`` bundle tests (``sevn export-secrets`` / ``onboard fast``)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from sevn.onboarding.export_bundle import (
    EXPORT_FORMAT_VERSION,
    ExportBundleError,
    _git_ignored,
    build_export_text,
    parse_export_text,
    resolve_export_workspace,
    run_export_secrets,
)
from sevn.security.secrets.backends.encrypted_file import (
    EncryptedFileBackend,
    default_encrypted_store_path,
)


def _write_sevn_json(
    workspace: Path, *, display_name: str = "Luluu", workspace_root: str = "."
) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / "sevn.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": workspace_root,
                "agent": {"display_name": display_name},
                "gateway": {
                    "host": "127.0.0.1",
                    "port": 3001,
                    "queue_mode": "cancel",
                    "token": "${SECRET:keychain:sevn.gateway.token}",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_build_parse_roundtrip() -> None:
    """A built bundle parses back to the same bot name, secrets, and config."""
    config = {
        "schema_version": 1,
        "agent": {"display_name": "Nova"},
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
        "channels": {"telegram": {"enabled": True, "allowed_users": [8484033337]}},
        "tracing": {"sinks": [{"type": "sqlite"}, {"path": ".sevn/traces/", "type": "jsonl_file"}]},
    }
    text = build_export_text(
        bot_name="Nova",
        config_doc=config,
        secrets={"SEVN_SECRET_MINIMAX": "sk-abc", "SEVN_TELEGRAM_BOT_TOKEN": "1:2"},
        generated_at="2026-06-07T00:00:00Z",
    )
    # Config is flattened plaintext, not a JSON blob.
    assert "config.gateway.port=3001" in text
    assert "SEVN_CONFIG_JSON" not in text
    bundle = parse_export_text(text)
    assert bundle.version == EXPORT_FORMAT_VERSION
    assert bundle.bot_name == "Nova"
    assert bundle.secrets["SEVN_SECRET_MINIMAX"] == "sk-abc"
    assert bundle.secrets["SEVN_TELEGRAM_BOT_TOKEN"] == "1:2"
    # Nested objects, typed scalars, and arrays of scalars/objects round-trip exactly.
    assert bundle.config_doc == config


def test_config_flatten_preserves_types_and_shape() -> None:
    """Booleans, ints, nested objects, and arrays survive flatten/unflatten."""
    config = {
        "schema_version": 1,
        "providers": {"use_main_model_for_all": True, "minimax": {"base_url": "https://x/y"}},
        "gateway": {
            "port": 3001,
            "queue_mode": "cancel",
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
        "secrets_backend": {"chain": [{"type": "encrypted_file", "key_source": "passphrase"}]},
        "my_sevn": {"sync": {"cron": "0 4 * * *", "enabled": True}},
    }
    bundle = parse_export_text(build_export_text(bot_name="X", config_doc=config, secrets={}))
    assert bundle.config_doc == config
    assert bundle.config_doc["gateway"]["port"] == 3001  # int, not "3001"
    assert bundle.config_doc["providers"]["use_main_model_for_all"] is True
    assert bundle.config_doc["secrets_backend"]["chain"][0]["type"] == "encrypted_file"


def test_roundtrip_preserves_special_values() -> None:
    """Values with newlines, spaces, and ``#`` survive encode/decode."""
    secrets = {
        "SEVN_MULTILINE": "line1\nline2",
        "SEVN_SPACED": "  padded  ",
        "SEVN_HASH": "#starts-with-hash",
        "SEVN_EQUALS": "a=b=c",
    }
    text = build_export_text(
        bot_name="X",
        config_doc={
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
        secrets=secrets,
    )
    parsed = parse_export_text(text).secrets
    assert parsed == secrets


def test_parse_missing_config_errors() -> None:
    """A bundle without any ``config.*`` line is a usage error (exit 2)."""
    with pytest.raises(ExportBundleError) as exc:
        parse_export_text("SEVN_BOT_NAME=Nova\nSEVN_SECRET_MINIMAX=k\n")
    assert exc.value.exit_code == 2


def test_parse_unsupported_version_errors() -> None:
    """A future format version is rejected with exit 2."""
    with pytest.raises(ExportBundleError) as exc:
        parse_export_text("SEVN_EXPORT_VERSION=999\nconfig.schema_version=1\n")
    assert exc.value.exit_code == 2


def test_parse_bot_name_falls_back_to_config() -> None:
    """When ``SEVN_BOT_NAME`` is absent, the config's display name is used."""
    bundle = parse_export_text("config.schema_version=1\nconfig.agent.display_name=FromCfg\n")
    assert bundle.bot_name == "FromCfg"


def test_resolve_export_workspace_variants(tmp_path: Path) -> None:
    """A workspace dir, its sevn.json, and an operator home all resolve."""
    workspace = tmp_path / "home" / "workspace"
    sevn_json = _write_sevn_json(workspace)
    for target in (workspace, sevn_json, tmp_path / "home"):
        resolved, _cfg, content_root, raw = resolve_export_workspace(target)
        assert resolved == sevn_json
        assert content_root == workspace.resolve()
        assert raw["agent"]["display_name"] == "Luluu"


def test_resolve_export_workspace_missing_errors(tmp_path: Path) -> None:
    """A path without a sevn.json raises a precondition error (exit 4)."""
    with pytest.raises(ExportBundleError) as exc:
        resolve_export_workspace(tmp_path / "nope")
    assert exc.value.exit_code == 4


@pytest.mark.asyncio
async def test_run_export_secrets_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exporting a passphrase store writes secrets + config + bot name (0600)."""
    workspace = tmp_path / "ws"
    _write_sevn_json(workspace)
    store = default_encrypted_store_path(workspace)
    backend = EncryptedFileBackend(store, passphrase="hunter2")
    await backend.set("SEVN_SECRET_MINIMAX", "sk-abc")
    await backend.set("SEVN_SECRETS_PASSPHRASE", "hunter2")
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "hunter2")

    out = tmp_path / "export.env"
    result = await run_export_secrets(workspace_root=workspace, to_file=out)
    assert result.secret_count == 2
    assert result.bot_name == "Luluu"
    assert (out.stat().st_mode & 0o777) == 0o600

    bundle = parse_export_text(out.read_text(encoding="utf-8"))
    assert bundle.secrets["SEVN_SECRET_MINIMAX"] == "sk-abc"
    assert bundle.config_doc["gateway"]["port"] == 3001


@pytest.mark.asyncio
async def test_run_export_secrets_empty_store(tmp_path: Path) -> None:
    """A workspace with no store exports zero secrets without needing a passphrase."""
    workspace = tmp_path / "ws"
    _write_sevn_json(workspace)
    out = tmp_path / "export.env"
    result = await run_export_secrets(workspace_root=workspace, to_file=out)
    assert result.secret_count == 0
    assert "config.schema_version=1" in out.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_run_export_secrets_overwrite_guard(tmp_path: Path) -> None:
    """An existing destination is preserved unless ``force`` is set."""
    workspace = tmp_path / "ws"
    _write_sevn_json(workspace)
    out = tmp_path / "export.env"
    out.write_text("keep me", encoding="utf-8")
    with pytest.raises(ExportBundleError) as exc:
        await run_export_secrets(workspace_root=workspace, to_file=out)
    assert exc.value.exit_code == 4
    assert out.read_text(encoding="utf-8") == "keep me"
    result = await run_export_secrets(workspace_root=workspace, to_file=out, force=True)
    assert result.secret_count == 0


@pytest.mark.asyncio
async def test_run_export_secrets_locked_store_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-empty store with no unlock credential errors as auth (exit 3)."""
    workspace = tmp_path / "ws"
    _write_sevn_json(workspace)
    store = default_encrypted_store_path(workspace)
    await EncryptedFileBackend(store, passphrase="hunter2").set("SEVN_SECRET_MINIMAX", "k")
    monkeypatch.delenv("SEVN_SECRETS_PASSPHRASE", raising=False)
    monkeypatch.setattr(
        "sevn.onboarding.export_bundle.fetch_unlock_secret_from_keychain",
        _async_none,
    )
    with pytest.raises(ExportBundleError) as exc:
        await run_export_secrets(workspace_root=workspace, to_file=tmp_path / "e.env")
    assert exc.value.exit_code == 3


@pytest.mark.asyncio
async def test_run_export_secrets_normalizes_absolute_workspace_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absolute ``workspace_root`` is rewritten to ``.`` for portability."""
    workspace = tmp_path / "ws"
    _write_sevn_json(workspace, workspace_root=str(workspace))
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "p")
    out = tmp_path / "export.env"
    await run_export_secrets(workspace_root=workspace, to_file=out)
    bundle = parse_export_text(out.read_text(encoding="utf-8"))
    assert bundle.config_doc["workspace_root"] == "."


async def _async_none(*_args: object, **_kwargs: object) -> None:
    """Async stub returning ``None`` (keychain miss).

    Examples:
        >>> import asyncio
        >>> asyncio.run(_async_none()) is None
        True
    """
    return


def _init_git_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)  # nosec B603


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_git_ignored_outside_repo(tmp_path: Path) -> None:
    """``_git_ignored`` returns ``None`` when the parent is not a git work tree."""
    assert _git_ignored(tmp_path / "export.env") is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_git_ignored_true_for_ignored_name(tmp_path: Path) -> None:
    """``_git_ignored`` returns ``True`` for a name matched by ``.gitignore``."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".gitignore").write_text("ignored.env\n", encoding="utf-8")
    assert _git_ignored(repo / "ignored.env") is True


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_git_ignored_false_for_unignored_name(tmp_path: Path) -> None:
    """``_git_ignored`` returns ``False`` for a tracked/unignored name in a repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    assert _git_ignored(repo / "export.env") is False


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
async def test_run_export_secrets_warns_on_unignored_git_path(tmp_path: Path) -> None:
    """Exporting into an unignored path inside a git repo sets the warning flag."""
    repo = tmp_path / "repo"
    workspace = repo / "ws"
    _write_sevn_json(workspace)
    _init_git_repo(repo)
    out = repo / "export.env"
    result = await run_export_secrets(workspace_root=workspace, to_file=out)
    assert result.git_unignored_warning is True
    assert result.secret_count == 0
