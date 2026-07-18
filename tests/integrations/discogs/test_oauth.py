"""Discogs OAuth integration + Telegram step machine (W1.11 / D20)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_router import IncomingMessage
from sevn.security.secrets.chain import SecretsChain
from sevn.storage.migrate import apply_migrations


class _MemBackend:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


def _oauth_mod() -> Any:
    from sevn.integrations.discogs import oauth as mod

    return mod


def test_begin_oauth_returns_authorize_tuple() -> None:
    mod = _oauth_mod()
    client = MagicMock()
    client.get_authorize_url.return_value = (
        "req-token",
        "req-secret",
        "https://discogs.com/oauth/authorize?oauth_token=req",
    )
    with patch("sevn.integrations.discogs.oauth.discogs_client") as pkg:
        pkg.Client.return_value = client
        request_token, request_secret, authorize_url = mod.begin_oauth(
            "consumer-key",
            "consumer-secret",
            "sevn-discogs/1.0",
        )
    assert request_token == "req-token"
    assert request_secret == "req-secret"
    assert authorize_url.startswith("https://")
    client.get_authorize_url.assert_called_once()


def test_begin_oauth_rejects_non_tuple_response() -> None:
    mod = _oauth_mod()
    client = MagicMock()
    client.get_authorize_url.return_value = "https://discogs.com/oauth/authorize?oauth_token=req"
    with patch("sevn.integrations.discogs.oauth.discogs_client") as pkg:
        pkg.Client.return_value = client
        with pytest.raises(mod.DiscogsOAuthError, match="Unexpected authorize URL"):
            mod.begin_oauth("consumer-key", "consumer-secret", "sevn-discogs/1.0")


def test_complete_oauth_returns_access_tuple() -> None:
    mod = _oauth_mod()
    client = MagicMock()
    client.get_access_token.return_value = ("access-token", "access-secret")
    with patch("sevn.integrations.discogs.oauth.discogs_client") as pkg:
        pkg.Client.return_value = client
        access_token, access_secret = mod.complete_oauth(
            "consumer-key",
            "consumer-secret",
            "request-token",
            "request-secret",
            "verifier-code",
            "sevn-discogs/1.0",
        )
    assert access_token == "access-token"
    assert access_secret == "access-secret"
    client.get_access_token.assert_called_once_with("verifier-code")


def test_complete_oauth_uses_configured_user_agent() -> None:
    mod = _oauth_mod()
    client = MagicMock()
    client.get_access_token.return_value = ("access-token", "access-secret")
    with patch("sevn.integrations.discogs.oauth.discogs_client") as pkg:
        pkg.Client.return_value = client
        mod.complete_oauth(
            "consumer-key",
            "consumer-secret",
            "request-token",
            "request-secret",
            "verifier-code",
            "custom-agent/2.0",
        )
    pkg.Client.assert_called_once()
    assert pkg.Client.call_args.args[0] == "custom-agent/2.0"


@pytest.mark.asyncio
async def test_advance_discogs_oauth_step_machine(tmp_path: Path) -> None:
    from sevn.gateway.commands.menu_form_handler import MenuFormHandler
    from sevn.gateway.dispatcher.dispatcher_state import insert_dispatcher_state

    store: dict[str, str] = {}
    chain = SecretsChain([_MemBackend(store)])
    cfg = WorkspaceConfig.minimal(
        skills={"discogs": {"enabled": True, "auth_method": "user_token"}},
    )
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(json.dumps(cfg.model_dump(mode="json")), encoding="utf-8")

    router = MagicMock()
    router._resolve_owner_flag.return_value = True
    router._content_root = tmp_path
    router._workspace = cfg
    adapter = MagicMock()
    adapter.send = AsyncMock()
    router._adapters = {"telegram": adapter}
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    handler = MenuFormHandler(
        workspace=cfg,
        router=router,
        conn=conn,
        content_root=tmp_path,
        sevn_json_path=sevn_json,
    )
    insert_dispatcher_state(
        conn,
        token="t1",
        kind="form",
        user_id=1,
        chat_id="1",
        topic_id=None,
        payload_json='{"v":1,"target":"discogs:oauth_start","step":"consumer_key"}',
        ttl_seconds=3600,
    )

    with (
        patch(
            "sevn.gateway.commands.discogs_oauth_wizard.secrets_chain_from_workspace",
            return_value=chain,
        ),
        patch(
            "sevn.gateway.commands.discogs_oauth_wizard.begin_oauth",
            return_value=("req-token", "req-secret", "https://discogs.com/oauth/authorize"),
        ),
        patch(
            "sevn.gateway.commands.discogs_oauth_wizard.complete_oauth",
            return_value=("access-token", "access-secret"),
        ),
    ):
        msg = IncomingMessage(
            channel="telegram",
            user_id="owner",
            text="consumer-key",
            metadata={"chat_id": 1, "owner": True},
        )
        await handler._advance_discogs_oauth(
            msg, token="t1", step="consumer_key", text="consumer-key", payload={}
        )
        await handler._advance_discogs_oauth(
            msg,
            token="t1",
            step="consumer_secret",
            text="consumer-secret",
            payload={},
        )
        await handler._advance_discogs_oauth(
            msg,
            token="t1",
            step="verifier",
            text="verifier-123",
            payload={},
        )

    assert store.get("discogs.oauth_token") == "access-token"
    assert store.get("discogs.oauth_token_secret") == "access-secret"
    assert "discogs.oauth_request_token" not in store
    assert "discogs.oauth_request_secret" not in store

    row = conn.execute(
        "SELECT payload_json FROM dispatcher_state WHERE token = ?",
        ("t1",),
    ).fetchone()
    assert row is not None
    payload_text = str(row[0])
    assert "consumer-key" not in payload_text
    assert "consumer-secret" not in payload_text
    assert "req-token" not in payload_text
    assert "req-secret" not in payload_text
