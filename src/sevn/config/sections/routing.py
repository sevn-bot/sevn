"""Named routing profiles for turn-scoped gateway isolation (#79 / W12, D14).

Module: sevn.config.sections.routing
Depends: pydantic

Exports:
    RoutingProfileEntryConfig — one named routing profile body.
    RoutingWorkspaceSectionConfig — ``routing.*`` workspace subtree.
    RoutingProfileConfigPaths — canonical dot paths for routing profile keys.
    routing_profile_config_paths — canonical dot paths (disambiguation from other "profile" keys).
    routing_profile_disambiguation_notes — maintainer doc listing four unrelated profile concepts.
    routing_section_dict — raw ``routing`` mapping from workspace config.

The ``routing.profiles`` map is **not** ``permissions.profiles``, ``deployment.profile``,
``onboarding.applied_profile``, or ``skills.browser.profile_dir`` — see
:func:`routing_profile_disambiguation_notes`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ROUTING_PROFILES_DOT_PATH = "routing.profiles"
ROUTING_CHANNEL_MAP_DOT_PATH = "routing.channel_map"


@dataclass(frozen=True)
class RoutingProfileConfigPaths:
    """Canonical ``sevn.json`` dot paths for routing-profile config."""

    profiles_dot_path: str
    channel_map_dot_path: str


def routing_profile_config_paths() -> RoutingProfileConfigPaths:
    """Return stable dot paths for the routing-profile namespace (D14).

    Returns:
        RoutingProfileConfigPaths: ``routing.profiles`` and ``routing.channel_map``.

    Examples:
        >>> paths = routing_profile_config_paths()
        >>> paths.profiles_dot_path
        'routing.profiles'
        >>> paths.channel_map_dot_path
        'routing.channel_map'
    """
    return RoutingProfileConfigPaths(
        profiles_dot_path=ROUTING_PROFILES_DOT_PATH,
        channel_map_dot_path=ROUTING_CHANNEL_MAP_DOT_PATH,
    )


def routing_profile_disambiguation_notes() -> str:
    """Document how ``routing.profiles`` differs from other ``*profile*`` keys (D14).

    Returns:
        str: Maintainer-facing disambiguation prose referencing four existing paths.

    Examples:
        >>> notes = routing_profile_disambiguation_notes()
        >>> "permissions.profiles" in notes
        True
    """
    return (
        "routing.profiles — named turn-routing profiles (model, prompt, skills, memory "
        "namespace, secrets scope, permissions_profile). Distinct from: "
        "onboarding.applied_profile (onboarding preset id), "
        "permissions.profiles (tool permission policy bodies), "
        "deployment.profile (host deployment label), "
        "skills.browser.profile_dir (Chrome user-data directory)."
    )


class RoutingProfileEntryConfig(BaseModel):
    """One entry under ``routing.profiles.<name>``."""

    model_config = ConfigDict(extra="ignore")

    model: str | None = None
    system_prompt: str | None = None
    skills: list[str] = Field(default_factory=list)
    memory_namespace: str = "default"
    secrets_scope: str | None = None
    permissions_profile: str | None = None
    reasoning_effort: str | None = None


class RoutingWorkspaceSectionConfig(BaseModel):
    """Workspace ``routing`` section for profile-based turn isolation."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    default_profile: str = "default"
    unknown_route: str = "default"
    profiles: dict[str, RoutingProfileEntryConfig] = Field(default_factory=dict)
    channel_map: dict[str, str] = Field(default_factory=dict)


def routing_section_dict(cfg: object) -> dict[str, Any]:
    """Return the workspace ``routing`` mapping when present.

    Args:
        cfg (object): Parsed workspace settings.

    Returns:
        dict[str, Any]: Routing section or empty dict.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> routing_section_dict(WorkspaceConfig.minimal())
        {}
    """
    raw = getattr(cfg, "routing", None)
    if raw is None:
        extra = getattr(cfg, "model_extra", None)
        if isinstance(extra, dict):
            block = extra.get("routing")
            if isinstance(block, dict):
                return block
        return {}
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        dumped = raw.model_dump(exclude_none=True)
        if isinstance(dumped, dict):
            return dumped
    return {}
