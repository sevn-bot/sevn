"""Personality fast-start seeding (onboarding comprehensive setup W8)."""

from __future__ import annotations

import json
from pathlib import Path

from sevn.gateway.bootstrap.bootstrap_state import bootstrap_completion_state
from sevn.onboarding.seed import (
    load_personality_presets,
    seed_narrative_templates,
    seed_personality_from_wizard,
)

_USER_INCOMPLETE_MARKER = "<!-- sevn-bootstrap:user-incomplete -->"


def _write_sevn_json(tmp_path: Path, merged: dict) -> Path:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(json.dumps(merged), encoding="utf-8")
    return sevn_json


def _seed_workspace(tmp_path: Path, merged: dict) -> None:
    sevn_json = _write_sevn_json(tmp_path, merged)
    seed_narrative_templates(sevn_json, merged)


def test_load_personality_presets_has_ten_options_each() -> None:
    presets = load_personality_presets()
    assert len(presets["style"]) == 10
    assert len(presets["preferences"]) == 10
    assert presets["languages"] == ["English"]
    assert len(presets["vibes"]) == 10
    assert len(presets["emojis"]) == 20


def test_seed_personality_skips_when_all_empty(tmp_path: Path) -> None:
    merged = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        "onboarding": {"personality": {}},
    }
    _seed_workspace(tmp_path, merged)
    written = seed_personality_from_wizard(tmp_path, merged)
    assert written == []
    user_md = (tmp_path / "USER.md").read_text(encoding="utf-8")
    assert user_md.rstrip().endswith(_USER_INCOMPLETE_MARKER)


def test_seed_personality_writes_user_identity_and_removes_bootstrap(tmp_path: Path) -> None:
    merged = {
        "schema_version": 1,
        "workspace_root": ".",
        "agent": {"display_name": "Nova"},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        "onboarding": {
            "personality": {
                "name": "Alex",
                "role": "Engineer",
                "timezone": "America/New_York",
                "style": "Brief and direct",
                "style_detail": "no fluff",
                "language": "English",
                "preferences": "Prefer open-source tools",
                "preferences_detail": "avoid SaaS lock-in",
                "vibe": "calm co-pilot",
                "emoji": "🌿",
            }
        },
    }
    _seed_workspace(tmp_path, merged)
    written = seed_personality_from_wizard(tmp_path, merged)
    names = {p.name for p in written}
    assert {"USER.md", "IDENTITY.md", "SOUL.md"}.issubset(names)
    user_md = (tmp_path / "USER.md").read_text(encoding="utf-8")
    assert "**Name:** Alex" in user_md
    assert "Brief and direct. no fluff" in user_md
    assert "Prefer open-source tools. avoid SaaS lock-in" in user_md
    assert _USER_INCOMPLETE_MARKER not in user_md
    identity_md = (tmp_path / "IDENTITY.md").read_text(encoding="utf-8")
    assert "calm co-pilot" in identity_md
    assert "🌿" in identity_md
    soul_md = (tmp_path / "SOUL.md").read_text(encoding="utf-8")
    assert "calm co-pilot" in soul_md
    assert not (tmp_path / "BOOTSTRAP.md").is_file()
    assert bootstrap_completion_state(tmp_path, agent_name="Nova") == "complete"


def test_seed_personality_without_name_keeps_marker_and_bootstrap(tmp_path: Path) -> None:
    merged = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        "onboarding": {"personality": {"vibe": "sharp analyst", "emoji": "⚡"}},
    }
    _seed_workspace(tmp_path, merged)
    seed_personality_from_wizard(tmp_path, merged)
    user_md = (tmp_path / "USER.md").read_text(encoding="utf-8")
    assert _USER_INCOMPLETE_MARKER in user_md
    assert (tmp_path / "BOOTSTRAP.md").is_file()
    assert bootstrap_completion_state(tmp_path, agent_name="Sevn") == "incomplete"
