"""Local tunnel setup writes (no running gateway required).

Module: sevn.cli.tunnel_setup_store
Depends: dataclasses, typing, sevn.cli.gateway_token_store, sevn.gateway.workspace_config_io,
    sevn.secrets.fingerprint, sevn.security.secrets.*

Exports:
    TunnelSetupResult — outcome of a local tunnel setup write.
    apply_tunnel_setup_local — stamp ``infrastructure.tunnel`` fields + optional secret.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sevn.cli.gateway_token_store import GatewayTokenBootstrap
from sevn.gateway.workspace_config_io import del_nested, mutate_sevn_json, set_nested
from sevn.secrets.fingerprint import fingerprint_sha256_hex

if TYPE_CHECKING:
    from sevn.security.secrets.chain import SecretsChain


@dataclass(frozen=True)
class TunnelSetupResult:
    """Outcome of a local tunnel setup write.

    Attributes:
        fingerprint_sha256_hex (str | None): SHA-256 hex of the stored secret, if any.
        overwritten (bool): Whether a prior secret value existed.
        secret_ref (str | None): Config ref stamped for the secret, if any.
    """

    fingerprint_sha256_hex: str | None
    overwritten: bool
    secret_ref: str | None


async def _write_secret_key(
    chain: SecretsChain,
    *,
    logical_key: str,
    plaintext: str,
    confirm_fingerprint: str | None,
) -> bool:
    """Write ``logical_key`` when absent or fingerprint-confirmed on overwrite.

    Args:
        chain (SecretsChain): Workspace secrets chain.
        logical_key (str): Secrets-chain logical id to write.
        plaintext (str): Secret value to store.
        confirm_fingerprint (str | None): Required when overwriting a differing value.

    Returns:
        bool: ``True`` when a prior value existed (overwrite).

    Raises:
        ValueError: When overwriting a differing value without a matching fingerprint.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock
        >>> ch = AsyncMock()
        >>> ch.get = AsyncMock(return_value=None)
        >>> ch.set = AsyncMock()
        >>> asyncio.run(
        ...     _write_secret_key(ch, logical_key="k", plaintext="v", confirm_fingerprint=None)
        ... )
        False
    """
    existing = await chain.get(logical_key)
    if existing is not None:
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
    await chain.set(logical_key, plaintext)
    return existing is not None


def apply_tunnel_setup_local(
    bootstrap: GatewayTokenBootstrap,
    *,
    config_fields: dict[str, Any],
    clear_fields: list[str] | None = None,
    secret_logical_key: str | None = None,
    secret_config_ref_path: str | None = None,
    secret_config_ref_value: str | None = None,
    secret_plaintext: str | None = None,
    confirm_fingerprint: str | None = None,
) -> TunnelSetupResult:
    """Stamp ``infrastructure.tunnel`` fields in ``sevn.json`` and store any secret.

    The config document is stamped first (including the ``${SECRET:…}`` ref when a
    secret is supplied); the plaintext is then written to the secrets chain. On a
    partial failure the document remains valid and the command is safe to re-run.

    .. note::

        Uses ``asyncio.run`` for the secrets-chain write and therefore must not be
        called from within a running event loop (call it only at the synchronous CLI
        boundary).

    Args:
        bootstrap (GatewayTokenBootstrap): Raw-JSON workspace view.
        config_fields (dict[str, Any]): Dotted-path → value edits (e.g.
            ``{"infrastructure.tunnel.mode": "cloudflare"}``).
        clear_fields (list[str] | None): Dotted paths to delete first, so stale
            mutually-exclusive credentials (e.g. a prior ``token`` when switching to a
            config file or another mode) do not linger.
        secret_logical_key (str | None): Secrets-chain logical id to write, if any.
        secret_config_ref_path (str | None): Dotted path receiving the secret ref.
        secret_config_ref_value (str | None): ``${SECRET:…}`` ref value to stamp.
        secret_plaintext (str | None): Secret plaintext to store, if any.
        confirm_fingerprint (str | None): Required when overwriting a differing secret.

    Returns:
        TunnelSetupResult: Store metadata.

    Raises:
        ValueError: On overwrite-guard or secrets I/O failure.

    Examples:
        >>> from pathlib import Path
        >>> apply_tunnel_setup_local(
        ...     GatewayTokenBootstrap(Path("s.json"), Path("."), None),
        ...     config_fields={"infrastructure.tunnel.mode": "cloudflare"},
        ... )  # doctest: +SKIP
    """

    def _stamp(doc: dict[str, Any]) -> None:
        for dotted in clear_fields or []:
            del_nested(doc, dotted)
        for dotted, value in config_fields.items():
            set_nested(doc, dotted, value)
        if secret_config_ref_path and secret_config_ref_value:
            set_nested(doc, secret_config_ref_path, secret_config_ref_value)

    mutate_sevn_json(bootstrap.sevn_json_path, _stamp)

    if not (secret_logical_key and secret_plaintext):
        return TunnelSetupResult(
            fingerprint_sha256_hex=None,
            overwritten=False,
            secret_ref=secret_config_ref_value,
        )

    from sevn.cli.asyncio_util import run_sync_coro
    from sevn.config.workspace_config import effective_encrypted_file_key_source
    from sevn.security.secrets.passphrase_prime import reconcile_unlock_env_with_keychain

    key_source = effective_encrypted_file_key_source(bootstrap.secrets_backend)
    run_sync_coro(reconcile_unlock_env_with_keychain(key_source=key_source))

    chain = bootstrap.chain()
    overwritten = run_sync_coro(
        _write_secret_key(
            chain,
            logical_key=secret_logical_key,
            plaintext=secret_plaintext,
            confirm_fingerprint=confirm_fingerprint,
        ),
    )
    return TunnelSetupResult(
        fingerprint_sha256_hex=fingerprint_sha256_hex(secret_plaintext),
        overwritten=overwritten,
        secret_ref=secret_config_ref_value,
    )


__all__ = ["TunnelSetupResult", "apply_tunnel_setup_local"]
