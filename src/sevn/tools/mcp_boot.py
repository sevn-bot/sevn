"""Gateway boot helpers for MCP OAuth credentials and profile policy (#90, W29).

Module: sevn.tools.mcp_boot
Depends: sevn.code_understanding.graphify_mcp, sevn.tools.mcp_oauth, sevn.tools.mcp_profile_policy

Exports:
    compute_mcp_registry_fingerprint — stable digest for session-registry cache keys.
    effective_mcp_servers_for_workspace — declared servers filtered by workspace/profile policy.
    load_mcp_oauth_credentials — load OAuth blobs from the secrets chain at boot.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sevn.code_understanding.graphify_mcp import build_effective_mcp_servers
from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.secrets.factory import secrets_chain_from_workspace
from sevn.tools.mcp_oauth import load_mcp_oauth_credential
from sevn.tools.mcp_profile_policy import resolve_mcp_servers_for_profile

if TYPE_CHECKING:
    from sevn.config.sections.secrets import SecretsBackendSectionConfig


def effective_mcp_servers_for_workspace(
    workspace: WorkspaceConfig,
    content_root: Path,
    *,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Return MCP server rows after workspace ``mcp_enabled`` and profile overlays.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        content_root (Path): Workspace content root for declared server merge.
        profile_id (str | None): Optional routing profile id (``None`` → workspace baseline).

    Returns:
        dict[str, Any]: Filtered server id → spec rows for discovery and runtime bindings.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> effective_mcp_servers_for_workspace(WorkspaceConfig.minimal(), root)
        {}
    """
    declared = build_effective_mcp_servers(workspace, content_root)
    return resolve_mcp_servers_for_profile(
        workspace,
        profile_id=profile_id,
        declared_servers=declared,
    )


async def load_mcp_oauth_credentials(
    content_root: Path,
    mcp_servers: Mapping[str, Mapping[str, Any]],
    *,
    secrets_backend: SecretsBackendSectionConfig | None = None,
) -> dict[str, dict[str, Any]]:
    """Load stored OAuth token blobs for declared MCP servers that declare ``oauth``.

    Args:
        content_root (Path): Workspace content root for secrets chain resolution.
        mcp_servers (Mapping[str, Mapping[str, Any]]): Effective MCP server map.
        secrets_backend (str | None): Workspace secrets backend id.

    Returns:
        dict[str, dict[str, Any]]: Server id → credential blob for subprocess env injection.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> import tempfile
        >>> asyncio.run(load_mcp_oauth_credentials(Path(tempfile.mkdtemp()), {}))
        {}
    """
    if not mcp_servers:
        return {}
    chain = secrets_chain_from_workspace(content_root, secrets_backend)
    loaded: dict[str, dict[str, Any]] = {}
    for server_id, spec in mcp_servers.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("oauth"), dict):
            continue
        blob = await load_mcp_oauth_credential(chain, server_id)
        if isinstance(blob, dict) and blob:
            loaded[server_id] = blob
    return loaded


def compute_mcp_registry_fingerprint(
    mcp_servers: Mapping[str, Mapping[str, Any]],
    oauth_credentials: Mapping[str, Mapping[str, Any]] | None,
    *,
    schema_version: int,
) -> str:
    """Build a stable digest for session-registry cache invalidation (W30.4 / #78).

    Args:
        mcp_servers (Mapping[str, Mapping[str, Any]]): Effective MCP server map.
        oauth_credentials (Mapping[str, Mapping[str, Any]] | None): Loaded OAuth blobs.
        schema_version (int): Workspace schema version fallback component.

    Returns:
        str: Hex digest suitable for :class:`~sevn.gateway.telemetry.ttft.SessionRegistryTurnCache`.

    Examples:
        >>> compute_mcp_registry_fingerprint({}, None, schema_version=1)[:8]
        'c775e7b7'
    """
    server_keys = ",".join(sorted(str(k) for k in mcp_servers))
    oauth_keys = ",".join(sorted(str(k) for k in (oauth_credentials or {})))
    payload = f"{schema_version}|{server_keys}|{oauth_keys}"
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "compute_mcp_registry_fingerprint",
    "effective_mcp_servers_for_workspace",
    "load_mcp_oauth_credentials",
]
