"""Resolve MCP profile servers and ``${SECRET:…}`` refs for Cursor cloud agents.

Module: sevn.proxy.integration.mcp_expand
Depends: sevn.proxy.secrets_resolve, sevn.security.secrets.cache

Exports:
    merge_mcp_profile_into_args — apply named profile + secret expansion.
    deep_expand_secret_refs — walk JSON-like trees and expand secret refs.
"""

from __future__ import annotations

import copy
from typing import Any

from sevn.proxy.secrets_resolve import expand_secret_refs
from sevn.security.secrets.cache import ResolvedSecretsCache


async def deep_expand_secret_refs(value: Any, cache: ResolvedSecretsCache | None) -> Any:
    """Recursively expand ``${SECRET:…}`` in strings inside mappings and lists.

    Args:
        value (Any): JSON-like structure.
        cache (ResolvedSecretsCache | None): Secrets cache; ``None`` skips expansion.

    Returns:
        Any: Structure with expanded strings.

    Examples:
        >>> import asyncio
        >>> asyncio.run(deep_expand_secret_refs("plain", None))
        'plain'
    """
    if cache is None:
        return value
    if isinstance(value, str):
        if "${SECRET:" not in value:
            return value
        return await expand_secret_refs(value, cache)
    if isinstance(value, dict):
        return {k: await deep_expand_secret_refs(v, cache) for k, v in value.items()}
    if isinstance(value, list):
        return [await deep_expand_secret_refs(item, cache) for item in value]
    return value


def _cursor_cloud_block(skills: dict[str, Any] | None) -> dict[str, Any]:
    """Return the ``cursor_cloud`` skills subtree when present.

    Args:
        skills (dict[str, Any] | None): Workspace ``skills`` config blob.

    Returns:
        dict[str, Any]: ``cursor_cloud`` block or empty dict.

    Examples:
        >>> _cursor_cloud_block({"cursor_cloud": {"mcp_profiles": {}}})
        {'mcp_profiles': {}}
    """
    if not isinstance(skills, dict):
        return {}
    block = skills.get("cursor_cloud")
    return block if isinstance(block, dict) else {}


async def merge_mcp_profile_into_args(
    args: dict[str, Any],
    *,
    skills: dict[str, Any] | None,
    cache: ResolvedSecretsCache | None,
) -> dict[str, Any]:
    """Merge ``mcp_profile`` servers into ``mcpServers`` and expand secret refs.

    Args:
        args (dict[str, Any]): Integration args (mutated copy returned).
        skills (dict[str, Any] | None): Workspace ``skills`` config.
        cache (ResolvedSecretsCache | None): Proxy secrets cache.

    Returns:
        dict[str, Any]: Args ready for Cursor ``POST /v1/agents`` (no ``mcp_profile`` key).

    Examples:
        >>> import asyncio
        >>> out = asyncio.run(
        ...     merge_mcp_profile_into_args({"mcp_profile": "missing"}, skills={}, cache=None),
        ... )
        >>> "mcp_profile" not in out
        True
    """
    body = copy.deepcopy(dict(args))
    profile_name = body.pop("mcp_profile", None)
    if isinstance(profile_name, str) and profile_name.strip():
        block = _cursor_cloud_block(skills)
        profiles = block.get("mcp_profiles")
        if isinstance(profiles, dict):
            entry = profiles.get(profile_name.strip())
            if isinstance(entry, dict):
                servers = entry.get("servers")
                if isinstance(servers, list):
                    existing = body.get("mcpServers")
                    merged: list[Any] = list(existing) if isinstance(existing, list) else []
                    merged.extend(servers)
                    body["mcpServers"] = merged
    if "mcpServers" in body:
        body["mcpServers"] = await deep_expand_secret_refs(body["mcpServers"], cache)
    return body
