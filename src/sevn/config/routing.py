"""Resolve named routing profiles for gateway turns (#79 / W12, D14).

Module: sevn.config.routing
Depends: sevn.config.sections.routing, sevn.tools.permissions

Exports:
    RoutingProfileDenied — unknown route when ``unknown_route`` is ``deny``.
    RoutingProfileBundle — resolved profile overrides for one turn.
    routing_profiles_active — whether routing config is enabled for the gateway.
    routing_channel_map_key — stable lookup key for ``routing.channel_map``.
    resolve_routing_profile_for_turn — profile name for channel + scope.
    resolve_routing_profile_bundle — model/prompt/skills/memory/permissions bundle.
    permission_policy_for_permissions_profile — map ``permissions.profiles`` entry.
    routing_profile_personality_root — namespace-scoped persona directory.
    prefix_secrets_logical_key — apply ``secrets_scope`` prefix for secret lookups.
    filter_tool_set_skills — restrict skill inventory to a profile allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — used at runtime for persona root resolution
from typing import Any

from sevn.config.defaults import DEFAULT_ROUTING_PROFILES_ENABLED
from sevn.config.sections.routing import (
    RoutingProfileEntryConfig,
    RoutingWorkspaceSectionConfig,
    routing_section_dict,
)
from sevn.tools.permissions import (
    AllowAllPermissionPolicy,
    AttributeBasedPermissionPolicy,
    DenyingPermissionPolicy,
    PermissionPolicy,
    resolve_principal,
)


class RoutingProfileDenied(RuntimeError):
    """Raised when ``routing.unknown_route`` is ``deny`` and no map entry matches."""


@dataclass(frozen=True)
class RoutingProfileBundle:
    """Resolved routing-profile overrides for one turn."""

    profile_name: str
    model: str | None
    system_prompt: str | None
    skill_allowlist: frozenset[str] | None
    memory_namespace: str
    secrets_scope: str | None
    permissions_profile: str | None
    permission_policy: PermissionPolicy
    reasoning_effort: str | None


def _routing_section(cfg: object) -> RoutingWorkspaceSectionConfig | None:
    """Parse ``routing`` workspace section when present.

    Args:
        cfg (object): Parsed workspace settings.

    Returns:
        RoutingWorkspaceSectionConfig | None: Coerced section or ``None``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _routing_section(WorkspaceConfig.minimal()) is None
        True
    """
    raw = routing_section_dict(cfg)
    if not raw:
        return None
    return RoutingWorkspaceSectionConfig.model_validate(raw)


def routing_profiles_active(cfg: object) -> bool:
    """Return whether routing profiles apply on the gateway turn spine (**D9**).

    Absent ``routing`` section ⇒ inactive. When the section exists, ``enabled`` defaults
    to :data:`DEFAULT_ROUTING_PROFILES_ENABLED` (``False``) unless explicitly true.

    Args:
        cfg (object): Parsed workspace settings.

    Returns:
        bool: ``True`` only when routing is explicitly enabled with profiles configured.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> routing_profiles_active(WorkspaceConfig.minimal())
        False
    """
    section = _routing_section(cfg)
    if section is None or not section.profiles:
        return False
    if section.enabled is True:
        return True
    if section.enabled is False:
        return False
    return DEFAULT_ROUTING_PROFILES_ENABLED


def routing_channel_map_key(*, channel: str, scope_key: str | None) -> str:
    """Build the ``routing.channel_map`` lookup key for one inbound route.

    Args:
        channel (str): Active channel adapter name.
        scope_key (str | None): Session scope override or default scope key.

    Returns:
        str: ``"{channel}:{scope_key}"`` when scope is set, else ``channel`` alone.

    Examples:
        >>> routing_channel_map_key(channel="telegram", scope_key="forum:1:42")
        'telegram:forum:1:42'
        >>> routing_channel_map_key(channel="webhook", scope_key="ingress-a")
        'webhook:ingress-a'
    """
    ch = channel.strip()
    scope = scope_key.strip() if isinstance(scope_key, str) else ""
    if scope:
        if scope.startswith(f"{ch}:"):
            return scope
        return f"{ch}:{scope}"
    return ch


def resolve_routing_profile_for_turn(
    cfg: object,
    *,
    channel: str,
    scope_key: str | None,
) -> str:
    """Resolve the routing profile name for one inbound route.

    Args:
        cfg (object): Parsed workspace settings.
        channel (str): Active channel adapter name.
        scope_key (str | None): Session scope key.

    Returns:
        str: Profile name from ``routing.channel_map`` or ``routing.default_profile``.

    Raises:
        RoutingProfileDenied: When the route is unknown and ``unknown_route`` is ``deny``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> doc = {
        ...     "schema_version": 1,
        ...     "routing": {
        ...         "default_profile": "safe",
        ...         "profiles": {"safe": {}, "ops": {}},
        ...         "channel_map": {"webhook:ingress-a": "ops"},
        ...     },
        ... }
        >>> cfg = WorkspaceConfig.model_validate(doc)
        >>> resolve_routing_profile_for_turn(cfg, channel="webhook", scope_key="ingress-a")
        'ops'
    """
    section = _routing_section(cfg)
    if section is None:
        msg = "routing section missing"
        raise RoutingProfileDenied(msg)
    route_key = routing_channel_map_key(channel=channel, scope_key=scope_key)
    channel_map = section.channel_map
    if route_key in channel_map:
        return channel_map[route_key].strip()
    if channel.strip() in channel_map:
        return channel_map[channel.strip()].strip()
    mode = (section.unknown_route or "default").strip().lower()
    if mode == "deny":
        msg = f"unknown route {route_key!r} — routing.unknown_route is deny"
        raise RoutingProfileDenied(msg)
    return section.default_profile.strip() or "default"


def permission_policy_for_permissions_profile(
    cfg: object,
    profile_key: str | None,
    *,
    channel: str = "",
    user_id: str = "",
) -> PermissionPolicy:
    """Resolve ``permissions.profiles.<key>`` into a :class:`PermissionPolicy`.

    Args:
        cfg (object): Parsed workspace settings.
        profile_key (str | None): Named permissions profile from routing config.
        channel (str): Session channel for ABAC principal resolution.
        user_id (str): Session user id for ABAC principal resolution.

    Returns:
        PermissionPolicy: Deny-list, deny-all, ABAC, or permissive default.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     permissions={
        ...         "profiles": {"p": {"deny_tools": ["terminal_run"]}},
        ...     },
        ... )
        >>> permission_policy_for_permissions_profile(cfg, "p").may_invoke("terminal_run")
        False
    """
    if not profile_key or not str(profile_key).strip():
        return AllowAllPermissionPolicy()
    raw = getattr(cfg, "permissions", None)
    if not isinstance(raw, dict):
        return AllowAllPermissionPolicy()
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict):
        return AllowAllPermissionPolicy()
    body = profiles.get(profile_key.strip())
    if not isinstance(body, dict):
        return AllowAllPermissionPolicy()
    deny_raw = body.get("deny_tools")
    if isinstance(deny_raw, list):
        denied = frozenset(str(x).strip() for x in deny_raw if str(x).strip())

        class _DenyListed:
            def may_invoke(self, tool_name: str) -> bool:
                return tool_name not in denied

        return _DenyListed()
    mode = str(body.get("mode", "")).strip().lower()
    if mode == "deny_all":
        return DenyingPermissionPolicy()
    if mode == "abac":
        owner_ids: frozenset[str] = frozenset()
        channels = getattr(cfg, "channels", None)
        if channels is not None and channels.telegram is not None:
            allowed = channels.telegram.allowed_users or []
            owner_ids = frozenset(str(int(uid)) for uid in allowed)
        principal = resolve_principal(
            channel=channel,
            user_id=user_id,
            owner_user_ids=owner_ids,
        )
        return AttributeBasedPermissionPolicy(principal)
    return AllowAllPermissionPolicy()


def _profile_entry(
    section: RoutingWorkspaceSectionConfig, profile_name: str
) -> RoutingProfileEntryConfig:
    """Return one profile entry from a parsed routing section.

    Args:
        section (RoutingWorkspaceSectionConfig): Parsed routing config.
        profile_name (str): Profile key under ``routing.profiles``.

    Returns:
        RoutingProfileEntryConfig: Entry body or empty defaults when missing.

    Examples:
        >>> section = RoutingWorkspaceSectionConfig(profiles={"p": {"model": "openai/gpt-4o"}})
        >>> _profile_entry(section, "p").model
        'openai/gpt-4o'
    """
    raw = section.profiles.get(profile_name)
    if raw is None:
        return RoutingProfileEntryConfig()
    if isinstance(raw, RoutingProfileEntryConfig):
        return raw
    if isinstance(raw, dict):
        return RoutingProfileEntryConfig.model_validate(raw)
    return RoutingProfileEntryConfig()


def resolve_routing_profile_bundle(
    cfg: object,
    *,
    profile_name: str,
    channel: str = "",
    user_id: str = "",
) -> RoutingProfileBundle:
    """Resolve one named routing profile into turn-scoped overrides.

    Args:
        cfg (object): Parsed workspace settings.
        profile_name (str): Key under ``routing.profiles``.
        channel (str): Active channel for permissions ABAC resolution.
        user_id (str): Session user id for permissions ABAC resolution.

    Returns:
        RoutingProfileBundle: Model/prompt/skills/memory/permissions overrides.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> doc = {
        ...     "schema_version": 1,
        ...     "routing": {
        ...         "profiles": {
        ...             "research": {
        ...                 "memory_namespace": "research",
        ...                 "skills": ["web-search"],
        ...                 "permissions_profile": "research_perms",
        ...             },
        ...         },
        ...     },
        ...     "permissions": {
        ...         "profiles": {"research_perms": {"deny_tools": ["terminal_run"]}},
        ...     },
        ... }
        >>> cfg = WorkspaceConfig.model_validate(doc)
        >>> bundle = resolve_routing_profile_bundle(cfg, profile_name="research")
        >>> bundle.memory_namespace
        'research'
    """
    section = _routing_section(cfg)
    entry = (
        _profile_entry(section, profile_name)
        if section is not None
        else RoutingProfileEntryConfig()
    )
    skills = entry.skills or []
    skill_allowlist = frozenset(str(s).strip() for s in skills if str(s).strip()) or None
    perms_key = (
        entry.permissions_profile.strip() if isinstance(entry.permissions_profile, str) else None
    )
    policy = permission_policy_for_permissions_profile(
        cfg,
        perms_key,
        channel=channel,
        user_id=user_id,
    )
    model = entry.model.strip() if isinstance(entry.model, str) and entry.model.strip() else None
    prompt = (
        entry.system_prompt.strip()
        if isinstance(entry.system_prompt, str) and entry.system_prompt.strip()
        else None
    )
    effort = (
        entry.reasoning_effort.strip()
        if isinstance(entry.reasoning_effort, str) and entry.reasoning_effort.strip()
        else None
    )
    namespace = entry.memory_namespace.strip() if entry.memory_namespace.strip() else "default"
    secrets_scope = (
        entry.secrets_scope.strip()
        if isinstance(entry.secrets_scope, str) and entry.secrets_scope.strip()
        else None
    )
    return RoutingProfileBundle(
        profile_name=profile_name,
        model=model,
        system_prompt=prompt,
        skill_allowlist=skill_allowlist,
        memory_namespace=namespace,
        secrets_scope=secrets_scope,
        permissions_profile=perms_key,
        permission_policy=policy,
        reasoning_effort=effort,
    )


def routing_profile_personality_root(content_root: Path, memory_namespace: str) -> Path:
    """Return the persona/memory root for a routing profile namespace.

    Default namespace reads from ``content_root``; others use
    ``<content_root>/.sevn/routing-profiles/<namespace>/``.

    Args:
        content_root (Path): Workspace content root.
        memory_namespace (str): Profile ``memory_namespace`` value.

    Returns:
        Path: Directory containing ``SOUL.md`` / ``USER.md`` for the profile.

    Examples:
        >>> from pathlib import Path
        >>> routing_profile_personality_root(Path("/w"), "default") == Path("/w")
        True
        >>> routing_profile_personality_root(Path("/w"), "research")
        PosixPath('/w/.sevn/routing-profiles/research')
    """
    ns = memory_namespace.strip() if memory_namespace.strip() else "default"
    if ns in ("default", "."):
        return content_root
    return content_root / ".sevn" / "routing-profiles" / ns


def prefix_secrets_logical_key(secrets_scope: str | None, logical_key: str) -> str:
    """Prefix a secret logical key with a routing profile ``secrets_scope``.

    Args:
        secrets_scope (str | None): Profile scope label; absent ⇒ unchanged key.
        logical_key (str): Backend logical key from ``${SECRET:source:key}``.

    Returns:
        str: Scoped key ``"{scope}/{logical_key}"`` when scope is set.

    Examples:
        >>> prefix_secrets_logical_key("research", "api.token")
        'research/api.token'
        >>> prefix_secrets_logical_key(None, "api.token")
        'api.token'
    """
    key = logical_key.strip()
    scope = secrets_scope.strip() if isinstance(secrets_scope, str) else ""
    if not scope:
        return key
    return f"{scope}/{key}"


def filter_tool_set_skills(tool_set: Any, skill_allowlist: frozenset[str] | None) -> Any:
    """Return a ``ToolSet`` copy with skills restricted to *skill_allowlist*.

    Args:
        tool_set (Any): Session ``ToolSet`` from ``build_session_registry``.
        skill_allowlist (frozenset[str] | None): Allowed skill ids; ``None`` keeps all.

    Returns:
        Any: Same ``ToolSet`` instance when unrestricted, else a filtered copy.

    Examples:
        >>> filter_tool_set_skills(None, None) is None
        True
    """
    if tool_set is None or skill_allowlist is None:
        return tool_set
    from sevn.tools.registry import ToolSet

    if not isinstance(tool_set, ToolSet):
        return tool_set
    skill_desc = {
        name: summary
        for name, summary in tool_set.skill_descriptions.items()
        if name in skill_allowlist
    }
    skill_inv = {
        name: payload
        for name, payload in tool_set.skill_inventory.items()
        if name in skill_allowlist
    }
    return ToolSet(
        tool_set.registry_version,
        tool_set.native,
        tool_set.mcp,
        skill_desc,
        skill_inventory=skill_inv,
    )
