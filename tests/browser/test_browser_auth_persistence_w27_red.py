"""Batch F W27 RED: browser auth reuse (#92) and credential storage policy (→ W28)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from loguru import logger as loguru_logger

from sevn.browser.chrome import resolve_profile_dir
from sevn.config.workspace_config import WorkspaceConfig


def test_profile_dirs_isolated_per_session(tmp_path: Path) -> None:
    """Per-profile isolation: distinct session ids resolve distinct profile dirs."""
    root = tmp_path / "content"
    root.mkdir()
    a = resolve_profile_dir(root, "telegram:1:general")
    b = resolve_profile_dir(root, "telegram:2:general")
    assert a != b
    assert a.name == "telegram-1-general"
    assert b.name == "telegram-2-general"


def test_stable_profile_dir_when_skills_browser_profile_configured(tmp_path: Path) -> None:
    """Operator-configured ``skills.browser.profile_dir`` is shared across sessions."""
    root = tmp_path / "content"
    root.mkdir()
    shared = tmp_path / "operator-chrome-profile"
    cfg = WorkspaceConfig.minimal()
    cfg.skills = {"browser": {"profile_dir": str(shared)}}
    first = resolve_profile_dir(root, "session-a", cfg=cfg)
    second = resolve_profile_dir(root, "session-b", cfg=cfg)
    assert first == second == shared.expanduser().resolve()


@pytest.mark.xfail(reason="green after W28: cross-restart browser session state", strict=False)
def test_session_cookies_survive_simulated_gateway_restart(tmp_path: Path) -> None:
    """Cookies/session markers written for a profile survive a tool/gateway restart."""
    from sevn.browser.persistence import (
        persist_browser_session_marker,
        read_browser_session_marker,
    )

    root = tmp_path / "content"
    root.mkdir()
    session_id = "telegram:99:auth"
    profile_dir = resolve_profile_dir(root, session_id)
    profile_dir.mkdir(parents=True, exist_ok=True)

    marker = {"cookie": "sid=abc123", "site": "example.com"}
    persist_browser_session_marker(profile_dir, marker)
    assert read_browser_session_marker(profile_dir) == marker

    # Simulated restart: new process, same profile resolution path.
    profile_after_restart = resolve_profile_dir(root, session_id)
    assert profile_after_restart == profile_dir
    assert read_browser_session_marker(profile_after_restart) == marker


@pytest.mark.xfail(reason="green after W28: ephemeral/no-persistence browser mode", strict=False)
def test_ephemeral_profile_mode_uses_non_persistent_directory(tmp_path: Path) -> None:
    """Sensitive tasks can opt into an ephemeral profile outside the persistent tree."""
    from sevn.browser.persistence import resolve_browser_profile_dir

    root = tmp_path / "content"
    root.mkdir()
    cfg = WorkspaceConfig.minimal()
    persistent = resolve_profile_dir(root, "sensitive-task", cfg=cfg)
    ephemeral = resolve_browser_profile_dir(
        root,
        "sensitive-task",
        cfg=cfg,
        ephemeral=True,
    )
    assert ephemeral != persistent
    assert persistent.parent.name == "browser-profiles"
    assert not str(ephemeral).startswith(str(persistent.parent))


@pytest.mark.xfail(reason="green after W28: credential path redaction in logs", strict=False)
def test_browser_profile_paths_redacted_in_log_lines(tmp_path: Path) -> None:
    """Cookie/password profile paths must not appear verbatim in log output."""
    from sevn.browser.redaction import redact_browser_credential_paths

    secret_path = (
        tmp_path / "content" / ".sevn" / "browser-profiles" / "sess" / "Default" / "Cookies"
    )
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_bytes(b"\x00")

    raw = f"loaded cookies from {secret_path}"
    redacted = redact_browser_credential_paths(raw)
    assert str(secret_path) not in redacted
    assert "Cookies" not in redacted or "<redacted" in redacted.lower()


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W28: cookie paths redacted in tool output", strict=False)
async def test_get_cookies_tool_output_redacts_absolute_paths(
    tmp_path: Path,
    fake_cdp: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Browser tool responses must not echo raw cookie-store filesystem paths."""
    from sevn.browser.lifecycle import CDPBrowserSession
    from sevn.browser.redaction import redact_browser_tool_payload
    from sevn.tools import browser as browser_mod
    from sevn.tools.context import ToolContext

    fake_cdp.set_result(
        "Target.getTargets",
        {"targetInfos": [{"targetId": "p1", "type": "page", "url": "https://a", "title": "A"}]},
    )
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S1"})
    fake_cdp.set_result("Network.getAllCookies", {"cookies": [{"name": "sid", "value": "x"}]})
    session = await CDPBrowserSession.attach_ws(fake_cdp.ws_url)

    async def _get(
        content_root: object, session_id: object, *, cfg: object = None
    ) -> CDPBrowserSession:
        return session

    monkeypatch.setattr("sevn.browser.lifecycle.get_or_create_session", _get)
    ctx = ToolContext(
        session_id="redact-sess",
        workspace_path=tmp_path,
        workspace_id="wid",
        registry_version=1,
    )
    profile_dir = resolve_profile_dir(tmp_path, "redact-sess")
    profile_dir.mkdir(parents=True, exist_ok=True)
    cookie_file = profile_dir / "Default" / "Cookies"
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_bytes(b"\x00")

    try:
        envelope = await browser_mod.browser_tool(ctx, action="get_cookies")
        safe = redact_browser_tool_payload(envelope, profile_dir=profile_dir)
        blob = json.dumps(safe)
        assert str(cookie_file) not in blob
        assert str(profile_dir / "Default") not in blob
    finally:
        await session.disconnect()


@pytest.mark.xfail(
    reason="green after W28: credentials never written to plaintext workspace files",
    strict=False,
)
def test_login_credentials_not_persisted_as_plaintext_workspace_files(tmp_path: Path) -> None:
    """Credential material must never land in a plaintext file under the workspace."""
    from sevn.browser.redaction import assert_no_plaintext_browser_credentials

    root = tmp_path / "content"
    root.mkdir()
    password = "never-on-disk-plaintext"
    assert_no_plaintext_browser_credentials(root, sample_secret=password)
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".txt", ".md", ".env"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            assert password not in text


@pytest.mark.xfail(reason="green after W28: spawn logs redact profile paths", strict=False)
def test_chrome_spawn_log_line_redacts_profile_dir(tmp_path: Path) -> None:
    """Chrome spawn diagnostics must redact ``--user-data-dir`` values."""
    from sevn.browser.redaction import redact_browser_credential_paths

    profile = resolve_profile_dir(tmp_path, "log-redact")
    profile.mkdir(parents=True, exist_ok=True)
    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="DEBUG")
    try:
        loguru_logger.debug("spawn chrome user-data-dir={}", profile)
    finally:
        loguru_logger.remove(sink_id)
    joined = "\n".join(captured)
    safe = redact_browser_credential_paths(joined)
    assert str(profile) not in safe
