"""Resolve webhook signing material (`specs/30-non-interactive-triggers.md` §2.3, `specs/06`).

Module: sevn.triggers.webhook_secret
Depends: base64, pathlib

Exports:
    resolve_webhook_signing_secret — load ``triggers.webhooks.<source>`` signing bytes.

Examples:
    >>> from sevn.triggers.webhook_secret import resolve_webhook_signing_secret
    >>> resolve_webhook_signing_secret.__name__
    'resolve_webhook_signing_secret'
"""

from __future__ import annotations

import base64
from pathlib import Path

from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.secrets.factory import secrets_chain_from_workspace


async def resolve_webhook_signing_secret(
    workspace: WorkspaceConfig,
    *,
    source: str,
    content_root: Path,
) -> bytes:
    """Return raw signing bytes for ``triggers.webhooks.<source>``.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json``.
        source (str): Webhook source id (e.g. ``github``).
        content_root (Path): Workspace content root for secret chain paths.

    Returns:
        bytes: MAC key material.

    Raises:
        ValueError: When the secret is missing or alias resolution fails.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import TriggersWorkspaceConfig, WorkspaceConfig
        >>> from sevn.triggers.webhook_secret import resolve_webhook_signing_secret
        >>> import base64
        >>> ws = WorkspaceConfig.minimal(
        ...     triggers=TriggersWorkspaceConfig(
        ...         webhooks={"github": {"secret_b64": base64.b64encode(b"k").decode()}},
        ...     ),
        ... )
        >>> asyncio.run(resolve_webhook_signing_secret(ws, source="github", content_root=Path("/tmp")))
        b'k'
    """

    tw = workspace.triggers
    if tw is None or not tw.webhooks:
        msg = "triggers.webhooks not configured"
        raise ValueError(msg)
    section = tw.webhooks.get(source)
    if not isinstance(section, dict):
        msg = f"triggers.webhooks.{source} must be an object"
        raise ValueError(msg)
    b64 = section.get("secret_b64")
    if isinstance(b64, str) and b64.strip():
        return base64.b64decode(b64.strip())
    ref = section.get("secret_alias") or section.get("secret_ref")
    if isinstance(ref, str) and ref.strip():
        chain = secrets_chain_from_workspace(content_root, workspace.secrets_backend)
        val = await chain.get(ref.strip())
        if not val:
            msg = f"secret alias {ref!r} not found"
            raise ValueError(msg)
        return val.encode("utf-8")
    msg = "webhook secret missing (secret_b64 or secret_alias)"
    raise ValueError(msg)
