"""W29 MCP OAuth, logging, and catalog preset tests (#90)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sevn.tools.mcp_catalog import list_mcp_catalog_presets
from sevn.tools.mcp_logging import MCP_LOG_FILENAME, append_mcp_log
from sevn.tools.mcp_oauth import (
    mcp_oauth_secret_alias,
    persist_mcp_oauth_credential,
    resolve_mcp_oauth_env,
)


def test_mcp_oauth_secret_alias() -> None:
    assert mcp_oauth_secret_alias("linear") == "oauth.mcp.linear"


def test_resolve_mcp_oauth_env_injects_access_token() -> None:
    env = resolve_mcp_oauth_env(
        {"oauth": {"env_var": "LINEAR_API_KEY"}},
        {"access_token": "secret-token"},
    )
    assert env == {"LINEAR_API_KEY": "secret-token"}


@pytest.mark.asyncio
async def test_persist_mcp_oauth_credential_uses_secrets_chain() -> None:
    chain = AsyncMock()
    await persist_mcp_oauth_credential(chain, "demo", {"access_token": "tok"})
    chain.set.assert_awaited_once()
    alias, payload = chain.set.await_args.args
    assert alias == "oauth.mcp.demo"
    assert json.loads(payload)["access_token"] == "tok"


def test_append_mcp_log_writes_operator_readable_file(tmp_path: Path) -> None:
    append_mcp_log(tmp_path, "discover_failed", server_id="demo", level="warning", error="boom")
    log_path = tmp_path / "logs" / MCP_LOG_FILENAME
    assert log_path.is_file()
    row = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert row["event"] == "discover_failed"
    assert row["server_id"] == "demo"


def test_catalog_presets_include_safe_defaults() -> None:
    presets = list_mcp_catalog_presets()
    assert presets
    assert all(p.get("safe_default") for p in presets)
    assert any(p["id"] == "code_review_read_only" for p in presets)
