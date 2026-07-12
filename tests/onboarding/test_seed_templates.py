"""Packaged workspace narrative templates (`specs/22-onboarding.md` §4.8)."""

from __future__ import annotations

import json
from pathlib import Path

from sevn.onboarding.seed import (
    NARRATIVE_TEMPLATE_NAMES,
    load_template,
    render_template,
    resolve_agent_display_name,
    seed_narrative_templates,
)


def test_narrative_template_names_complete() -> None:
    assert set(NARRATIVE_TEMPLATE_NAMES) == {
        "AGENTS.md",
        "AGENTS-detail.md",
        "sevn.bot.md",
        "BOOTSTRAP.md",
        "IDENTITY.md",
        "MEMORY.md",
        "SESSIONS.md",
        "SEVN-ARCHITECTURE.md",
        "SOUL.md",
        "TOOLS.md",
        "USER.md",
        "WORKSPACE.md",
    }


def test_all_packaged_templates_load() -> None:
    for name in NARRATIVE_TEMPLATE_NAMES:
        body = load_template(name)
        assert body.strip(), name
        assert body.startswith("#"), name


def test_resolve_agent_display_name_defaults() -> None:
    assert resolve_agent_display_name({}) == "Sevn"
    assert resolve_agent_display_name({"agent": {"display_name": "  Nova  "}}) == "Nova"


def test_render_template_substitutes_agent_name() -> None:
    assert render_template("Hi {{AGENT_NAME}}", "Nova") == "Hi Nova"


def test_seed_writes_identity_with_wizard_name(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    merged = {
        "schema_version": 1,
        "workspace_root": ".",
        "agent": {"display_name": "TestBot"},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    written = seed_narrative_templates(sevn_json, merged)
    names = {p.name for p in written}
    assert "IDENTITY.md" in names
    identity = (tmp_path / "IDENTITY.md").read_text(encoding="utf-8")
    assert "TestBot" in identity
    assert "Name" in identity or "## Name" in identity
    soul = (tmp_path / "SOUL.md").read_text(encoding="utf-8")
    assert "TestBot" in soul


def test_seed_skips_existing_memory(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "MEMORY.md").write_text("operator notes", encoding="utf-8")
    written = seed_narrative_templates(
        sevn_json,
        {
            "schema_version": 1,
            "workspace_root": ".",
            "agent": {"display_name": "X"},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    assert all(p.name != "MEMORY.md" for p in written)
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == "operator notes"
