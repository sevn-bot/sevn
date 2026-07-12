"""Tests for browser profile/registry GC and idle-close helpers (Wave W4)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sevn.config.workspace_config import WorkspaceConfig
from sevn.skills.browser_gc import prune_orphan_browser_profiles
from sevn.skills.browser_session import (
    BrowserSessionRegistry,
    CloseBrowserResult,
    close_idle_browser_sessions,
    resolve_idle_close_seconds,
    write_registry,
)


def test_prune_orphan_browser_profiles(tmp_path: Path) -> None:
    content = tmp_path / "ws"
    stale_profile = content / ".sevn" / "browser-profiles" / "gone-session"
    stale_profile.mkdir(parents=True)
    (stale_profile / "Cookies").write_text("data", encoding="utf-8")
    kept_profile = content / ".sevn" / "browser-profiles" / "live-session"
    kept_profile.mkdir(parents=True)
    (kept_profile / "Cookies").write_text("keep", encoding="utf-8")

    stale_reg = content / ".sevn" / "browser-sessions" / "gone-session.json"
    stale_reg.parent.mkdir(parents=True, exist_ok=True)
    stale_reg.write_text('{"pid": 1}', encoding="utf-8")
    kept_reg = content / ".sevn" / "browser-sessions" / "live-session.json"
    kept_reg.write_text('{"pid": 2}', encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE gateway_sessions (session_id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO gateway_sessions (session_id) VALUES ('live-session')")
    conn.commit()

    n = prune_orphan_browser_profiles(content_root=content, conn=conn)
    assert n == 2
    assert not stale_profile.exists()
    assert not stale_reg.exists()
    assert (kept_profile / "Cookies").is_file()
    assert kept_reg.is_file()


def test_prune_noop_when_browser_dirs_missing(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE gateway_sessions (session_id TEXT PRIMARY KEY)")
    conn.commit()
    assert prune_orphan_browser_profiles(content_root=tmp_path, conn=conn) == 0


def test_resolve_idle_close_seconds_reads_cfg() -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        skills={"browser": {"idle_close_seconds": 120}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert resolve_idle_close_seconds(cfg) == 120
    assert resolve_idle_close_seconds(None) == 0


def test_idle_close_respects_ttl(tmp_path: Path) -> None:
    content = tmp_path / "ws"
    stale_at = (datetime.now(tz=UTC) - timedelta(seconds=600)).isoformat()
    fresh_at = datetime.now(tz=UTC).isoformat()
    stale_row = BrowserSessionRegistry(
        pid=111,
        cdp_url="http://127.0.0.1:9333",
        cdp_port=9333,
        profile_dir=str(content / "p1"),
        headless=False,
        spawned_by_sevn=True,
        last_used_at=stale_at,
    )
    fresh_row = BrowserSessionRegistry(
        pid=222,
        cdp_url="http://127.0.0.1:9334",
        cdp_port=9334,
        profile_dir=str(content / "p2"),
        headless=False,
        spawned_by_sevn=True,
        last_used_at=fresh_at,
    )
    write_registry(content, "stale-session", stale_row)
    write_registry(content, "fresh-session", fresh_row)

    with patch("sevn.skills.browser_session.close_browser_session") as mock_close:
        mock_close.return_value = CloseBrowserResult(
            ok=True,
            code="CLOSED",
            message="terminated",
        )
        closed = close_idle_browser_sessions(content_root=content, idle_seconds=300)
        assert closed == 1
        mock_close.assert_called_once_with(content, "stale-session")
