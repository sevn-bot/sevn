"""Live Mission Control tab snapshot for docs gates and the about-site build.

Module: scripts.mission_control_snapshot
Depends: dataclasses, sevn.ui.dashboard.tab_registry

Exports:
    LiveTab — one sidebar tab from the registry.
    LiveGroup — one dashboard group and its tabs.
    collect_live_mission_control — snapshot groups and tabs from code.

Examples:
    >>> menu = collect_live_mission_control()
    >>> "core" in menu
    True
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "LiveGroup",
    "LiveTab",
    "collect_live_mission_control",
]


@dataclass(frozen=True)
class LiveTab:
    """One Mission Control sidebar tab."""

    slug: str
    label: str
    kind: str


@dataclass(frozen=True)
class LiveGroup:
    """One sidebar group and its documented tabs."""

    group_id: str
    title: str
    tabs: tuple[LiveTab, ...]


def collect_live_mission_control() -> dict[str, LiveGroup]:
    """Snapshot Mission Control groups and tabs from :mod:`tab_registry`.

    Returns:
        dict[str, LiveGroup]: Group id → live group snapshot.

    Examples:
        >>> menu = collect_live_mission_control()
        >>> len(menu["core"].tabs) == 3
        True
    """
    from sevn.ui.dashboard.tab_registry import (
        DASHBOARD_GROUPS,
        POST_V1_PLACEHOLDER_SLUGS,
        WIRED_SLUGS,
        registry_tab_slug,
        tab_slug,
    )

    groups: dict[str, LiveGroup] = {}
    for group_name, tab_names in DASHBOARD_GROUPS:
        group_id = tab_slug(group_name)
        tabs: list[LiveTab] = []
        for name in tab_names:
            slug = registry_tab_slug(name)
            if slug in WIRED_SLUGS:
                kind = "wired"
            elif slug in POST_V1_PLACEHOLDER_SLUGS:
                kind = "post_v1"
            else:
                kind = "stub"
            tabs.append(LiveTab(slug=slug, label=name, kind=kind))
        groups[group_id] = LiveGroup(group_id=group_id, title=group_name, tabs=tuple(tabs))
    return groups
