"""Local gateway token bootstrap (no running gateway required).

Module: sevn.cli.gateway_token_store
Depends: asyncio, json, pathlib, sevn.cli.workspace, sevn.config.workspace_config,
    sevn.gateway.gateway_token, sevn.gateway.workspace_config_io

Exports:
    GatewayTokenBootstrap — raw-JSON view of the bound workspace for bootstrap.
    GatewayTokenStoreResult — outcome of a local gateway token write.
    load_bootstrap_workspace — read ``sevn.json`` raw (does not require a valid config).
    store_gateway_token_local — stamp ``gateway.token`` ref + write logical key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from sevn.cli.errors import CliPreconditionError
from sevn.cli.workspace import bound_sevn_json_path
from sevn.config.workspace_config import SecretsBackendSectionConfig
from sevn.gateway.gateway_token import (
    GATEWAY_TOKEN_CONFIG_REF,
    GATEWAY_TOKEN_LOGICAL_KEY,
    validate_gateway_token_plaintext,
)
from sevn.gateway.workspace_config_io import mutate_sevn_json, set_nested
from sevn.secrets.fingerprint import fingerprint_sha256_hex
from sevn.security.secrets.factory import secrets_chain_from_workspace

if TYPE_CHECKING:
    from sevn.security.secrets.chain import SecretsChain


@dataclass(frozen=True)
class GatewayTokenBootstrap:
    """Minimal raw-JSON view of the bound workspace for token bootstrap.

    Carries only what ``store_gateway_token_local`` needs so the command works on a
    legacy ``sevn.json`` that lacks ``gateway.token`` (the very workspace that must run
    it). Full ``WorkspaceConfig`` validation — which now requires the token — is bypassed.

    Attributes:
        sevn_json_path (Path): Path to the bound ``sevn.json``.
        content_root (Path): Workspace content root for secrets-chain path resolution.
        secrets_backend (SecretsBackendSectionConfig | None): Parsed ``secrets_backend``.
    """

    sevn_json_path: Path
    content_root: Path
    secrets_backend: SecretsBackendSectionConfig | None

    def chain(self) -> SecretsChain:
        """Build the secrets chain for this workspace.

        Returns:
            SecretsChain: Chain from ``secrets_backend`` and ``content_root``.

        Examples:
            >>> from pathlib import Path
            >>> b = GatewayTokenBootstrap(Path("s.json"), Path("."), None)
            >>> b.chain().__class__.__name__
            'SecretsChain'
        """
        return secrets_chain_from_workspace(self.content_root, self.secrets_backend)


def load_bootstrap_workspace() -> GatewayTokenBootstrap:
    """Read the bound ``sevn.json`` raw, without requiring a fully valid config.

    Only the file path, content root, and ``secrets_backend`` subtree are needed to
    store the gateway token. This deliberately avoids ``load_bound_workspace`` /
    ``parse_workspace_config`` so a legacy document missing ``gateway.token`` can still
    bootstrap (``specs/17-gateway.md`` §2.1).

    Returns:
        GatewayTokenBootstrap: Raw-JSON workspace view.

    Raises:
        CliPreconditionError: Missing/unreadable ``sevn.json`` or bad ``secrets_backend``.

    Examples:
        >>> load_bootstrap_workspace()  # doctest: +SKIP
    """
    path = bound_sevn_json_path()
    if not path.is_file():
        raise CliPreconditionError(
            f"workspace not bound: missing sevn.json at {path} "
            "(complete onboarding or set SEVN_HOME; the CLI does not search upward from cwd)",
            exit_code=4,
        )
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CliPreconditionError(
            f"cannot read sevn.json: {path} ({exc})",
            exit_code=4,
        ) from exc
    if not isinstance(raw, dict):
        raise CliPreconditionError("sevn.json must be a JSON object", exit_code=4)

    backend_section: SecretsBackendSectionConfig | None = None
    backend_raw = raw.get("secrets_backend")
    if backend_raw is not None:
        try:
            backend_section = SecretsBackendSectionConfig.model_validate(backend_raw)
        except ValidationError as exc:
            raise CliPreconditionError(
                f"invalid sevn.json secrets_backend: {exc}",
                exit_code=4,
            ) from exc

    cfg_path = path.expanduser().resolve()
    workspace_root = raw.get("workspace_root", ".")
    wr = Path(str(workspace_root)).expanduser()
    content_root = wr.resolve() if wr.is_absolute() else (cfg_path.parent / wr).resolve()
    return GatewayTokenBootstrap(
        sevn_json_path=cfg_path,
        content_root=content_root,
        secrets_backend=backend_section,
    )


@dataclass(frozen=True)
class GatewayTokenStoreResult:
    """Outcome of a local gateway token write.

    Attributes:
        fingerprint_sha256_hex (str): SHA-256 hex of stored plaintext.
        overwritten (bool): Whether a prior value existed.
        gateway_token_ref (str): Config ref written to ``gateway.token``.
    """

    fingerprint_sha256_hex: str
    overwritten: bool
    gateway_token_ref: str = GATEWAY_TOKEN_CONFIG_REF


async def _write_logical_key(
    chain: SecretsChain,
    *,
    plaintext: str,
    confirm_fingerprint: str | None,
) -> bool:
    """Write ``GATEWAY_TOKEN_LOGICAL_KEY`` when absent or fingerprint-confirmed.

    Args:
        chain (SecretsChain): Workspace secrets chain.
        plaintext (str): Validated bearer token.
        confirm_fingerprint (str | None): Required when overwriting a differing value.

    Returns:
        bool: ``True`` when a prior value existed (overwrite).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock
        >>> ch = AsyncMock()
        >>> ch.get = AsyncMock(return_value=None)
        >>> ch.set = AsyncMock()
        >>> asyncio.run(_write_logical_key(ch, plaintext="a" * 64, confirm_fingerprint=None))
        False
    """
    existing = await chain.get(GATEWAY_TOKEN_LOGICAL_KEY)
    if existing is not None:
        # Re-storing the identical value is a no-op overwrite; allow it without a
        # fingerprint so a retry after a partial run (M2) never demands an unseen value.
        if existing == plaintext:
            return True
        want = fingerprint_sha256_hex(existing)
        got = (confirm_fingerprint or "").strip().lower()
        if got != want:
            msg = (
                "overwrite blocked: pass --confirm-fingerprint matching the existing value "
                f"(expected {want})"
            )
            raise ValueError(msg)
    await chain.set(GATEWAY_TOKEN_LOGICAL_KEY, plaintext)
    return existing is not None


def store_gateway_token_local(
    bootstrap: GatewayTokenBootstrap,
    *,
    plaintext: str,
    confirm_fingerprint: str | None = None,
) -> GatewayTokenStoreResult:
    """Stamp ``gateway.token`` ref in ``sevn.json``, then write the bearer to the chain.

    The config ref is stamped first (M2): if the secret write then fails the document is
    still valid and the command is safe to re-run (no prior secret ⇒ no fingerprint
    needed). The reverse order would leave a stored secret the operator never saw,
    blocking the retry behind ``--confirm-fingerprint``.

    .. note::

        Uses ``asyncio.run`` for the secrets-chain write and therefore must not be called
        from within a running event loop (call it only at the synchronous CLI boundary).

    Args:
        bootstrap (GatewayTokenBootstrap): Raw-JSON workspace view.
        plaintext (str): Gateway bearer token (validated).
        confirm_fingerprint (str | None): Required when overwriting a differing logical key.

    Returns:
        GatewayTokenStoreResult: Store metadata.

    Raises:
        ValueError: On validation, overwrite guard, or secrets I/O failure.

    Examples:
        >>> from pathlib import Path
        >>> store_gateway_token_local(
        ...     GatewayTokenBootstrap(Path("s.json"), Path("."), None),
        ...     plaintext="a" * 64,
        ... )  # doctest: +SKIP
    """
    token = validate_gateway_token_plaintext(plaintext)

    def _stamp_gateway_token(doc: dict[str, object]) -> None:
        gw = doc.setdefault("gateway", {})
        if not isinstance(gw, dict):
            msg = "gateway section must be an object"
            raise ValueError(msg)
        set_nested(doc, "gateway.token", GATEWAY_TOKEN_CONFIG_REF)

    mutate_sevn_json(bootstrap.sevn_json_path, _stamp_gateway_token)

    from sevn.cli.asyncio_util import run_sync_coro
    from sevn.config.workspace_config import effective_encrypted_file_key_source
    from sevn.security.secrets.passphrase_prime import reconcile_unlock_env_with_keychain

    key_source = effective_encrypted_file_key_source(bootstrap.secrets_backend)
    run_sync_coro(reconcile_unlock_env_with_keychain(key_source=key_source))

    chain = bootstrap.chain()
    overwritten = run_sync_coro(
        _write_logical_key(chain, plaintext=token, confirm_fingerprint=confirm_fingerprint),
    )
    fp = fingerprint_sha256_hex(token)
    return GatewayTokenStoreResult(
        fingerprint_sha256_hex=fp,
        overwritten=overwritten,
    )


__all__ = [
    "GatewayTokenBootstrap",
    "GatewayTokenStoreResult",
    "load_bootstrap_workspace",
    "store_gateway_token_local",
]
