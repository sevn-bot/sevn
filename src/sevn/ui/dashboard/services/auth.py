"""Dashboard owner-session JWT helpers (`specs/24-dashboard.md` §2.2).

Module: sevn.ui.dashboard.services.auth
Depends: base64, hashlib, hmac, json, secrets, time, fastapi

Exports:
    DashboardClaims — verified ``aud=dashboard`` claim bundle.
    DashboardAuthService — password check + JWT mint/verify service.
    infrastructure_tunnel_mode — read ``infrastructure.tunnel.mode`` from workspace.
    tunnel_active — whether a public tunnel mode is configured.
    dashboard_local_open_configured — configured/effective ``dashboard.local_open``.
    is_loopback_client_host — loopback client address check.
    local_open_effective — loopback no-login bypass gate.
    synthetic_owner_claims — owner claims without a JWT.
    apply_tunnel_local_open_policy — lifespan tunnel safety for ``local_open``.
    sevn_json_path_from_request — bound ``sevn.json`` path from a dashboard request.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sevn.config.defaults import DEFAULT_DASHBOARD_JWT_TTL_SECONDS, DEFAULT_GATEWAY_HOST
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import DashboardWorkspaceConfig, WorkspaceConfig
from sevn.gateway.auth import extract_bearer

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import Request
    from starlette.websockets import WebSocket

_LOOPBACK_CLIENT_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "testclient"})
_LOOPBACK_GATEWAY_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

DASHBOARD_COOKIE_NAME = "sevn_dashboard_session"
DASHBOARD_CSRF_COOKIE_NAME = "sevn_dashboard_csrf"
DASHBOARD_CSRF_HEADER = "X-CSRF-Token"
_JWT_AUD = "dashboard"
_JWT_ALG = "HS256"
_JWT_SCOPE = ("workspace:read", "workspace:write")


@dataclass(frozen=True)
class DashboardClaims:
    """Verified dashboard JWT claims.

    Attributes:
        sub (str): Owner subject, always ``owner`` in v1.
        aud (str): JWT audience, always ``dashboard`` after verification.
        exp (int): Expiry epoch seconds.
        workspace (str): Workspace scope string.
        scope (tuple[str, ...]): Workspace permission scopes.
        iat (int): Issued-at epoch seconds.
    """

    sub: str
    aud: str
    exp: int
    workspace: str
    scope: tuple[str, ...]
    iat: int = 0


def sevn_json_path_from_request(request: Request | WebSocket) -> Path | None:
    """Return the bound ``sevn.json`` path from a dashboard HTTP or WS request.

    Args:
        request (Request | WebSocket): Incoming ASGI connection.

    Returns:
        Path | None: Workspace config path when the gateway layout is available.

    Examples:
        >>> sevn_json_path_from_request.__name__
        'sevn_json_path_from_request'
    """
    from pathlib import Path

    app = None
    scope = getattr(request, "scope", None)
    if isinstance(scope, dict):
        app = scope.get("app")
    if app is None:
        return None
    layout = getattr(app.state, "layout", None)
    path = getattr(layout, "sevn_json_path", None) if layout is not None else None
    return path if isinstance(path, Path) else None


def infrastructure_tunnel_mode(
    workspace: WorkspaceConfig,
    *,
    sevn_json: Path | None = None,
) -> str:
    """Return ``infrastructure.tunnel.mode`` from workspace extras.

    When ``sevn_json`` is supplied (or the bound workspace file exists on disk),
    reads the live tunnel section so CLI setup without gateway restart is visible
    to auth and dashboard policy checks.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        sevn_json (Path | None): Explicit ``sevn.json`` path override.

    Returns:
        str: Tunnel mode name; ``none`` when unset.

    Examples:
        >>> infrastructure_tunnel_mode(WorkspaceConfig.minimal())
        'none'
    """
    from sevn.infrastructure.tunnel_config import tunnel_cfg_from_disk

    tunnel = tunnel_cfg_from_disk(workspace, sevn_json=sevn_json)
    mode = tunnel.get("mode")
    if isinstance(mode, str) and mode.strip():
        return mode.strip()
    return "none"


def tunnel_active(
    workspace: WorkspaceConfig,
    *,
    sevn_json: Path | None = None,
) -> bool:
    """Return whether intentional internet tunnel exposure is configured.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        sevn_json (Path | None): Explicit ``sevn.json`` path override.

    Returns:
        bool: ``True`` when ``infrastructure.tunnel.mode`` is not ``none``.

    Examples:
        >>> tunnel_active(WorkspaceConfig.minimal())
        False
    """

    return infrastructure_tunnel_mode(workspace, sevn_json=sevn_json) != "none"


def _gateway_bind_loopback(workspace: WorkspaceConfig) -> bool:
    """Return whether ``gateway.host`` binds loopback-only.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.

    Returns:
        bool: ``True`` for loopback bind addresses.

    Examples:
        >>> _gateway_bind_loopback(WorkspaceConfig.minimal())
        True
    """

    gw = workspace.gateway
    host = (gw.host if gw and gw.host else None) or DEFAULT_GATEWAY_HOST
    return host.strip().lower() in _LOOPBACK_GATEWAY_HOSTS


def dashboard_local_open_configured(
    workspace: WorkspaceConfig,
    *,
    sevn_json: Path | None = None,
) -> bool:
    """Return configured/effective ``dashboard.local_open`` after tunnel policy.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config (post-lifespan policy).
        sevn_json (Path | None): Explicit ``sevn.json`` path override.

    Returns:
        bool: Whether loopback bypass is allowed by config.

    Examples:
        >>> dashboard_local_open_configured(WorkspaceConfig.minimal())
        True
    """

    if tunnel_active(workspace, sevn_json=sevn_json):
        return False
    section = _dashboard_section(workspace)
    if section is not None:
        raw = getattr(section, "local_open", None)
        if raw is not None:
            return bool(raw)
    return _gateway_bind_loopback(workspace)


def is_loopback_client_host(host: str | None) -> bool:
    """Return whether an HTTP/WebSocket client host is loopback.

    Args:
        host (str | None): Client host from ASGI scope.

    Returns:
        bool: ``True`` for loopback/test client addresses.

    Examples:
        >>> is_loopback_client_host("127.0.0.1")
        True
        >>> is_loopback_client_host("203.0.113.1")
        False
    """

    if not host:
        return False
    return host.strip().lower() in _LOOPBACK_CLIENT_HOSTS


def local_open_effective(workspace: WorkspaceConfig, request: Request | WebSocket) -> bool:
    """Return whether this request may use the loopback owner bypass.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        request (Request | WebSocket): HTTP request or WebSocket connection.

    Returns:
        bool: ``True`` for loopback clients when local-open is configured and no tunnel.

    Examples:
        >>> from starlette.requests import Request
        >>> scope = {"type": "http", "client": ("127.0.0.1", 123), "headers": []}
        >>> req = Request(scope)
        >>> local_open_effective(WorkspaceConfig.minimal(), req)
        True
    """

    if not dashboard_local_open_configured(
        workspace,
        sevn_json=sevn_json_path_from_request(request),
    ):
        return False
    client = request.client
    return is_loopback_client_host(client.host if client is not None else None)


def synthetic_owner_claims(workspace: WorkspaceConfig) -> DashboardClaims:
    """Mint synthetic owner claims for local-open sessions.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.

    Returns:
        DashboardClaims: Owner-capable claims without a signed JWT.

    Examples:
        >>> claims = synthetic_owner_claims(WorkspaceConfig.minimal())
        >>> claims.sub == "owner" and claims.aud == "dashboard"
        True
    """

    now = int(time.time())
    return DashboardClaims(
        sub="owner",
        aud="dashboard",
        exp=now + DEFAULT_DASHBOARD_JWT_TTL_SECONDS,
        workspace=workspace.workspace_root or ".",
        scope=("workspace:read", "workspace:write"),
        iat=now,
    )


def apply_tunnel_local_open_policy(workspace: WorkspaceConfig) -> None:
    """Force ``dashboard.local_open`` off when a tunnel mode is active.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config (mutated in place).

    Returns:
        None: Side-effect only.

    Examples:
        >>> from sevn.config.workspace_config import DashboardWorkspaceConfig
        >>> ws = WorkspaceConfig.minimal(
        ...     dashboard=DashboardWorkspaceConfig(enabled=True, local_open=True),
        ...     infrastructure={"tunnel": {"mode": "cloudflare"}},
        ... )
        >>> apply_tunnel_local_open_policy(ws)
        >>> ws.dashboard is not None and ws.dashboard.local_open is False
        True
    """

    if not tunnel_active(workspace):
        return
    section = _dashboard_section(workspace)
    if section is None:
        return
    if getattr(section, "local_open", None) is True:
        from loguru import logger

        logger.warning(
            "dashboard.local_open=true ignored because infrastructure.tunnel.mode is active; "
            "forcing dashboard.local_open=false",
        )
    section.local_open = False


def _dashboard_section(workspace: WorkspaceConfig) -> DashboardWorkspaceConfig | None:
    """Return the typed dashboard section when present.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        DashboardWorkspaceConfig | None: Dashboard config model or ``None``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _dashboard_section(WorkspaceConfig.minimal()) is None
        True
    """

    return getattr(workspace, "dashboard", None)


def _b64url_encode(data: bytes) -> str:
    """Return URL-safe base64 text without padding.

    Args:
        data (bytes): Raw bytes.

    Returns:
        str: Encoded ASCII string.

    Examples:
        >>> _b64url_encode(b"hi")
        'aGk'
    """

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(token: str) -> bytes:
    """Decode URL-safe base64 text.

    Args:
        token (str): Encoded text without padding.

    Returns:
        bytes: Decoded bytes.

    Examples:
        >>> _b64url_decode("aGk")
        b'hi'
    """

    pad = "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode((token + pad).encode("ascii"))


class DashboardAuthService:
    """Owner auth service for Mission Control.

    The signing key is workspace-configured when available and otherwise
    generated in-process, which matches the v1 restart-rotation allowance.
    """

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig | None,
        process_settings: ProcessSettings,
        jwt_secret: str | None = None,
    ) -> None:
        """Create the auth service.

        Args:
            workspace (WorkspaceConfig | None): Parsed workspace config when available.
            process_settings (ProcessSettings): Env-derived gateway settings.
            jwt_secret (str | None): Optional explicit signing secret for tests.

        Examples:
            >>> svc = DashboardAuthService(
            ...     workspace=None,
            ...     process_settings=ProcessSettings(),
            ...     jwt_secret="s",
            ... )
            >>> isinstance(svc, DashboardAuthService)
            True
        """

        self._workspace = workspace
        self._process = process_settings
        self._secret = jwt_secret or self._configured_secret(workspace) or secrets.token_urlsafe(32)

    @property
    def cookie_name(self) -> str:
        """Return the dashboard session cookie name.

        Returns:
            str: Stable cookie name.

        Examples:
            >>> DashboardAuthService(
            ...     workspace=None,
            ...     process_settings=ProcessSettings(),
            ...     jwt_secret="s",
            ... ).cookie_name
            'sevn_dashboard_session'
        """

        return DASHBOARD_COOKIE_NAME

    def can_login(self, workspace: WorkspaceConfig | None = None) -> bool:
        """Return whether a configured credential exists.

        Args:
            workspace (WorkspaceConfig | None): Optional current workspace override.

        Returns:
            bool: ``True`` when login can be checked.

        Examples:
            >>> DashboardAuthService(
            ...     workspace=None,
            ...     process_settings=ProcessSettings(),
            ...     jwt_secret="s",
            ... ).can_login()
            False
        """

        return bool(self._configured_password(workspace or self._workspace))

    def verify_login(self, *, password: str, workspace: WorkspaceConfig | None = None) -> bool:
        """Verify the owner login password.

        Args:
            password (str): Password-like login token submitted by the owner.
            workspace (WorkspaceConfig | None): Optional current workspace override.

        Returns:
            bool: ``True`` when the supplied password matches the configured secret.

        Examples:
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> ws = WorkspaceConfig.minimal(dashboard={"login_password": "pw"})
            >>> svc = DashboardAuthService(
            ...     workspace=ws,
            ...     process_settings=ProcessSettings(),
            ...     jwt_secret="s",
            ... )
            >>> svc.verify_login(password="pw")
            True
        """

        configured = self._configured_password(workspace or self._workspace)
        if configured is None:
            return False
        return hmac.compare_digest(configured, password)

    def mint_dashboard_jwt(
        self,
        *,
        workspace: WorkspaceConfig | None = None,
        now: int | None = None,
    ) -> tuple[str, int]:
        """Mint an ``aud=dashboard`` JWT for the owner.

        Args:
            workspace (WorkspaceConfig | None): Optional current workspace override.
            now (int | None): Epoch seconds override for tests.

        Returns:
            tuple[str, int]: ``(token, expires_in_seconds)`` pair.

        Examples:
            >>> svc = DashboardAuthService(
            ...     workspace=None,
            ...     process_settings=ProcessSettings(),
            ...     jwt_secret="s",
            ... )
            >>> token, ttl = svc.mint_dashboard_jwt(now=100)
            >>> isinstance(token, str) and ttl > 0
            True
        """

        ws = workspace or self._workspace
        ttl = self._ttl_seconds(ws)
        issued = int(now if now is not None else time.time())
        payload = {
            "sub": "owner",
            "aud": _JWT_AUD,
            "iat": issued,
            "exp": issued + ttl,
            "workspace": self._workspace_scope(ws),
            "scope": " ".join(_JWT_SCOPE),
        }
        header = {"alg": _JWT_ALG, "typ": "JWT"}
        enc_header = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        enc_payload = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{enc_header}.{enc_payload}".encode("ascii")
        sig = hmac.new(self._secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        return f"{enc_header}.{enc_payload}.{_b64url_encode(sig)}", ttl

    def verify_dashboard_jwt(self, token: str, *, now: int | None = None) -> DashboardClaims | None:
        """Verify a dashboard JWT.

        Args:
            token (str): Compact JWT text.
            now (int | None): Epoch seconds override for tests.

        Returns:
            DashboardClaims | None: Claims on success; ``None`` on failure.

        Examples:
            >>> svc = DashboardAuthService(
            ...     workspace=None,
            ...     process_settings=ProcessSettings(),
            ...     jwt_secret="s",
            ... )
            >>> tok, _ = svc.mint_dashboard_jwt(now=100)
            >>> svc.verify_dashboard_jwt(tok, now=101).aud
            'dashboard'
        """

        parts = token.split(".")
        if len(parts) != 3:
            return None
        enc_header, enc_payload, enc_sig = parts
        signing_input = f"{enc_header}.{enc_payload}".encode("ascii")
        expected = hmac.new(self._secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        try:
            provided = _b64url_decode(enc_sig)
        except (ValueError, binascii.Error):
            return None
        if not hmac.compare_digest(expected, provided):
            return None
        try:
            header = json.loads(_b64url_decode(enc_header).decode("utf-8"))
            payload = json.loads(_b64url_decode(enc_payload).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(header, dict) or header.get("alg") != _JWT_ALG:
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("aud") != _JWT_AUD or payload.get("sub") != "owner":
            return None
        exp = payload.get("exp")
        if not isinstance(exp, int):
            return None
        current = int(now if now is not None else time.time())
        if current >= exp:
            return None
        workspace = payload.get("workspace")
        if not isinstance(workspace, str):
            workspace = "default"
        scope = payload.get("scope", "")
        scope_tuple = tuple(s for s in scope.split() if s) if isinstance(scope, str) else ()
        iat = payload.get("iat", 0)
        return DashboardClaims(
            sub="owner",
            aud=_JWT_AUD,
            exp=exp,
            workspace=workspace,
            scope=scope_tuple,
            iat=iat if isinstance(iat, int) else 0,
        )

    def mint_csrf_token(self) -> str:
        """Mint a double-submit CSRF token for browser sessions.

        Returns:
            str: URL-safe random token stored in a non-httpOnly cookie.

        Examples:
            >>> svc = DashboardAuthService(
            ...     workspace=None,
            ...     process_settings=ProcessSettings(),
            ...     jwt_secret="s",
            ... )
            >>> len(svc.mint_csrf_token()) > 10
            True
        """

        return secrets.token_urlsafe(32)

    def verify_csrf(self, *, cookie: str | None, header: str | None) -> bool:
        """Verify double-submit CSRF (cookie must match header).

        Args:
            cookie (str | None): CSRF cookie value.
            header (str | None): ``X-CSRF-Token`` header value.

        Returns:
            bool: ``True`` when both are present and equal.

        Examples:
            >>> svc = DashboardAuthService(
            ...     workspace=None,
            ...     process_settings=ProcessSettings(),
            ...     jwt_secret="s",
            ... )
            >>> tok = svc.mint_csrf_token()
            >>> svc.verify_csrf(cookie=tok, header=tok)
            True
        """

        if not cookie or not header:
            return False
        return hmac.compare_digest(cookie, header)

    def token_from_request(self, *, authorization: str | None, cookie: str | None) -> str | None:
        """Extract a dashboard JWT from cookie or bearer header.

        Args:
            authorization (str | None): Raw ``Authorization`` header.
            cookie (str | None): Session cookie value.

        Returns:
            str | None: Token text if present.

        Examples:
            >>> svc = DashboardAuthService(
            ...     workspace=None,
            ...     process_settings=ProcessSettings(),
            ...     jwt_secret="s",
            ... )
            >>> svc.token_from_request(authorization="Bearer abc", cookie=None)
            'abc'
        """

        if cookie:
            return cookie
        return extract_bearer(authorization)

    def _configured_secret(self, workspace: WorkspaceConfig | None) -> str | None:
        """Return configured dashboard JWT secret.

        Args:
            workspace (WorkspaceConfig | None): Parsed workspace config.

        Returns:
            str | None: Configured signing secret when present.

        Examples:
            >>> DashboardAuthService(
            ...     workspace=None,
            ...     process_settings=ProcessSettings(),
            ...     jwt_secret="s",
            ... )._configured_secret(None) is None
            True
        """

        section = _dashboard_section(workspace) if workspace is not None else None
        raw = getattr(section, "jwt_secret", None) if section is not None else None
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return None

    def _configured_password(self, workspace: WorkspaceConfig | None) -> str | None:
        """Return configured dashboard login password/token.

        Args:
            workspace (WorkspaceConfig | None): Parsed workspace config.

        Returns:
            str | None: Password-like login secret when present.

        Examples:
            >>> DashboardAuthService(
            ...     workspace=None,
            ...     process_settings=ProcessSettings(),
            ...     jwt_secret="s",
            ... )._configured_password(None) is None
            True
        """

        section = _dashboard_section(workspace) if workspace is not None else None
        raw = getattr(section, "login_password", None) if section is not None else None
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        token = self._process.gateway_token
        if token and token.strip():
            return token.strip()
        if workspace is not None and workspace.gateway and workspace.gateway.token:
            return workspace.gateway.token.strip()
        return None

    def _ttl_seconds(self, workspace: WorkspaceConfig | None) -> int:
        """Return configured dashboard JWT TTL.

        Args:
            workspace (WorkspaceConfig | None): Parsed workspace config.

        Returns:
            int: Positive token lifetime in seconds.

        Examples:
            >>> DashboardAuthService(
            ...     workspace=None,
            ...     process_settings=ProcessSettings(),
            ...     jwt_secret="s",
            ... )._ttl_seconds(None) == DEFAULT_DASHBOARD_JWT_TTL_SECONDS
            True
        """

        section = _dashboard_section(workspace) if workspace is not None else None
        raw = getattr(section, "jwt_ttl_seconds", None) if section is not None else None
        if isinstance(raw, int) and raw > 0:
            return raw
        return DEFAULT_DASHBOARD_JWT_TTL_SECONDS

    def _workspace_scope(self, workspace: WorkspaceConfig | None) -> str:
        """Return JWT workspace scope.

        Args:
            workspace (WorkspaceConfig | None): Parsed workspace config.

        Returns:
            str: Workspace scope claim.

        Examples:
            >>> DashboardAuthService(
            ...     workspace=None,
            ...     process_settings=ProcessSettings(),
            ...     jwt_secret="s",
            ... )._workspace_scope(None)
            'default'
        """

        if workspace is None:
            return "default"
        return workspace.workspace_root or "."
