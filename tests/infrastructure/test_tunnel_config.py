"""Unit tests for sevn.infrastructure.tunnel_config."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from sevn.infrastructure.tunnel_config import (
    NGROK_AUTHTOKEN_CONFIG_REF,
    build_tunnel_launch,
    normalize_tunnel_mode,
    prepare_tunnel_runtime_cfg,
)


def test_normalize_cloudflare_quick_mode() -> None:
    assert normalize_tunnel_mode("cloudflare-quick") == "cloudflare_quick"


def test_build_tunnel_launch_cloudflare_quick() -> None:
    with patch("shutil.which", return_value="/usr/bin/cloudflared"):
        argv, env = build_tunnel_launch("cloudflare_quick", {"local_port": 3005})
    assert argv == ["/usr/bin/cloudflared", "tunnel", "--url", "http://127.0.0.1:3005"]
    assert env is None


def test_prepare_runtime_cfg_skips_ngrok_secret_for_cloudflare() -> None:
    cfg = {
        "mode": "cloudflare",
        "config_path": "/etc/cloudflared/config.yml",
        "ngrok_authtoken": NGROK_AUTHTOKEN_CONFIG_REF,
    }
    with patch(
        "sevn.security.secrets.value_expand.expand_refs_env_then_secret",
        new_callable=AsyncMock,
    ) as expand:
        resolved = asyncio.run(
            prepare_tunnel_runtime_cfg(
                cfg,
                gateway_port=3001,
                content_root=__import__("pathlib").Path("."),
                secrets_backend=None,
            )
        )
    expand.assert_not_called()
    assert resolved["ngrok_authtoken"] == NGROK_AUTHTOKEN_CONFIG_REF
