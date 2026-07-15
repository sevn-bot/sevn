"""Telegram ``/config`` section → ``sevn.json`` dot-path SSOT (D14).

Module: sevn.cli.config_paths
Depends: dataclasses, re, sevn.gateway.menu.menu_registry

Exports:
    ConfigSection — one ``/config`` root section and its schema dot-paths.
    iter_config_sections — canonical section order from ``menu_registry``.
    section_by_slug — lookup by section slug.
    section_callback — ``cfg:section:{slug}`` callback string.
    menu_registry_root_slugs — slugs from live ``MENU_BUTTON_SPECS``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sevn.gateway.menu.menu_registry import MENU_BUTTON_SPECS

_SECTION_CALLBACK_RE = re.compile(r"^\^cfg:section:([^\\$]+)\$$")


@dataclass(frozen=True)
class ConfigSection:
    """One Telegram ``/config`` root tile and its ``sevn.json`` key paths."""

    slug: str
    label: str
    callback: str
    dot_paths: tuple[str, ...]


# Menu-registry ``section`` field(s) whose ``cfg:toggle:*`` paths belong to a root slug.
_SLUG_MENU_SECTIONS: dict[str, tuple[str, ...]] = {
    "session": ("session",),
    "agents": ("agents",),
    "models": ("models",),
    "voice": ("voice",),
    "channels": ("channels",),
    "secrets": ("secrets",),
    "skills": ("skills",),
    "tools": ("tools",),
    "code": ("code",),
    "security": ("security",),
    "integrations": ("integrations",),
    "dashboard": ("dashboard",),
    "shortcuts": ("shortcuts",),
    "notifications": ("notifications",),
    "advanced": (
        "advanced",
        "codemode",
        "rlm",
        "self_improve",
        "second_brain",
        "subagents",
        "subagents_running",
    ),
    "logs": ("logs",),
    "help": ("help",),
    "sevn_bot": ("sevn_bot",),
    "my_sevn_bot": ("my_sevn_bot",),
}

# Non-toggle schema keys surfaced in a section (forms / Mission Control parity).
_EXTRA_DOT_PATHS: dict[str, tuple[str, ...]] = {
    "agents": ("agent.display_name",),
    "models": (
        "agent.triager.model",
        "agent.tier_b.model",
        "agent.tier_cd.model",
        "agent.unified_model.enabled",
    ),
    "voice": ("channels.telegram.tts_mode",),
    "dashboard": ("channels.telegram.pinned_status",),
    "advanced": (
        "second_brain.paths.vault",
        "second_brain.layout",
        "second_brain.para.inbox",
        "second_brain.para.projects",
        "second_brain.para.areas",
        "second_brain.para.resources",
        "second_brain.para.archive",
        "second_brain.para.templates",
        "second_brain.para.sources_subdir",
        "second_brain.para.outputs_subdir",
        "gateway.restart.auto_resume_b",
        "tracing.redaction.enabled",
    ),
    "subagents": (
        "subagents.enabled",
        "subagents.max_level1_default",
        "subagents.max_level2_default",
        "subagents.max_override",
        "subagents.timeout_s",
        "gateway.queue_mode",
    ),
    "logs": ("tracing.sinks",),
}


def _dot_path_from_toggle_pattern(pattern: str) -> str | None:
    """Extract a ``sevn.json`` dot path from a ``cfg:toggle:`` regex pattern.

    Args:
        pattern (str): ``MenuButtonSpec.callback_pattern``.

    Returns:
        str | None: Dot path when the pattern is a toggle row.

    Examples:
        >>> _dot_path_from_toggle_pattern(r"^cfg:toggle:gateway\\.queue_mode:.+$")
        'gateway.queue_mode'
    """
    marker = "cfg:toggle:"
    if marker not in pattern:
        return None
    rest = pattern.split(marker, 1)[1]
    escaped, _, _ = rest.partition(":")
    if not escaped:
        return None
    return escaped.replace(r"\.", ".")


def menu_registry_root_slugs() -> tuple[str, ...]:
    """Return ``/config`` root section slugs from ``menu_registry`` (live).

    Returns:
        tuple[str, ...]: Slugs in registry order.

    Examples:
        >>> slugs = menu_registry_root_slugs()
        >>> "session" in slugs and len(slugs) == 19
        True
    """
    slugs: list[str] = []
    for spec in MENU_BUTTON_SPECS:
        if spec.section != "root":
            continue
        match = _SECTION_CALLBACK_RE.match(spec.callback_pattern)
        if match:
            slugs.append(match.group(1))
    return tuple(slugs)


def _labels_by_slug() -> dict[str, str]:
    """Map ``/config`` root slugs to display labels from ``menu_registry``.

    Returns:
        dict[str, str]: Slug → label.

    Examples:
        >>> labels = _labels_by_slug()
        >>> labels.get("session") == "Session"
        True
    """
    labels: dict[str, str] = {}
    for spec in MENU_BUTTON_SPECS:
        if spec.section != "root":
            continue
        match = _SECTION_CALLBACK_RE.match(spec.callback_pattern)
        if match:
            labels[match.group(1)] = spec.label
    return labels


def _dot_paths_for_slug(slug: str) -> tuple[str, ...]:
    """Collect toggle dot-paths for a root section slug.

    Args:
        slug (str): Root section slug.

    Returns:
        tuple[str, ...]: Sorted unique dot paths.

    Examples:
        >>> "gateway.queue_mode" in _dot_paths_for_slug("session")
        True
    """
    menu_sections = _SLUG_MENU_SECTIONS.get(slug, (slug,))
    paths: set[str] = set(_EXTRA_DOT_PATHS.get(slug, ()))
    for spec in MENU_BUTTON_SPECS:
        if spec.section not in menu_sections:
            continue
        path = _dot_path_from_toggle_pattern(spec.callback_pattern)
        if path:
            paths.add(path)
    return tuple(sorted(paths))


def iter_config_sections() -> tuple[ConfigSection, ...]:
    """Yield canonical ``/config`` sections aligned with Telegram ``menu_registry``.

    Returns:
        tuple[ConfigSection, ...]: Ordered sections for CLI menus and ``sevn config <slug>``.

    Examples:
        >>> sections = iter_config_sections()
        >>> sections[0].slug == "session"
        True
    """
    labels = _labels_by_slug()
    sections: list[ConfigSection] = []
    for slug in menu_registry_root_slugs():
        sections.append(
            ConfigSection(
                slug=slug,
                label=labels.get(slug, slug.replace("_", " ").title()),
                callback=section_callback(slug),
                dot_paths=_dot_paths_for_slug(slug),
            )
        )
    return tuple(sections)


def section_by_slug(slug: str) -> ConfigSection | None:
    """Look up a config section by slug.

    Args:
        slug (str): Section slug (e.g. ``session``).

    Returns:
        ConfigSection | None: Matching section or None.

    Examples:
        >>> section_by_slug("session") is not None
        True
        >>> section_by_slug("missing") is None
        True
    """
    normalized = slug.strip().lower().replace("-", "_")
    for section in iter_config_sections():
        if section.slug == normalized:
            return section
    return None


def section_callback(slug: str) -> str:
    """Return the Telegram ``cfg:section:*`` callback for a slug.

    Args:
        slug (str): Section slug.

    Returns:
        str: Callback string.

    Examples:
        >>> section_callback("voice")
        'cfg:section:voice'
    """
    return f"cfg:section:{slug}"
