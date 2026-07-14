"""Local Mission Control login password bootstrap (no running gateway required).

Module: sevn.cli.dashboard_login_password_store
Depends: asyncio, json, pathlib, sevn.cli.gateway_token_store, sevn.ui.dashboard.dashboard_password

Exports:
    DashboardLoginPasswordStoreResult — outcome of a local dashboard password write.
    store_dashboard_login_password_local — stamp ref + write logical key.
"""

from __future__ import annotations

from dataclasses import dataclass

from sevn.cli.gateway_token_store import GatewayTokenBootstrap, load_bootstrap_workspace
from sevn.gateway.workspace_config_io import mutate_sevn_json, set_nested
from sevn.secrets.fingerprint import fingerprint_sha256_hex
from sevn.ui.dashboard.dashboard_password import (
    DASHBOARD_LOGIN_PASSWORD_CONFIG_REF,
    DASHBOARD_LOGIN_PASSWORD_LOGICAL_KEY,
    validate_dashboard_login_password_plaintext,
)


@dataclass(frozen=True)
class DashboardLoginPasswordStoreResult:
    """Outcome of a local dashboard login password write.

    Attributes:
        fingerprint_sha256_hex (str): SHA-256 hex of stored plaintext.
        overwritten (bool): Whether a prior value existed.
        login_password_ref (str): Config ref written to ``dashboard.login_password``.
    """

    fingerprint_sha256_hex: str
    overwritten: bool
    login_password_ref: str = DASHBOARD_LOGIN_PASSWORD_CONFIG_REF


async def _write_logical_key(
    bootstrap: GatewayTokenBootstrap,
    *,
    plaintext: str,
    confirm_fingerprint: str | None,
) -> bool:
    """Write ``DASHBOARD_LOGIN_PASSWORD_LOGICAL_KEY`` when absent or fingerprint-confirmed.

    Args:
        bootstrap (GatewayTokenBootstrap): Raw-JSON workspace view.
        plaintext (str): Validated owner password.
        confirm_fingerprint (str | None): Required when overwriting a differing value.

    Returns:
        bool: ``True`` when a prior value existed (overwrite).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, patch
        >>> from sevn.cli.gateway_token_store import GatewayTokenBootstrap
        >>> from pathlib import Path
        >>> boot = GatewayTokenBootstrap(Path("s.json"), Path("."), None)
        >>> mock_chain = AsyncMock(get=AsyncMock(return_value=None), set=AsyncMock())
        >>> with patch.object(GatewayTokenBootstrap, "chain", lambda self: mock_chain):
        ...     asyncio.run(
        ...         _write_logical_key(
        ...             boot, plaintext="owner-password-12", confirm_fingerprint=None,
        ...         ),
        ...     )
        False
    """
    chain = bootstrap.chain()
    existing = await chain.get(DASHBOARD_LOGIN_PASSWORD_LOGICAL_KEY)
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
    await chain.set(DASHBOARD_LOGIN_PASSWORD_LOGICAL_KEY, plaintext)
    return existing is not None


def store_dashboard_login_password_local(
    bootstrap: GatewayTokenBootstrap,
    *,
    plaintext: str,
    confirm_fingerprint: str | None = None,
) -> DashboardLoginPasswordStoreResult:
    """Stamp ``dashboard.login_password`` ref in ``sevn.json``, then write the secret.

    Args:
        bootstrap (GatewayTokenBootstrap): Raw-JSON workspace view.
        plaintext (str): Owner login password (validated).
        confirm_fingerprint (str | None): Required when overwriting a differing logical key.

    Returns:
        DashboardLoginPasswordStoreResult: Store metadata.

    Raises:
        ValueError: On validation, overwrite guard, or secrets I/O failure.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.cli.gateway_token_store import GatewayTokenBootstrap
        >>> store_dashboard_login_password_local(
        ...     GatewayTokenBootstrap(Path("s.json"), Path("."), None),
        ...     plaintext="owner-password-12",
        ... )  # doctest: +SKIP
    """
    password = validate_dashboard_login_password_plaintext(plaintext)

    from sevn.cli.asyncio_util import run_sync_coro
    from sevn.config.workspace_config import effective_encrypted_file_key_source
    from sevn.security.secrets.passphrase_prime import reconcile_unlock_env_with_keychain

    key_source = effective_encrypted_file_key_source(bootstrap.secrets_backend)
    run_sync_coro(reconcile_unlock_env_with_keychain(key_source=key_source))

    overwritten = run_sync_coro(
        _write_logical_key(
            bootstrap,
            plaintext=password,
            confirm_fingerprint=confirm_fingerprint,
        ),
    )

    def _stamp_login_password(doc: dict[str, object]) -> None:
        dash = doc.setdefault("dashboard", {})
        if not isinstance(dash, dict):
            msg = "dashboard section must be an object"
            raise ValueError(msg)
        dash.setdefault("enabled", True)
        set_nested(doc, "dashboard.login_password", DASHBOARD_LOGIN_PASSWORD_CONFIG_REF)

    mutate_sevn_json(bootstrap.sevn_json_path, _stamp_login_password)
    fp = fingerprint_sha256_hex(password)
    return DashboardLoginPasswordStoreResult(
        fingerprint_sha256_hex=fp,
        overwritten=overwritten,
    )


__all__ = [
    "DashboardLoginPasswordStoreResult",
    "load_bootstrap_workspace",
    "store_dashboard_login_password_local",
]
