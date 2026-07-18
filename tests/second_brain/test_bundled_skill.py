"""Bundled ``second_brain`` skill is discoverable with default skills roots."""

from __future__ import annotations

from pathlib import Path

from sevn.config.workspace_config import parse_workspace_config
from sevn.skills.manager import SkillsManager
from sevn.workspace.layout import WorkspaceLayout


def test_default_skills_scan_includes_packaged_second_brain(tmp_path: Path) -> None:
    """Default skill roots resolve bundled Second Brain and Obsidian skills.

    Examples:
        >>> expected_id = "obsidian-markdown"
        >>> expected_id == "obsidian-markdown"
        True
    """
    SkillsManager.reset_singletons_for_tests()
    try:
        (tmp_path / "skills").mkdir()
        lay = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
        man = SkillsManager.shared(
            tmp_path,
            layout=lay,
            config=parse_workspace_config(
                {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
            ),
        )
        expected = {
            "defuddle",
            "json-canvas",
            "obsidian-bases",
            "obsidian-cli",
            "obsidian-markdown",
            "second_brain",
        }
        for skill_id in expected:
            assert man.get_record(skill_id).canonical_id == skill_id
    finally:
        SkillsManager.reset_singletons_for_tests()
