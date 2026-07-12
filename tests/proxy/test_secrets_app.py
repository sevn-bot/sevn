"""Integration: proxy app wires ``secrets_cache`` when workspace is supplied."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from pathlib import Path
from unittest.mock import patch

import httpx
from starlette.testclient import TestClient

from sevn.config.workspace_config import parse_workspace_config
from sevn.proxy.app import create_app
from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend
from sevn.security.secrets.chain import SecretsChain


def test_create_app_sets_secrets_cache_when_workspace_configured(tmp_path: Path) -> None:
    """``app.state.secrets_cache`` is non-``None`` when config + content root are passed."""
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "secrets_backend": {"chain": [{"type": "encrypted_file"}]},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    app = create_app(workspace_config=cfg, content_root=Path(tmp_path))
    with TestClient(app) as client:
        assert client.app.state.secrets_cache is not None
        assert client.app.state.secrets_cache.ttl_seconds >= 0


def test_factory_boot_loads_provider_key_from_secrets(tmp_path: Path) -> None:
    """``create_app()`` with ``SEVN_HOME`` resolves per-provider bindings at boot."""
    home = tmp_path / "op"
    workspace = home / "workspace"
    workspace.mkdir(parents=True)
    store = workspace / "store.enc"
    mk = secrets.token_bytes(32)
    backend = EncryptedFileBackend(store, master_key=mk)
    chain = SecretsChain([backend], backend_labels=["encrypted_file"])
    asyncio.run(chain.set("SEVN_SECRET_MINIMAX", "PLACEHOLDER_PROVIDER"))

    sevn_json = {
        "schema_version": 1,
        "workspace_root": ".",
        "secrets_backend": {
            "chain": [{"type": "encrypted_file", "path": "store.enc", "key_source": "master_key"}],
        },
        "providers": {
            "tier_default": {"triager": "minimax/MiniMax-M2.7"},
            "minimax": {"api_key": "${SECRET:SEVN_SECRET_MINIMAX}"},
        },
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    (workspace / "sevn.json").write_text(json.dumps(sevn_json), encoding="utf-8")
    os.environ["SEVN_SECRETS_MASTER_KEY"] = mk.hex()

    captured: dict[str, str] = {}

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        url = kwargs.get("url")
        body = kwargs.get("body")
        hdrs = kwargs.get("headers")
        assert isinstance(hdrs, dict)
        assert isinstance(url, str)
        captured["url"] = url
        captured["x-api-key"] = str(hdrs.get("x-api-key", ""))
        if isinstance(body, dict):
            captured["model"] = str(body.get("model", ""))
        return httpx.Response(200, json={"id": "msg"})

    with patch.dict(os.environ, {"SEVN_HOME": str(home)}, clear=False):
        app = create_app()
    try:
        with (
            patch("sevn.proxy.app.post_json", capture_post_json),
            TestClient(app) as client,
        ):
            provider_creds = client.app.state.provider_credentials
            assert provider_creds.by_name["minimax"].api_key == "PLACEHOLDER_PROVIDER"
            resp = client.post(
                "/llm/anthropic/messages",
                json={"model": "minimax/MiniMax-M2.7", "messages": []},
            )
        assert resp.status_code == 200
        assert captured["x-api-key"] == "PLACEHOLDER_PROVIDER"
        assert captured["model"] == "MiniMax-M2.7"
        assert captured["url"].endswith("/anthropic/v1/messages")
    finally:
        os.environ.pop("SEVN_SECRETS_MASTER_KEY", None)
