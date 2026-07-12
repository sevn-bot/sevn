"""Tests for ``.llmignore`` helpers (``specs/09-security-scanner.md`` §9)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from sevn.config.defaults import DEFAULT_SCANNER_MAX_INBOUND_BYTES
from sevn.config.workspace_config import parse_workspace_config
from sevn.security.llm_guard_scanner import BlockReason, ScanResult, ScanVerdict
from sevn.security.llmignore import (
    DEFAULT_INDEX_DENY,
    assert_shadow_workspace_excludes_llmignore,
    is_llmignored,
    resolve_llmignore_root,
    sweep_expired,
    write_blocked_feedback,
    write_blocked_inbound,
)
from sevn.security.sandbox_runtime import materialize_shadow_workspace


def test_default_index_deny_prefixes() -> None:
    assert any(p.startswith(".llmignore") for p in DEFAULT_INDEX_DENY)


def test_resolve_llmignore_root_custom_relative() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "security": {"llmignore": {"path": "var/llm"}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    ws = Path("/tmp") / "ws"
    root = resolve_llmignore_root(ws, cfg)
    assert root.name == "llm"


def test_llmignore_path_rejects_parent_segments() -> None:
    with pytest.raises(ValueError, match=r"llmignore\.path"):
        parse_workspace_config(
            {
                "schema_version": 1,
                "security": {"llmignore": {"path": "a/../b"}},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        )


def test_is_llmignored_normalizes_dotdot(tmp_path: Path) -> None:
    ws = tmp_path / "w"
    ig = ws / ".llmignore" / "blocked"
    ig.mkdir(parents=True)
    sneaky = ws / ".llmignore" / "blocked" / ".." / "blocked" / "x.json"
    assert is_llmignored(sneaky, ws)


def test_write_blocked_inbound_atomic_distinct(tmp_path: Path) -> None:
    vr = ScanResult(
        verdict=ScanVerdict.block,
        reasons=(BlockReason.policy,),
        scores={},
        provider_used=None,
        details={},
    )
    p1 = write_blocked_inbound(tmp_path, text="a", verdict=vr, channel="c", user_id="1")
    p2 = write_blocked_inbound(tmp_path, text="b", verdict=vr, channel="c", user_id="1")
    assert p1 != p2
    assert p1.stat().st_size > 0
    body = p1.read_text(encoding="utf-8")
    assert '"schema_version":1' in body


def test_write_blocked_feedback_channel(tmp_path: Path) -> None:
    vr = ScanResult(
        verdict=ScanVerdict.block,
        reasons=(BlockReason.policy,),
        scores={},
        provider_used=None,
        details={},
    )
    p = write_blocked_feedback(tmp_path, text="fb", verdict=vr, telegram_user_id="99")
    data = p.read_text(encoding="utf-8")
    assert "telegram_webapp_feedback" in data
    assert "blocked_feedback" in data


def test_sweep_expired_removes_old_files(tmp_path: Path) -> None:
    root = tmp_path / "w"
    blocked = root / ".llmignore" / "blocked"
    blocked.mkdir(parents=True)
    stale = blocked / "old.json"
    stale.write_text("{}", encoding="utf-8")
    old = time.time() - 999_999.0
    os.utime(stale, (old, old))
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "security": {
                "llmignore": {"retention_days": {"blocked": 1, "quarantine": 1, "incidents": 1}},
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    n = sweep_expired(root, cfg)
    assert n == 1
    assert not stale.exists()


def test_sweep_uses_config_path(tmp_path: Path) -> None:
    alt = tmp_path / "w"
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "security": {
                "llmignore": {
                    "path": "q",
                    "retention_days": {"blocked": 1, "quarantine": 1, "incidents": 1},
                },
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    quarantine = alt / "q" / "quarantine"
    quarantine.mkdir(parents=True)
    f = quarantine / "x.bin"
    f.write_bytes(b"x")
    old = time.time() - 999_999.0
    os.utime(f, (old, old))
    assert sweep_expired(alt, cfg) >= 1


def test_shadow_materialize_passes_llmignore_assert(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "file.txt").write_text("ok", encoding="utf-8")
    (ws / ".llmignore").mkdir()
    sh = tmp_path / "shadow" / "run"
    materialize_shadow_workspace(ws, sh)
    assert_shadow_workspace_excludes_llmignore(sh)
    assert (sh / "file.txt").is_symlink()


def test_shadow_assert_catches_llmignore_symlink(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    ign = ws / ".llmignore"
    ign.mkdir()
    sh = tmp_path / "shadow" / "bad"
    sh.mkdir(parents=True)
    (sh / "x").symlink_to(ign / "blocked")
    with pytest.raises(AssertionError, match="llmignore"):
        assert_shadow_workspace_excludes_llmignore(sh)


def test_ensure_llmignore_layout_creates_subdirs(tmp_path: Path) -> None:
    from sevn.security.llmignore import ensure_llmignore_layout

    root = ensure_llmignore_layout(tmp_path)
    assert root.is_dir()
    assert (root / "blocked").is_dir()
    assert (root / "quarantine").is_dir()
    assert (root / "incidents").is_dir()


def test_llmignore_retention_defaults_match_spec_3_2() -> None:
    """§3.2 table defaults (blocked 90d / quarantine 30d / incidents 7d)."""
    from sevn.config.defaults import (
        DEFAULT_LLMIGNORE_RETENTION_BLOCKED_DAYS,
        DEFAULT_LLMIGNORE_RETENTION_INCIDENTS_DAYS,
        DEFAULT_LLMIGNORE_RETENTION_QUARANTINE_DAYS,
    )
    from sevn.config.workspace_config import SecurityLlmignoreRetentionSubConfig

    r = SecurityLlmignoreRetentionSubConfig()
    assert r.blocked == DEFAULT_LLMIGNORE_RETENTION_BLOCKED_DAYS == 90
    assert r.quarantine == DEFAULT_LLMIGNORE_RETENTION_QUARANTINE_DAYS == 30
    assert r.incidents == DEFAULT_LLMIGNORE_RETENTION_INCIDENTS_DAYS == 7


def test_write_blocked_inbound_rejects_oversized_payload(tmp_path: Path) -> None:
    huge = "x" * (DEFAULT_SCANNER_MAX_INBOUND_BYTES + 1)
    vr = ScanResult(
        verdict=ScanVerdict.block,
        reasons=(BlockReason.policy,),
        scores={},
        provider_used=None,
        details={},
    )
    with pytest.raises(ValueError, match="blocked inbound text exceeds"):
        write_blocked_inbound(tmp_path, text=huge, verdict=vr, channel="c", user_id="u")
