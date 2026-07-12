"""AGENTS.md backtick names must match packaged registry manifests."""

from __future__ import annotations

import re

from sevn.onboarding.seed import load_template, render_template
from sevn.tools.registry import DEFAULT_SKILL_MANIFESTS, DEFAULT_TOOL_MANIFESTS

_NOT_YET_AVAILABLE_MARKER = "not yet available in this workspace"
_REGISTRY_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
# Greeting examples in AGENTS.md "Short messages" are not tool names.
_NON_REGISTRY_BACKTICK_NAMES = frozenset({"hi", "thanks", "ok", "bye"})
# One-release skill index alias (`specs/28-code-understanding.md`).
_SKILL_INDEX_ALIASES = frozenset({"mycode_scan"})
# Bundled but not in DEFAULT_SKILL_MANIFESTS (host-only / quarantined from gateway index).
_QUARANTINED_BUNDLED_CORE_SKILL_DIRS = frozenset({"mycode_scan", "telegram_test", "kokoro-tts"})


def _allowed_registry_backtick_names() -> frozenset[str]:
    """Return tool and skill names AGENTS.md may cite in backticks.

    Returns:
        frozenset[str]: Packaged default manifests plus known skill aliases.

    Examples:
        >>> "load_tool" in _allowed_registry_backtick_names()
        True
    """
    return (
        frozenset(DEFAULT_TOOL_MANIFESTS)
        | frozenset(DEFAULT_SKILL_MANIFESTS)
        | _SKILL_INDEX_ALIASES
        | _QUARANTINED_BUNDLED_CORE_SKILL_DIRS
    )


def test_agents_md_has_no_shipped_capability_gaps() -> None:
    """Shipped capabilities must not carry the workspace gap marker."""
    rendered = render_template(load_template("AGENTS.md"), "TestBot")
    assert _NOT_YET_AVAILABLE_MARKER not in rendered


def test_agents_md_backtick_names_match_registry() -> None:
    """Every registry-shaped backtick token in AGENTS.md is a known tool or skill."""
    rendered = render_template(load_template("AGENTS.md"), "TestBot")
    allowed = _allowed_registry_backtick_names()
    for line in rendered.splitlines():
        for name in re.findall(r"`([^`]+)`", line):
            if name in allowed or name in _NON_REGISTRY_BACKTICK_NAMES:
                continue
            if not _REGISTRY_NAME_PATTERN.fullmatch(name):
                continue
            msg = f"AGENTS.md mentions unregistered tool/skill {name!r}: {line.strip()}"
            raise AssertionError(msg)


def test_default_skill_manifests_cover_bundled_core_skills() -> None:
    """Every bundled core skill directory has a DEFAULT_SKILL_MANIFESTS row."""
    from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT

    core_names = {
        path.parent.name
        for path in (BUNDLED_SKILLS_ROOT / "core").glob("*/SKILL.md")
        if path.parent.name not in _QUARANTINED_BUNDLED_CORE_SKILL_DIRS
    }
    missing = sorted(core_names - set(DEFAULT_SKILL_MANIFESTS))
    assert not missing, f"DEFAULT_SKILL_MANIFESTS missing bundled core skills: {missing}"
