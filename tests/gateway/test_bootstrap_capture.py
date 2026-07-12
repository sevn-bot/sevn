"""Bootstrap workspace writes (`plan/operator-experience-wave-plan.md` Wave 3).

W2 additions (2026-06-04):
- Label-anchored field extraction (no positional 1→Name, 2→Role map).
- Placeholder-only guard on _replace_field_line.
- Tightened Name validator (single token, no stopword/pronoun).
- write=False on _bootstrap_capture_after_turn skips USER.md write.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sevn.gateway.bootstrap_capture import (
    _parse_labeled_bootstrap_fields,
    _replace_field_line,
    extract_bootstrap_name,
    try_bootstrap_user_md_fallback,
)
from sevn.gateway.first_session import bootstrap_completion_state
from sevn.onboarding.seed import seed_narrative_templates
from sevn.storage.migrate import apply_migrations
from sevn.tools.workspace_files import write_workspace_md


def _seed_workspace(tmp_path: Path) -> Path:
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
    seed_narrative_templates(
        sevn_json,
        {
            "schema_version": 1,
            "workspace_root": ".",
            "agent": {"display_name": "Sevn"},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    return tmp_path


def test_extract_bootstrap_name_from_intro() -> None:
    assert extract_bootstrap_name("Hey — I'm Alex, PM in SF") == "Alex"
    assert extract_bootstrap_name("my name is Jordan") == "Jordan"
    assert extract_bootstrap_name("I'm Alex") == "Alex"
    assert extract_bootstrap_name("1. Alex\n2. casual") == "Alex"


def test_try_bootstrap_fallback_patches_numbered_answers(tmp_path: Path) -> None:
    """Full profile with inline labels (label-anchored extraction replaces positional map)."""
    root = _seed_workspace(tmp_path)
    # Role and Preferences require inline labels; bare answers use keyword heuristics.
    user_text = (
        "1. Alex\n"
        "2. role: AI engineer\n"
        "3. America/Los_Angeles\n"
        "4. casual\n"
        "5. English\n"
        "6. preferences: agentic AI and LLM tooling"
    )
    ok = try_bootstrap_user_md_fallback(root, user_text)
    assert ok is True
    text = (root / "USER.md").read_text(encoding="utf-8")
    assert "**Name:** Alex" in text
    assert "**Role:** AI engineer" in text
    assert "**Timezone:** America/Los_Angeles" in text
    assert "**Style:** casual" in text
    assert "**Language:** English" in text
    assert "agentic AI" in text
    assert "user-incomplete" not in text
    assert bootstrap_completion_state(root, agent_name="Sevn") == "complete"


def test_write_workspace_md_strips_marker_for_real_name(tmp_path: Path) -> None:
    root = _seed_workspace(tmp_path)
    write_workspace_md(
        root,
        "USER.md",
        "<!-- sevn-bootstrap:user-incomplete -->\n- **Name:** Alex\n",
    )
    text = (root / "USER.md").read_text(encoding="utf-8")
    assert "user-incomplete" not in text
    assert "Alex" in text


def test_try_bootstrap_fallback_patches_user_md(tmp_path: Path) -> None:
    root = _seed_workspace(tmp_path)
    assert bootstrap_completion_state(root, agent_name="Sevn") == "incomplete"
    ok = try_bootstrap_user_md_fallback(root, "I'm Alex and I run ops here")
    assert ok is True
    text = (root / "USER.md").read_text(encoding="utf-8")
    assert "Alex" in text
    assert "user-incomplete" not in text
    assert bootstrap_completion_state(root, agent_name="Sevn") == "complete"


def test_build_session_registry_includes_write_workspace_md_when_requested() -> None:
    from sevn.tools.registry import build_session_registry

    exe, _ = build_session_registry(include_bootstrap_tools=True)
    names = {d.name for d in exe.definitions()}
    assert "write_workspace_md" in names


# ---------------------------------------------------------------------------
# W2.2 — Label-anchored extraction (no positional 1→Name, 2→Role map)
# ---------------------------------------------------------------------------


def test_incident_message_does_not_set_name(tmp_path: Path) -> None:
    """2026-06-04 incident: '1. I am into AI engineering\n2. amsterdam…' must NOT write Name."""
    root = _seed_workspace(tmp_path)
    user_text = "1. I am into AI engineering\n2. amsterdam time zone"
    # extract_bootstrap_name must reject the multi-word phrase.
    assert extract_bootstrap_name(user_text) is None
    # The fallback write may still set Timezone from 'amsterdam' but must not set Name.
    try_bootstrap_user_md_fallback(root, user_text)
    text = (root / "USER.md").read_text(encoding="utf-8")
    assert "I am into AI engineering" not in text
    assert "_(your preferred name)_" in text  # placeholder unchanged


def test_extract_bootstrap_name_rejects_multiword_phrase() -> None:
    """Multi-word phrases in position 1 are not treated as a Name."""
    assert extract_bootstrap_name("1. I am into AI engineering\n2. amsterdam") is None
    assert extract_bootstrap_name("1. software engineer\n2. casual") is None


def test_extract_bootstrap_name_rejects_stopwords() -> None:
    """Pronouns and stopwords in position 1 are rejected as names."""
    assert extract_bootstrap_name("1. I\n2. casual") is None
    assert extract_bootstrap_name("1. my\n2. casual") is None
    assert extract_bootstrap_name("1. the\n2. casual") is None


def test_inline_label_timezone_sets_only_timezone() -> None:
    """'2. timezone: Amsterdam' sets Timezone only — no Name or other fields."""
    user_text = "2. timezone: Amsterdam"
    fields = _parse_labeled_bootstrap_fields(user_text)
    assert "Timezone" in fields
    assert fields["Timezone"] == "Europe/Amsterdam"
    assert "Name" not in fields
    assert "Role" not in fields


def test_parse_labeled_fields_inline_label_map(tmp_path: Path) -> None:
    """Inline labels on numbered lines map by label, not position."""
    fields = _parse_labeled_bootstrap_fields(
        "1. name: Alex\n2. timezone: Amsterdam\n3. style: casual\n4. language: English\n"
    )
    assert fields.get("Name") == "Alex"
    assert fields.get("Timezone") == "Europe/Amsterdam"
    assert fields.get("Style") == "casual"
    assert fields.get("Language") == "English"


def test_unrelated_text_returns_no_write(tmp_path: Path) -> None:
    """'hello random' contains no confident field — fallback returns False."""
    root = _seed_workspace(tmp_path)
    result = try_bootstrap_user_md_fallback(root, "hello random")
    assert result is False
    text = (root / "USER.md").read_text(encoding="utf-8")
    assert "_(your preferred name)_" in text  # placeholder unchanged


# ---------------------------------------------------------------------------
# W2.3 — Placeholder-only guard on _replace_field_line
# ---------------------------------------------------------------------------


def test_replace_field_line_leaves_non_placeholder_unchanged() -> None:
    """_replace_field_line must NOT overwrite a non-placeholder Name: Alex."""
    lines = ["- **Name:** Alex"]
    result = _replace_field_line(lines, "Name", "Jordan")
    assert result is False
    assert lines == ["- **Name:** Alex"]  # unchanged


def test_replace_field_line_replaces_placeholder() -> None:
    """_replace_field_line replaces a placeholder value."""
    lines = ["- **Name:** _(your preferred name)_"]
    result = _replace_field_line(lines, "Name", "Alex")
    assert result is True
    assert lines == ["- **Name:** Alex"]


def test_existing_name_not_clobbered_by_numbered_message(tmp_path: Path) -> None:
    """Non-placeholder Name: Alex in USER.md must survive any numbered message."""
    root = _seed_workspace(tmp_path)
    # Set a real name first.
    user_md = root / "USER.md"
    content = user_md.read_text(encoding="utf-8")
    content = content.replace("_(your preferred name)_", "Alex")
    user_md.write_text(content, encoding="utf-8")
    # Now run a bootstrap capture with a numbered message that has a different name.
    try_bootstrap_user_md_fallback(root, "1. Jordan\n4. casual")
    text = user_md.read_text(encoding="utf-8")
    assert "**Name:** Alex" in text
    assert "Jordan" not in text


# ---------------------------------------------------------------------------
# W2.1 — write=False skips USER.md write, completion mark still runs
# ---------------------------------------------------------------------------


async def test_bootstrap_capture_after_turn_write_false_no_write(tmp_path: Path) -> None:
    """write=False must not call try_bootstrap_user_md_fallback."""
    from sevn.gateway.agent_turn import _bootstrap_capture_after_turn

    root = _seed_workspace(tmp_path)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_migrations(conn)
    from sevn.gateway.session_manager import SessionManager

    sm = SessionManager(conn)
    session_id = await sm.ensure_session(
        scope_key="webchat:w2-test",
        channel="webchat",
        user_id="w2-test",
    )
    # USER.md is still incomplete — write=False should NOT touch it.
    user_md = root / "USER.md"
    before = user_md.read_text(encoding="utf-8")

    await _bootstrap_capture_after_turn(
        bootstrap_active=True,
        content_root=root,
        user_text="1. Alex\n2. casual",
        agent_name="Sevn",
        conn=conn,
        session_id=session_id,
        write=False,
    )

    after = user_md.read_text(encoding="utf-8")
    # File must be unchanged (no write).
    assert before == after
    # Placeholder still present (no name was written).
    assert "_(your preferred name)_" in after


async def test_bootstrap_capture_after_turn_write_true_does_write(tmp_path: Path) -> None:
    """write=True (default) runs the heuristic write and may update USER.md."""
    from sevn.gateway.agent_turn import _bootstrap_capture_after_turn

    root = _seed_workspace(tmp_path)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_migrations(conn)
    from sevn.gateway.session_manager import SessionManager

    sm = SessionManager(conn)
    session_id = await sm.ensure_session(
        scope_key="webchat:w2-test-write",
        channel="webchat",
        user_id="w2-test-write",
    )

    await _bootstrap_capture_after_turn(
        bootstrap_active=True,
        content_root=root,
        user_text="1. Alex\n4. casual\n5. English",
        agent_name="Sevn",
        conn=conn,
        session_id=session_id,
        write=True,
    )

    text = (root / "USER.md").read_text(encoding="utf-8")
    assert "**Name:** Alex" in text
