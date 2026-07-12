"""``probe_secrets_backend`` surfaces wrong-key stores as hard errors (`specs/06-secrets.md` §6).

Regression: a stale ``SEVN_SECRETS_MASTER_KEY`` shadowing the passphrase silently broke
decryption of a passphrase-sealed store, leaving the gateway booting without a bot token. The
probe must report this loudly (severity ``error``), distinct from a merely *locked* backend.
"""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest

from sevn.config.workspace_config import SecretsBackendSectionConfig
from sevn.onboarding.live_validate import probe_secrets_backend
from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend

_STORE_REL = ".sevn/secrets/store.enc"


def _section(key_source: str = "passphrase") -> SecretsBackendSectionConfig:
    return SecretsBackendSectionConfig.model_validate(
        {
            "encrypted_file": {"path": _STORE_REL, "key_source": key_source},
            "chain": [{"type": "encrypted_file", "path": _STORE_REL, "key_source": key_source}],
        }
    )


@pytest.mark.anyio
async def test_probe_reports_wrong_key_store_as_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A store sealed with one master_key but read with another is a hard ``error``."""
    store = tmp_path / _STORE_REL
    store.parent.mkdir(parents=True)
    # Seal under KDF_RAW_KEY with master_key A, then read with an unrelated master_key B.
    writer = EncryptedFileBackend(store, master_key=secrets.token_bytes(32))
    await writer.set("_sevn_probe", "ok")

    monkeypatch.delenv("SEVN_SECRETS_PASSPHRASE", raising=False)
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", secrets.token_bytes(32).hex())

    check = await probe_secrets_backend(content_root=tmp_path, section=_section("master_key"))

    assert check.ok is False
    assert check.severity == "error"
    assert "fails to decrypt" in check.detail
    assert check.hint is not None
    assert "SEVN_SECRETS_MASTER_KEY" in check.hint


@pytest.mark.anyio
async def test_probe_warns_on_stray_master_key_under_passphrase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PBKDF2 store reads OK with a stray master_key, but the probe warns it is ignored.

    The ``_material_key`` fix means the store still opens (no breakage); the proactive warning
    surfaces the stray credential — the exact stale-env condition that used to break resolution.
    """
    store = tmp_path / _STORE_REL
    store.parent.mkdir(parents=True)
    writer = EncryptedFileBackend(store, passphrase="correct horse battery staple")
    await writer.set("_sevn_probe", "ok")

    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "correct horse battery staple")
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", secrets.token_bytes(32).hex())

    check = await probe_secrets_backend(content_root=tmp_path, section=_section())

    assert check.ok is True
    assert check.severity == "warn"
    assert "SEVN_SECRETS_MASTER_KEY" in check.detail
    assert "ignored" in check.detail


@pytest.mark.anyio
async def test_probe_clean_passphrase_store_is_info(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No stray credential → clean ``info`` read."""
    store = tmp_path / _STORE_REL
    store.parent.mkdir(parents=True)
    writer = EncryptedFileBackend(store, passphrase="correct horse battery staple")
    await writer.set("_sevn_probe", "ok")

    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "correct horse battery staple")
    monkeypatch.delenv("SEVN_SECRETS_MASTER_KEY", raising=False)

    check = await probe_secrets_backend(content_root=tmp_path, section=_section())

    assert check.ok is True
    assert check.severity == "info"
