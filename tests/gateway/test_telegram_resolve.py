"""Telegram bot token resolution (`specs/06-secrets.md` §2.5)."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.telegram.telegram_resolve import resolve_telegram_bot_token
from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend
from sevn.security.secrets.chain import SecretsChain


@pytest.mark.anyio
async def test_env_ref_resolves_from_secrets_chain(tmp_path: Path) -> None:
    """``${ENV:SEVN_TELEGRAM_BOT_TOKEN}`` loads from chain when process env is unset."""
    store = tmp_path / "store.enc"
    mk = secrets.token_bytes(32)
    backend = EncryptedFileBackend(store, master_key=mk)
    chain = SecretsChain([backend], backend_labels=["encrypted_file"])
    await chain.set("SEVN_TELEGRAM_BOT_TOKEN", "123456789:ABCdefGHIjklMNOpqrsTUVwxyz")

    cfg = WorkspaceConfig(
        schema_version=1,
        channels={"telegram": {"bot_token_ref": "${ENV:SEVN_TELEGRAM_BOT_TOKEN}"}},
        secrets_backend={
            "chain": [
                {"type": "encrypted_file", "path": "store.enc", "key_source": "master_key"},
            ],
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    import os

    os.environ["SEVN_SECRETS_MASTER_KEY"] = mk.hex()
    os.environ.pop("SEVN_TELEGRAM_BOT_TOKEN", None)
    try:
        token = await resolve_telegram_bot_token(cfg, content_root=tmp_path)
    finally:
        os.environ.pop("SEVN_SECRETS_MASTER_KEY", None)
    assert token == "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
