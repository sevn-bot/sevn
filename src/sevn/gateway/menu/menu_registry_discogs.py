"""Discogs menu button registry entries (TMF surface C7.8-C7.20).

Module: sevn.gateway.menu.menu_registry_discogs
Depends: sevn.gateway.menu.menu_registry

Exports:
    register_discogs_menu_entries — append Discogs control-surface specs to the registry.
"""

from __future__ import annotations

from collections.abc import Callable

from sevn.gateway.menu.menu_registry import _exact, _toggle


def register_discogs_menu_entries(
    add: Callable[..., None],
    *,
    implemented: bool = True,
    owner_only: bool = False,
) -> None:
    """Register Discogs submenu, toggles, setup wizards, and smoke-test actions.

    Args:
        add (Callable[..., None]): Registry ``add`` helper from :func:`_build_menu_button_specs`.
        implemented (bool, optional): Whether entries are wired in the gateway.
        owner_only (bool, optional): Default owner-only flag (unused; per-entry overrides).

    Returns:
        None

    Examples:
        >>> register_discogs_menu_entries.__name__
        'register_discogs_menu_entries'
    """
    _ = owner_only
    add(
        "C7.8",
        _exact("cfg:section:skills:discogs"),
        "C",
        "skills",
        "Discogs submenu",
        implemented=implemented,
        notes="Schema-gated when skills.discogs declared",
    )
    add(
        "C7.9",
        _exact("cfg:section:skills:discogs:setup"),
        "C",
        "skills:discogs",
        "Discogs Setup submenu",
        implemented=implemented,
        notes="User-token wizard and auth smoke-test",
    )
    add(
        "C7.10",
        _toggle("skills.discogs.enabled"),
        "C",
        "skills:discogs",
        "Discogs group enabled toggle",
        implemented=implemented,
        notes="Off by default; gates all five bundled skills",
    )
    add(
        "C7.11",
        _toggle("skills.discogs.database.enabled"),
        "C",
        "skills:discogs",
        "Discogs database skill toggle",
        implemented=implemented,
    )
    add(
        "C7.12",
        _toggle("skills.discogs.marketplace.enabled"),
        "C",
        "skills:discogs",
        "Discogs marketplace skill toggle",
        implemented=implemented,
    )
    add(
        "C7.13",
        _toggle("skills.discogs.collection.enabled"),
        "C",
        "skills:discogs",
        "Discogs collection skill toggle",
        implemented=implemented,
    )
    add(
        "C7.14",
        _toggle("skills.discogs.wantlist.enabled"),
        "C",
        "skills:discogs",
        "Discogs wantlist skill toggle",
        implemented=implemented,
    )
    add(
        "C7.15",
        _toggle("skills.discogs.identity.enabled"),
        "C",
        "skills:discogs",
        "Discogs identity skill toggle",
        implemented=implemented,
    )
    add(
        "C7.16",
        r"^cfg:cycle:skills\.discogs\.auth_method:(?:user_token|oauth)$",
        "C",
        "skills:discogs",
        "Discogs auth method cycle",
        implemented=implemented,
    )
    add(
        "C7.17",
        _toggle("skills.discogs.confirm_writes"),
        "C",
        "skills:discogs",
        "Discogs confirm_writes toggle",
        implemented=implemented,
    )
    add(
        "C7.18",
        _exact("form:secret_wizard:discogs.user_token"),
        "C",
        "skills:discogs:setup",
        "Set Discogs user token",
        implemented=implemented,
        owner_only=True,
        notes="Preset-alias wizard; sets auth_method user_token",
    )
    add(
        "C7.19",
        _exact("form:discogs:oauth_start"),
        "C",
        "skills:discogs:setup",
        "Discogs OAuth setup",
        implemented=implemented,
        owner_only=True,
        notes="OAuth 1.0a multi-step form",
    )
    add(
        "C7.20",
        _exact("act:discogs:whoami"),
        "C",
        "skills:discogs:setup",
        "Discogs auth smoke-test",
        implemented=implemented,
        owner_only=True,
        notes="Runs discogs-identity/whoami subprocess",
    )
