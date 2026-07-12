"""Boot trace when IDENTITY/USER bootstrap placeholders remain (W8)."""

from __future__ import annotations

from pathlib import Path

from sevn.agent.identity_reply import identity_bootstrap_incomplete_fields
from sevn.onboarding.seed import load_template


def test_bootstrap_incomplete_fields_for_seeded_identity(tmp_path: Path) -> None:
    root = tmp_path
    (root / "IDENTITY.md").write_text(load_template("IDENTITY.md"), encoding="utf-8")
    fields = identity_bootstrap_incomplete_fields(root)
    assert "IDENTITY.md:Name" in fields


def test_bootstrap_complete_identity_name_resolves(tmp_path: Path) -> None:
    root = tmp_path
    (root / "IDENTITY.md").write_text("## Name\n\ntestmee\n", encoding="utf-8")
    assert "IDENTITY.md:Name" not in identity_bootstrap_incomplete_fields(root)
