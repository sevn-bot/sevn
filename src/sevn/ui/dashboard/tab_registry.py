"""Mission Control sidebar tab registry (`specs/24-dashboard.md` §4.2, PRD §5.2).

Module: sevn.ui.dashboard.tab_registry
Depends: re

Exports:
    registry_tab_slug — canonical slug for a registry tab label.
    tab_slug — slugify a tab display name for path routes.
    build_nav_payload — JSON-serializable nav payload for SPA bootstrap.
"""

from __future__ import annotations

import re

# PRD §5.2 / `src/sevn/ui/spa/dashboard/app.js` — 45 tabs, 8 groups.
DASHBOARD_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Core", ("Overview", "Chat", "Canvas (OpenUI)", "Sessions")),
    (
        "Observability",
        (
            "Traces",
            "Audit & Analytics",
            "Providers & LLMs",
            "Budget & Cost",
            "Channels",
            "Alerts & Logs",
        ),
    ),
    (
        "Agent",
        (
            "Agent Config",
            "Model Params",
            "Tools & Permissions",
            "Skills",
            "MCP Servers",
            "Coding Agents",
        ),
    ),
    (
        "Knowledge",
        ("Memory", "Second Brain", "Workspace Files", "Code Understanding"),
    ),
    (
        "Self-improve",
        (
            "Jobs",
            "Trajectories",
            "Feedback",
            "RLM Config",
            "Experiments & Metrics",
        ),
    ),
    (
        "Evolution",
        (
            "Issues",
            "Pipelines",
            "Approvals",
            "Spec-Kit",
            "Evolution Traces",
            "Stats",
        ),
    ),
    (
        "Ops",
        (
            "Cron",
            "Security",
            "Secrets",
            "Egress proxy",
            "Tunnels & Infra",
            "Backup & Snapshots",
            "Config",
            "Schema & Ontology",
            "sevn CLI",
            "Terminal",
        ),
    ),
    (
        "Surfaces",
        ("Telegram Menu", "Web Apps", "Onboarding", "Users & RBAC"),
    ),
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Labels whose URL slug is intentionally not tab_slug(label) (Telegram deep-links, API paths).
TAB_SLUG_OVERRIDES: dict[str, str] = {
    "RLM Config": "rlm-training",
}


def tab_slug(name: str) -> str:
    """Slugify a tab display name for ``/mission/{slug}`` path routes.

    Args:
        name (str): Human-readable tab label from the registry.

    Returns:
        str: Lowercase hyphenated slug (matches SPA ``slug()``).

    Examples:
        >>> tab_slug("Providers & LLMs")
        'providers-llms'
        >>> tab_slug("Canvas (OpenUI)")
        'canvas-openui'
    """

    lowered = name.lower()
    slug = _SLUG_RE.sub("-", lowered)
    return slug.strip("-")


def registry_tab_slug(name: str) -> str:
    """Return the canonical Mission Control slug for a registry tab label.

    Args:
        name (str): Human-readable tab label from :data:`DASHBOARD_GROUPS`.

    Returns:
        str: Slug used in ``/mission/{slug}`` routes and :data:`WIRED_SLUGS`.

    Examples:
        >>> registry_tab_slug("RLM Config")
        'rlm-training'
        >>> registry_tab_slug("Providers & LLMs")
        'providers-llms'
    """

    return TAB_SLUG_OVERRIDES.get(name, tab_slug(name))


def _all_tab_slugs() -> frozenset[str]:
    """Collect slugs for every tab in :data:`DASHBOARD_GROUPS`.

    Returns:
        frozenset[str]: Unique tab slugs.

    Examples:
        >>> len(_all_tab_slugs())
        45
    """

    slugs: set[str] = set()
    for _group, names in DASHBOARD_GROUPS:
        for name in names:
            slugs.add(registry_tab_slug(name))
    return frozenset(slugs)


TAB_SLUGS: frozenset[str] = _all_tab_slugs()

WIRED_SLUGS: frozenset[str] = frozenset(
    {
        "overview",
        "chat",
        "canvas-openui",
        "sessions",
        "traces",
        "audit-analytics",
        "budget-cost",
        "providers-llms",
        "channels",
        "alerts-logs",
        "jobs",
        "issues",
        "pipelines",
        "approvals",
        "evolution-traces",
        "stats",
        "spec-kit",
        "cron",
        "security",
        "secrets",
        "egress-proxy",
        "tunnels-infra",
        "backup-snapshots",
        "config",
        "schema-ontology",
        "sevn-cli",
        "terminal",
        "memory",
        "second-brain",
        "workspace-files",
        "code-understanding",
        "agent-config",
        "model-params",
        "tools-permissions",
        "skills",
        "mcp-servers",
        "coding-agents",
        "trajectories",
        "feedback",
        "rlm-training",
        "experiments-metrics",
        "telegram-menu",
        "web-apps",
        "onboarding",
        "users-rbac",
    }
)

POST_V1_PLACEHOLDER_SLUGS: frozenset[str] = frozenset()


def build_nav_payload() -> dict[str, object]:
    """Build JSON payload for ``GET /api/v1/dashboard/nav``.

    Returns:
        dict[str, object]: Groups, tab entries, wired set, and post-v1 placeholders.

    Examples:
        >>> payload = build_nav_payload()
        >>> len(payload["groups"])
        8
        >>> payload["tab_count"]
        45
    """

    groups: list[dict[str, object]] = []
    tabs: list[dict[str, str]] = []
    for group_name, names in DASHBOARD_GROUPS:
        tab_entries: list[dict[str, str]] = []
        for name in names:
            slug = registry_tab_slug(name)
            kind = (
                "wired"
                if slug in WIRED_SLUGS
                else ("post_v1" if slug in POST_V1_PLACEHOLDER_SLUGS else "stub")
            )
            entry = {
                "name": name,
                "slug": slug,
                "path": f"/mission/{slug}",
                "kind": kind,
            }
            tab_entries.append(entry)
            tabs.append({"group": group_name, "name": name, "slug": slug, "path": entry["path"]})
        groups.append({"name": group_name, "tabs": tab_entries})

    return {
        "groups": groups,
        "tabs": tabs,
        "wired_slugs": sorted(WIRED_SLUGS),
        "post_v1_placeholder_slugs": sorted(POST_V1_PLACEHOLDER_SLUGS),
        "tab_count": len(tabs),
    }


__all__ = [
    "DASHBOARD_GROUPS",
    "POST_V1_PLACEHOLDER_SLUGS",
    "TAB_SLUGS",
    "TAB_SLUG_OVERRIDES",
    "WIRED_SLUGS",
    "build_nav_payload",
    "registry_tab_slug",
    "tab_slug",
]
