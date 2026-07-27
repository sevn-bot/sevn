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


# Menu-registry ``section`` field(s) whose ``cfg:toggle:*`` paths belong to a root slug (W6).
_SLUG_MENU_SECTIONS: dict[str, tuple[str, ...]] = {
    "chat": (
        "chat",
        "chat_qa",
        "chat_shortcuts",
        "chat_voice",
        "chat_channels",
        "chat_sessions",
        "session",
        "voice",
        "channels",
        "shortcuts",
        "notifications",
    ),
    "agent": (
        "agent",
        "agent_identity",
        "agent_sampling",
        "agent_subagents",
        "agent_subagents_running",
        "agent_lab",
        "agents",
        "models",
        "rlm",
        "codemode",
        "self_improve",
        "subagents",
        "subagents_running",
    ),
    "skills": (
        "skills",
        "skills:social_media_manager",
        "skills:discogs",
        "skills:discogs:setup",
        "skills_tools",
        "skills_integrations",
        "tools",
        "integrations",
    ),
    "memory": (
        "memory",
        "memory_sb",
        "memory_dreaming",
        "memory_code",
        "memory_openwiki",
        "code",
        "second_brain",
    ),
    "access": (
        "access",
        "access_secrets",
        "access_providers",
        "access_guard",
        "access_pairing",
        "secrets",
        "security",
    ),
    "health": (
        "health",
        "health_bundles",
        "health_tracing",
        "health_pin",
        "logs",
        "dashboard",
    ),
    "deployment": (
        "deployment",
        "deployment_services",
        "deployment_tunnel",
        "deployment_config",
        "deployment_update",
        "deployment_deploy",
        "deployment_host",
        "my_sevn_bot",
    ),
    "help": ("help", "help_guides", "help_dev", "sevn_bot"),
}

# Non-toggle schema keys surfaced in a section (forms / Mission Control parity).
_EXTRA_DOT_PATHS: dict[str, tuple[str, ...]] = {
    "chat": (
        "gateway.queue_mode",
        "channels.telegram.reply_keyboard.enabled",
        "channels.telegram.show_routing",
        "channels.telegram.telegram_notify_policy",
        "channels.telegram.quick_actions.show_regen",
        "channels.telegram.quick_actions.show_thumbs_up",
        "channels.telegram.quick_actions.show_thumbs_down",
        "channels.telegram.quick_actions.show_share",
        "channels.telegram.quick_actions.show_feedback",
        "channels.telegram.tts_mode",
    ),
    "agent": (
        "agent.display_name",
        "agent.triager.model",
        "agent.tier_b.model",
        "agent.tier_cd.model",
        "agent.unified_model.enabled",
        "providers.use_main_model_for_all",
        "subagents.enabled",
        "agent.codemode.enabled",
        "self_improve.enabled",
        "executors.tier_cd.lambda_rlm.enabled",
    ),
    "skills": (),
    "memory": (
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
        "code_understanding.mycode.enabled",
        "code_understanding.code_review_graph.enabled",
    ),
    "access": (
        "security.scanner.heuristic_only",
        "channels.telegram.owner_scanner_overrides.disable_text",
        "channels.telegram.owner_scanner_overrides.disable_links",
        "channels.telegram.owner_scanner_overrides.disable_documents",
    ),
    "health": (
        "tracing.sinks",
        "tracing.redaction.enabled",
        "channels.telegram.pinned_status",
    ),
    "deployment": ("gateway.restart.auto_resume_b",),
    "help": (),
    "health_tracing": ("tracing.redaction.enabled",),
}

# Retired CLI slugs → redesign root slugs (parity with ``menu._SECTION_ALIASES``).
_CLI_SLUG_ALIASES: dict[str, str] = {
    "session": "chat",
    "voice": "chat",
    "channels": "chat",
    "shortcuts": "chat",
    "notifications": "chat",
    "agents": "agent",
    "models": "agent",
    "rlm": "agent",
    "codemode": "agent",
    "self_improve": "agent",
    "subagents": "agent",
    "tools": "skills",
    "integrations": "skills",
    "code": "memory",
    "second_brain": "memory",
    "secrets": "access",
    "security": "access",
    "logs": "health",
    "dashboard": "health",
    "my_sevn_bot": "deployment",
    "sevn_bot": "help",
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
        >>> "chat" in slugs and len(slugs) == 8
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
        >>> labels.get("chat") == "Chat"
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
        >>> "gateway.queue_mode" in _dot_paths_for_slug("chat")
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
        >>> sections[0].slug == "chat"
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
        slug (str): Section slug (e.g. ``chat``).

    Returns:
        ConfigSection | None: Matching section or None.

    Examples:
        >>> section_by_slug("chat") is not None
        True
        >>> section_by_slug("missing") is None
        True
    """
    normalized = slug.strip().lower().replace("-", "_")
    canonical = _CLI_SLUG_ALIASES.get(normalized, normalized)
    for section in iter_config_sections():
        if section.slug == canonical:
            return section
    return None


def section_callback(slug: str) -> str:
    """Return the Telegram ``cfg:section:*`` callback for a slug.

    Args:
        slug (str): Section slug.

    Returns:
        str: Callback string.

    Examples:
        >>> section_callback("chat")
        'cfg:section:chat'
    """
    return f"cfg:section:{slug}"
