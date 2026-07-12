"""Packaged workspace templates must not cite internal project paths."""

from __future__ import annotations

import re

from sevn.onboarding.seed import NARRATIVE_TEMPLATE_NAMES, load_template, render_template
from tests.data.test_agents_md_registry_parity import (
    _NON_REGISTRY_BACKTICK_NAMES,
    _NOT_YET_AVAILABLE_MARKER,
    _REGISTRY_NAME_PATTERN,
    _allowed_registry_backtick_names,
)

_INTERNAL_PATH_PATTERN = re.compile(r"(?:specs/|prd/|plan/)")

_AGENTS_SECTION_HEADINGS: tuple[str, ...] = (
    "First Run",
    "Session Startup",
    "Short messages",
    "Core capabilities",
    "Decomposition rule",
    "Workspace layout",
    "Memory subsystems",
    "Red lines",
    "External vs Internal",
    "Group chats / topics",
    "Platform formatting",
    "Safety",
    "Make it yours",
)


def test_rendered_workspace_templates_are_self_contained() -> None:
    for name in NARRATIVE_TEMPLATE_NAMES:
        rendered = render_template(load_template(name), "TestBot")
        match = _INTERNAL_PATH_PATTERN.search(rendered)
        assert match is None, f"{name} cites internal path: {match.group(0)!r}"


def test_rendered_bootstrap_references_workspace_files() -> None:
    rendered = render_template(load_template("BOOTSTRAP.md"), "TestBot")
    assert "USER.md" in rendered
    assert "SOUL.md" in rendered
    assert "IDENTITY.md" in rendered
    assert "delete this file" not in rendered.lower()


def test_rendered_agents_md_contains_operating_manual_sections() -> None:
    rendered = render_template(load_template("AGENTS.md"), "TestBot")
    for heading in _AGENTS_SECTION_HEADINGS:
        assert f"## {heading}" in rendered, f"AGENTS.md missing section heading: {heading!r}"


def test_rendered_agents_md_tool_and_skill_names_are_registered() -> None:
    rendered = render_template(load_template("AGENTS.md"), "TestBot")
    allowed = _allowed_registry_backtick_names()
    for line in rendered.splitlines():
        if _NOT_YET_AVAILABLE_MARKER in line:
            continue
        for name in re.findall(r"`([^`]+)`", line):
            if name in allowed or name in _NON_REGISTRY_BACKTICK_NAMES:
                continue
            if not _REGISTRY_NAME_PATTERN.fullmatch(name):
                continue
            msg = f"AGENTS.md mentions unregistered tool/skill {name!r}: {line.strip()}"
            raise AssertionError(msg)


def test_wave_8_tools_md_has_registry_markers_and_local_notes() -> None:
    rendered = render_template(load_template("TOOLS.md"), "TestBot")
    assert "sevn:tools-registry:begin" in rendered
    assert "What goes here" in rendered
    assert "Why separate" in rendered
    assert "WORKSPACE.md" in rendered


def test_workspace_md_template_is_self_contained() -> None:
    rendered = render_template(load_template("WORKSPACE.md"), "TestBot")
    match = _INTERNAL_PATH_PATTERN.search(rendered)
    assert match is None, f"WORKSPACE.md cites internal path: {match.group(0)!r}"
    assert ".sevn/" in rendered
    assert "WORKSPACE.md" in rendered


def test_wave_8_memory_md_mentions_memory_subsystems() -> None:
    rendered = render_template(load_template("MEMORY.md"), "TestBot")
    assert any(term in rendered for term in ("LCM", "Honcho", "dreaming", "Dreaming"))


def test_wave_8_polished_templates_reference_workspace_docs() -> None:
    user = render_template(load_template("USER.md"), "TestBot")
    soul = render_template(load_template("SOUL.md"), "TestBot")
    assert "BOOTSTRAP.md" in user
    assert "AGENTS.md" in user
    assert "BOOTSTRAP.md" in soul
    assert "AGENTS.md" in soul


def test_wave_8_identity_has_vibe_and_emoji_placeholders() -> None:
    rendered = render_template(load_template("IDENTITY.md"), "TestBot")
    assert "## Vibe" in rendered
    assert "## Emoji" in rendered
