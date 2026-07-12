"""Bundled ``second_brain`` live ingest script tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sevn.second_brain.frontmatter import split_frontmatter
from sevn.second_brain.ingest import run_ingest
from sevn.second_brain.paths import raw_dir_for_scope, user_scope_root, vault_root

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "second_brain"
)
_SCRIPTS = _SKILL_ROOT / "scripts"


def _run_script(
    script_name: str,
    workspace: Path,
    cli_args: list[str] | None = None,
) -> dict[str, object]:
    script = _SCRIPTS / script_name
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    proc = subprocess.run(
        [sys.executable, str(script), *(cli_args or [])],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout.strip())
    assert payload.get("ok") is True
    return payload


def test_live_ingest_script_creates_wiki_page(tmp_path: Path) -> None:
    """``ingest.py`` writes a live page with source excerpt and index/log."""
    vault = vault_root(tmp_path)
    scope_path = user_scope_root(vault, "owner")
    raw = raw_dir_for_scope(scope_path)
    raw.mkdir(parents=True)
    (raw / "note.md").write_text("# My Note\n\nImportant content.", encoding="utf-8")

    payload = _run_script("ingest.py", tmp_path, ["--raw", "note.md"])
    data = payload["data"]
    assert isinstance(data, dict)
    assert data.get("skipped") is False
    assert data.get("promoted") is False

    wiki = scope_path / "wiki"
    page = wiki / "ingests" / "note.md"
    assert page.is_file()
    fm, body, _ = split_frontmatter(page.read_text(encoding="utf-8"))
    assert fm.get("stub") is False
    assert fm.get("type") == "Ingest"
    assert fm.get("sevn_raw_hash")
    assert "Important content." in body
    assert "[Source: note.md]" in body
    assert (wiki / "index.md").is_file()
    assert (wiki / "log.md").is_file()


def test_live_ingest_idempotent_on_unchanged_raw(tmp_path: Path) -> None:
    """Re-ingesting unchanged raw skips body rewrite."""
    vault = vault_root(tmp_path)
    scope_path = user_scope_root(vault, "owner")
    raw = raw_dir_for_scope(scope_path)
    raw.mkdir(parents=True)
    (raw / "note.md").write_text("# Stable\n\nSame bytes.", encoding="utf-8")

    first = run_ingest(
        workspace_root=tmp_path,
        vault_users_scope=scope_path,
        raw_relpath="note.md",
        sevn_source="test",
    )
    assert first["skipped"] is False
    page = scope_path / "wiki" / "ingests" / "note.md"
    before = page.read_text(encoding="utf-8")

    second = run_ingest(
        workspace_root=tmp_path,
        vault_users_scope=scope_path,
        raw_relpath="note.md",
        sevn_source="test",
    )
    assert second["skipped"] is True
    assert page.read_text(encoding="utf-8") == before


def test_live_ingest_respects_promoted_page(tmp_path: Path) -> None:
    """Human-promoted pages (``stub: false``) are never overwritten."""
    vault = vault_root(tmp_path)
    scope_path = user_scope_root(vault, "owner")
    raw = raw_dir_for_scope(scope_path)
    raw.mkdir(parents=True)
    (raw / "note.md").write_text("raw v2", encoding="utf-8")

    wiki = scope_path / "wiki" / "ingests"
    wiki.mkdir(parents=True)
    promoted_body = "---\ntitle: Promoted\nstub: false\n---\n# Human edit\n"
    page = wiki / "note.md"
    page.write_text(promoted_body, encoding="utf-8")

    out = run_ingest(
        workspace_root=tmp_path,
        vault_users_scope=scope_path,
        raw_relpath="note.md",
        sevn_source="test",
    )
    assert out["promoted"] is True
    assert out["skipped"] is True
    assert page.read_text(encoding="utf-8") == promoted_body
