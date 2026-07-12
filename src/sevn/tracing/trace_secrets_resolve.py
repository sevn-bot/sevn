"""Resolve trace sink ``token_ref`` via env + secrets chain (``specs/04-tracing.md``, D11).

Module: sevn.tracing.trace_secrets_resolve
Depends: pathlib, re, sevn.config.workspace_config, sevn.security.secrets.{cache,factory,value_expand}

Exports:
    resolve_trace_sink_token — expand ``token_ref`` (${ENV}, ${SECRET}) to bearer text.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import SecretsChain, get_secret_resilient
from sevn.security.secrets.errors import SecretUnresolvedError
from sevn.security.secrets.factory import secrets_chain_from_workspace
from sevn.security.secrets.value_expand import (
    EnvUnresolvedError,
    expand_env_refs,
    expand_refs_env_then_secret,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.config.workspace_config import WorkspaceConfig

_ENV_REF_RE = re.compile(r"^\$\{ENV:([^}]+)\}$")


async def _resolve_env_ref_from_chain(
    chain: SecretsChain,
    ref_raw: str,
) -> str | None:
    """Resolve ``${ENV:LOGICAL_KEY}`` via the secrets chain when process env is unset.

    Args:
        chain (SecretsChain): Workspace secrets chain.
        ref_raw (str): Raw ``token_ref`` value from ``sevn.json``.

    Returns:
        str | None: Token text when the logical key resolves to a non-empty value.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.security.secrets.factory import secrets_chain_from_workspace
        >>> chain = secrets_chain_from_workspace(Path("/tmp"), None)
        >>> asyncio.run(_resolve_env_ref_from_chain(chain, "${ENV:MISSING}")) is None
        True
    """
    match = _ENV_REF_RE.match(ref_raw.strip())
    if match is None:
        return None
    logical_key = match.group(1).strip()
    if not logical_key:
        return None
    value = await get_secret_resilient(chain, logical_key)
    if not value:
        return None
    text = value.strip()
    return text or None


async def resolve_trace_sink_token(
    token_ref: str | None,
    *,
    content_root: Path,
    workspace: WorkspaceConfig,
) -> str | None:
    """Return the OTLP bearer token for one ``tracing.sinks[]`` ``token_ref``.

    Applies ``expand_env_refs(..., strict=False)`` then, when ``${SECRET:…}`` spans remain,
    iterated env-then-secret expansion against the workspace secrets chain. A fully expanded
    value with no remaining ``${…}`` placeholders is the token; otherwise a bare value is
    treated as a logical key via ``get_secret_resilient``.

    Args:
        token_ref (str | None): Sink ``token_ref`` from config.
        content_root (Path): Workspace content root for encrypted-file backends.
        workspace (WorkspaceConfig): Parsed ``sevn.json``.

    Returns:
        str | None: Bearer token text when resolved; ``None`` when unset or unresolved.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> asyncio.run(
        ...     resolve_trace_sink_token(None, content_root=Path("."), workspace=WorkspaceConfig.minimal()),
        ... ) is None
        True
    """
    ref_raw = (token_ref or "").strip()
    if not ref_raw:
        return None

    chain = secrets_chain_from_workspace(content_root, workspace.secrets_backend)
    if "${" not in ref_raw:
        value = await get_secret_resilient(chain, ref_raw)
        if not value:
            return None
        text = value.strip()
        return text or None

    interim = expand_env_refs(ref_raw, strict=False)
    if "${ENV:" in interim:
        from_chain = await _resolve_env_ref_from_chain(chain, ref_raw)
        if from_chain:
            return from_chain
        return None

    interim_s = interim.strip()
    expanded = interim_s
    if "${SECRET:" in interim_s:
        cache = ResolvedSecretsCache(chain, ttl_seconds=0)
        try:
            expanded = await expand_refs_env_then_secret(interim_s, cache)
        except (EnvUnresolvedError, SecretUnresolvedError, ValueError):
            return None

    expanded = expanded.strip()
    if "${SECRET:" in expanded or "${ENV:" in expanded:
        return None

    if expanded and "${" not in expanded:
        return expanded

    return await get_secret_resilient(chain, expanded)
