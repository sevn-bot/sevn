"""Mission Control owner login password constants and secret-ref resolution.

Module: sevn.ui.dashboard.dashboard_password
Depends: sevn.gateway.gateway_token, sevn.config.settings, sevn.security.secrets.*

Constants:
    DASHBOARD_LOGIN_PASSWORD_LOGICAL_KEY — secrets chain logical id.
    DASHBOARD_LOGIN_PASSWORD_CONFIG_REF — default ``dashboard.login_password`` placeholder.
    DASHBOARD_LOGIN_PASSWORD_MIN_CHARS — minimum accepted plaintext length.

Exports:
    generate_dashboard_login_password — CSPRNG owner password.
    validate_dashboard_login_password_plaintext — reject empty/short values.
    resolve_dashboard_login_password_ref — expand env + ``${SECRET:…}`` refs to plaintext.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from sevn.config.settings import ProcessSettings
from sevn.gateway.gateway_token import resolve_config_ref

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.config.workspace_config import WorkspaceConfig

DASHBOARD_LOGIN_PASSWORD_LOGICAL_KEY: str = "sevn.dashboard.password"
DASHBOARD_LOGIN_PASSWORD_CONFIG_REF: str = "${SECRET:keychain:sevn.dashboard.password}"
DASHBOARD_LOGIN_PASSWORD_MIN_CHARS: int = 12


def validate_dashboard_login_password_plaintext(value: str) -> str:
    """Validate operator-supplied Mission Control login password.

    Args:
        value (str): Candidate password.

    Returns:
        str: Stripped plaintext.

    Raises:
        ValueError: When empty or shorter than ``DASHBOARD_LOGIN_PASSWORD_MIN_CHARS``.

    Examples:
        >>> validate_dashboard_login_password_plaintext("x" * 12) == "x" * 12
        True
        >>> import pytest
        >>> with pytest.raises(ValueError, match="at least"):
        ...     validate_dashboard_login_password_plaintext("short")
    """
    text = value.strip()
    if not text:
        msg = "dashboard login password must be non-empty"
        raise ValueError(msg)
    if len(text) < DASHBOARD_LOGIN_PASSWORD_MIN_CHARS:
        msg = (
            f"dashboard login password must be at least "
            f"{DASHBOARD_LOGIN_PASSWORD_MIN_CHARS} characters"
        )
        raise ValueError(msg)
    return text


def generate_dashboard_login_password() -> str:
    """Return a new random Mission Control owner password.

    Returns:
        str: URL-safe random password (32 chars).

    Examples:
        >>> len(generate_dashboard_login_password()) >= DASHBOARD_LOGIN_PASSWORD_MIN_CHARS
        True
    """
    return secrets.token_urlsafe(24)


async def resolve_dashboard_login_password_ref(
    workspace: WorkspaceConfig,
    *,
    content_root: Path,
    process: ProcessSettings | None = None,
) -> str | None:
    """Resolve effective Mission Control owner login password from config refs.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json``.
        content_root (Path): Workspace content root for encrypted-file backends.
        process (ProcessSettings | None): Process env; default fresh settings.

    Returns:
        str | None: Login password when configured and resolved.

    Examples:
        >>> import asyncio
        >>> import inspect
        >>> inspect.iscoroutinefunction(resolve_dashboard_login_password_ref)
        True
    """
    section = workspace.dashboard
    ref_raw: str | None = None
    if section is not None and section.login_password:
        ref_raw = str(section.login_password).strip()
    if not ref_raw:
        return None
    return await resolve_config_ref(
        workspace,
        content_root=content_root,
        ref_raw=ref_raw,
        process=process,
        unresolved_log_label="dashboard_login_password_ref_unresolved",
    )


__all__ = [
    "DASHBOARD_LOGIN_PASSWORD_CONFIG_REF",
    "DASHBOARD_LOGIN_PASSWORD_LOGICAL_KEY",
    "DASHBOARD_LOGIN_PASSWORD_MIN_CHARS",
    "generate_dashboard_login_password",
    "resolve_dashboard_login_password_ref",
    "validate_dashboard_login_password_plaintext",
]
