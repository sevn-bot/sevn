"""Wave W4.2: new workspace scaffold includes ``SESSIONS.md``."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sevn.onboarding.seed import NARRATIVE_TEMPLATE_NAMES, load_template, seed_narrative_templates


def test_sessions_md_is_packaged_template() -> None:
    body = load_template("SESSIONS.md")
    assert "recall" in body.lower()
    assert "history" in body.lower()


def test_sessions_md_in_narrative_template_names() -> None:
    assert "SESSIONS.md" in NARRATIVE_TEMPLATE_NAMES


def test_seed_narrative_templates_writes_sessions_md() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sj = root / "sevn.json"
        _ = sj.write_text(
            '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
            encoding="utf-8",
        )
        written = seed_narrative_templates(
            sj,
            {
                "schema_version": 1,
                "workspace_root": ".",
                "agent": {"display_name": "Nova"},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        )
        assert any(p.name == "SESSIONS.md" for p in written)
        sessions = root / "SESSIONS.md"
        assert sessions.is_file()
        assert "history" in sessions.read_text(encoding="utf-8").lower()
