"""USER.md bootstrap marker seeding (`plan/control-surface-wave-plan.md` Wave 0B)."""

from __future__ import annotations

import json
from pathlib import Path

from sevn.onboarding.seed import seed_bundled_skills, seed_narrative_templates

_USER_INCOMPLETE_MARKER = "<!-- sevn-bootstrap:user-incomplete -->"


def _seed_empty_workspace(tmp_path: Path, *, agent_name: str = "TestBot") -> None:
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
            "agent": {"display_name": agent_name},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )


def test_user_md_marker_present_after_first_seed(tmp_path: Path) -> None:
    _seed_empty_workspace(tmp_path)
    user_md = (tmp_path / "USER.md").read_text(encoding="utf-8")
    assert user_md.rstrip().endswith(_USER_INCOMPLETE_MARKER)


def test_user_md_marker_absent_when_skipping_edited_file(tmp_path: Path) -> None:
    _seed_empty_workspace(tmp_path)
    user_path = tmp_path / "USER.md"
    user_path.write_text(
        "# User\n\n- **Name:** Alex\n",
        encoding="utf-8",
    )
    sevn_json = tmp_path / "sevn.json"
    written = seed_narrative_templates(
        sevn_json,
        {
            "schema_version": 1,
            "workspace_root": ".",
            "agent": {"display_name": "TestBot"},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
        overwrite=False,
    )
    assert all(p.name != "USER.md" for p in written)
    user_md = user_path.read_text(encoding="utf-8")
    assert _USER_INCOMPLETE_MARKER not in user_md
    assert "Alex" in user_md


def test_narrative_seed_includes_bundled_core_skills(tmp_path: Path) -> None:
    _seed_empty_workspace(tmp_path)
    assert (tmp_path / "skills" / "core" / "canvas" / "SKILL.md").is_file()


def test_seed_bundled_skills_idempotent_skips_existing_package(tmp_path: Path) -> None:
    _seed_empty_workspace(tmp_path)
    canvas = tmp_path / "skills" / "core" / "canvas"
    assert canvas.is_dir()
    marker = canvas / "SKILL.md"
    first_mtime = marker.stat().st_mtime_ns
    again = seed_bundled_skills(tmp_path)
    assert again == []
    assert marker.stat().st_mtime_ns == first_mtime


def test_seed_narrative_rejects_package_checkout(tmp_path: Path) -> None:
    import pytest

    from sevn.workspace.safe_root import UnsafeWorkspaceRootError

    fake_repo = tmp_path / "fake-repo"
    (fake_repo / "src" / "sevn").mkdir(parents=True)
    (fake_repo / "pyproject.toml").write_text("[project]\nname='sevn'\n", encoding="utf-8")
    sevn_json = fake_repo / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    with pytest.raises(UnsafeWorkspaceRootError):
        seed_narrative_templates(
            sevn_json,
            {
                "schema_version": 1,
                "workspace_root": ".",
                "agent": {"display_name": "X"},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        )
