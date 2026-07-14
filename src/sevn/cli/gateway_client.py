"""HTTP client for gateway probes (`specs/23-cli.md` §2.3, §2.10).

Module: sevn.cli.gateway_client
Depends: httpx, urllib.parse, sevn.config.defaults, sevn.config.settings, sevn.config.workspace_config

Exports:
    resolve_gateway_base_url — ``SEVN_GATEWAY_URL`` → ``sevn.json`` host/port, ``http`` loopback v1.
    resolve_gateway_token — ``SEVN_GATEWAY_TOKEN`` → ``gateway.token`` in ``sevn.json``.
    probe_gateway_listen_state — ``running`` / ``absent`` / ``conflict`` on configured gateway port.
    gateway_listen_conflict_detail — human detail when another process owns the port.
    gateway_get — idempotent ``GET`` with retries and exit-code mapping.
    gateway_json_request — JSON ``GET``/``POST``/``PUT``/``DELETE`` (no mutating retries).
    proxy_healthz_get — ``GET`` proxy ``/healthz`` for doctor.
    resolve_proxy_base_url — ``SEVN_PROXY_URL`` → workspace proxy port fallback.
    probe_proxy_listen_state — ``running`` / ``absent`` / ``conflict`` on proxy port.
    proxy_listen_conflict_detail — human detail when another process owns the proxy port.
"""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from sevn.cli.errors import CliAuthError, CliPreconditionError, CliUsageError
from sevn.config.defaults import (
    CLI_GATEWAY_GET_DEFAULT_TIMEOUT_S,
    CLI_GATEWAY_GET_LIVENESS_TIMEOUT_S,
    CLI_GATEWAY_GET_MAX_RETRIES,
    CLI_GATEWAY_GET_RETRY_BACKOFF_S,
    DEFAULT_GATEWAY_HOST,
    DEFAULT_GATEWAY_PORT,
    DEFAULT_PROXY_PORT,
)
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import WorkspaceConfig


def resolve_gateway_base_url(
    *,
    process: ProcessSettings | None = None,
    workspace: WorkspaceConfig | None = None,
) -> str:
    """Resolve gateway origin per ``specs/23-cli.md`` §2.3 (first match wins).

    Args:
        process (ProcessSettings | None): Parsed env; default fresh settings.
        workspace (WorkspaceConfig | None): Parsed ``sevn.json`` for host/port fallback.

    Returns:
        str: Origin without trailing slash.

    Raises:
        CliUsageError: When ``SEVN_GATEWAY_URL`` is set but not a valid HTTP(S) origin.

    Examples:
        >>> isinstance(resolve_gateway_base_url(), str)
        True
    """
    ps = process or ProcessSettings()
    raw = (ps.gateway_url or "").strip()
    if raw:
        parsed = urlparse(raw)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise CliUsageError(f"SEVN_GATEWAY_URL is not a valid origin: {raw!r}")
        return raw.rstrip("/")
    gw = workspace.gateway if workspace is not None else None
    host = (gw.host if gw and gw.host else None) or DEFAULT_GATEWAY_HOST
    port = int((gw.port if gw and gw.port is not None else None) or DEFAULT_GATEWAY_PORT)
    scheme = "http"
    if host not in ("127.0.0.1", "localhost", "::1"):
        scheme = "http"
    return f"{scheme}://{host}:{port}".rstrip("/")


def _bound_content_root() -> Path | None:
    """Best-effort content root of the bound workspace for ``${SECRET:…}`` expansion.

    Returns ``None`` when no ``sevn.json`` is bound (e.g. unit tests with an unrelated
    in-memory ``WorkspaceConfig``), so callers fall back to "no token" rather than crash.

    Returns:
        Path | None: ``<SEVN_HOME>/workspace`` when bound, else ``None``.

    Examples:
        >>> isinstance(_bound_content_root(), (type(None), Path))
        True
    """
    from sevn.cli.workspace import bound_sevn_json_path

    sevn_json = bound_sevn_json_path()
    if not sevn_json.is_file():
        return None
    return sevn_json.parent


def resolve_gateway_token(
    *,
    process: ProcessSettings | None = None,
    workspace: WorkspaceConfig | None = None,
    content_root: Path | None = None,
) -> str | None:
    """Resolve gateway bearer token (process env overrides expanded ``gateway.token``).

    When the configured token is a ``${SECRET:…}``/``${ENV:…}`` ref and ``content_root``
    is not supplied, the bound workspace's content root is derived automatically so a
    caller that omits ``content_root`` does not silently resolve to "no token" for a token
    that *is* configured (H3). Pass ``content_root`` explicitly to override.

    .. note::

        This is a synchronous wrapper around the async ``resolve_gateway_token_ref`` via
        :func:`sevn.cli.asyncio_util.run_sync_coro` (safe when a loop is already active).
        Async callers should await ``resolve_gateway_token_ref`` directly (H4).

    Args:
        process (ProcessSettings | None): Parsed env; default fresh settings.
        workspace (WorkspaceConfig | None): Parsed ``sevn.json`` for token fallback.
        content_root (Path | None): Workspace content root for ``${SECRET:…}`` expansion;
            derived from the bound workspace when omitted and the token needs expansion.

    Returns:
        str | None: Bearer token when configured.

    Examples:
        >>> from sevn.config.workspace_config import GatewayConfig, WorkspaceConfig
        >>> resolve_gateway_token(
        ...     process=ProcessSettings(),
        ...     workspace=WorkspaceConfig(
        ...         schema_version=1,
        ...         gateway=GatewayConfig(
        ...             token="literal-gateway-token-at-least-32-chars",
        ...         ),
        ...     ),
        ... )
        'literal-gateway-token-at-least-32-chars'
    """
    ps = process or ProcessSettings()
    env_token = (ps.gateway_token or "").strip()
    if env_token:
        return env_token
    if workspace is None:
        return None
    ref_raw = (
        workspace.gateway.token.strip()
        if workspace.gateway is not None and workspace.gateway.token
        else ""
    )
    if not ref_raw:
        return None
    if "${" in ref_raw:
        root = content_root if content_root is not None else _bound_content_root()
        if root is None:
            return None
        from sevn.cli.asyncio_util import run_sync_coro
        from sevn.config.workspace_config import effective_encrypted_file_key_source
        from sevn.gateway.runtime.gateway_token import resolve_gateway_token_ref
        from sevn.security.secrets.passphrase_prime import reconcile_unlock_env_with_keychain

        key_source = effective_encrypted_file_key_source(workspace.secrets_backend)
        run_sync_coro(reconcile_unlock_env_with_keychain(key_source=key_source))
        return run_sync_coro(
            resolve_gateway_token_ref(workspace, content_root=root, process=ps),
        )
    return ref_raw


_GATEWAY_TOKEN_REQUIRED_MSG: str = (
    "gateway auth token is required — run `sevn gateway set-gateway-token` "
    "or set SEVN_GATEWAY_TOKEN"
)


def probe_gateway_listen_state(*, workspace: WorkspaceConfig | None = None) -> str:
    """Classify what is listening on the configured gateway port.

    Args:
        workspace (WorkspaceConfig | None): Parsed ``sevn.json`` for host/port fallback.

    Returns:
        str: ``running`` when ``GET /health`` succeeds, ``conflict`` when HTTP 404 on
            ``/health``, else ``absent``.

    Examples:
        >>> probe_gateway_listen_state(workspace=WorkspaceConfig.minimal()) in (
        ...     "running",
        ...     "absent",
        ...     "conflict",
        ... )
        True
    """
    base = resolve_gateway_base_url(workspace=workspace)
    url = f"{base}/health"
    try:
        with httpx.Client(timeout=1.5) as client:
            response = client.get(url)
    except (httpx.RequestError, OSError, ValueError):
        return "absent"
    if response.status_code < 400:
        return "running"
    if response.status_code == 404:
        return "conflict"
    return "absent"


def gateway_listen_conflict_detail(*, workspace: WorkspaceConfig | None = None) -> str:
    """Return operator-facing detail when the gateway port is owned by a non-sevn process.

    Args:
        workspace (WorkspaceConfig | None): Parsed ``sevn.json`` for host/port fallback.

    Returns:
        str: Actionable message including the configured host/port.

    Examples:
        >>> "port" in gateway_listen_conflict_detail(
        ...     workspace=WorkspaceConfig.minimal()
        ... )
        True
    """
    gw = workspace.gateway if workspace is not None else None
    host = (gw.host if gw and gw.host else None) or DEFAULT_GATEWAY_HOST
    port = int((gw.port if gw and gw.port is not None else None) or DEFAULT_GATEWAY_PORT)
    return (
        f"port {host}:{port} is in use but does not expose GET /health — "
        "stop the other process (e.g. another uvicorn app on the same port) or change "
        "gateway.port in sevn.json, then start the sevn gateway"
    )


def _is_transient(exc: BaseException, response: httpx.Response | None) -> bool:
    """Return True when a ``GET`` failure is retryable per §2.3.

    Args:
        exc (BaseException): Raised exception when applicable.
        response (httpx.Response | None): HTTP response when applicable.

    Returns:
        bool: Whether to retry after backoff.

    Examples:
        >>> _is_transient(RuntimeError("x"), None)
        False
    """
    if response is not None and response.status_code >= 500:
        return True
    return isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
        ),
    )


def gateway_get(
    path: str,
    *,
    process: ProcessSettings | None = None,
    workspace: WorkspaceConfig | None = None,
    liveness: bool = False,
    token: str | None = None,
    require_token: bool = False,
    transport: httpx.BaseTransport | None = None,
    content_root: Path | None = None,
) -> httpx.Response:
    """Perform an idempotent ``GET`` with retries and exit-code mapping.

    Args:
        path (str): Path under the gateway origin (e.g. ``/health``).
        process (ProcessSettings | None): Parsed env; default fresh settings.
        workspace (WorkspaceConfig | None): Parsed ``sevn.json`` for URL fallback.
        liveness (bool): Use short timeout when True.
        token (str | None): Bearer override; default from ``process``.
        require_token (bool): Fail before I/O when token missing and True.
        transport (httpx.BaseTransport | None): Optional transport for tests.
        content_root (Path | None): Workspace root for ``${SECRET:…}`` token expansion.

    Returns:
        httpx.Response: Successful response with status ``<400`` after retries.

    Raises:
        CliAuthError: Missing token when required, or HTTP 401/403.
        CliPreconditionError: Client HTTP errors, transport exhaustion, or 5xx after retries.

    Examples:
        >>> import httpx
        >>> t = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}, request=r))
        >>> gateway_get(
        ...     "/health",
        ...     workspace=WorkspaceConfig.minimal(),
        ...     transport=t,
        ... ).status_code
        200
    """
    ps = process or ProcessSettings()
    base = resolve_gateway_base_url(process=ps, workspace=workspace)
    url = base + (path if path.startswith("/") else f"/{path}")
    auth_token = (
        token
        if token is not None
        else resolve_gateway_token(
            process=ps,
            workspace=workspace,
            content_root=content_root,
        )
    )
    if require_token and not (auth_token or "").strip():
        raise CliAuthError(_GATEWAY_TOKEN_REQUIRED_MSG)
    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token.strip()}"
    timeout = CLI_GATEWAY_GET_LIVENESS_TIMEOUT_S if liveness else CLI_GATEWAY_GET_DEFAULT_TIMEOUT_S
    last_exc: BaseException | None = None
    for attempt in range(1 + CLI_GATEWAY_GET_MAX_RETRIES):
        try:
            with httpx.Client(timeout=timeout, transport=transport) as client:
                r = client.get(url, headers=headers)
            if r.status_code in (401, 403):
                raise CliAuthError(f"gateway auth failed ({r.status_code}) for {url}")
            if 400 <= r.status_code < 500:
                raise CliPreconditionError(
                    f"gateway HTTP {r.status_code}: {url}",
                    exit_code=4,
                )
            if r.status_code >= 500:
                raise httpx.HTTPStatusError(
                    "server error",
                    request=httpx.Request("GET", url),
                    response=r,
                )
            return r
        except CliAuthError:
            raise
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if _is_transient(exc, exc.response) and attempt < CLI_GATEWAY_GET_MAX_RETRIES:
                time.sleep(CLI_GATEWAY_GET_RETRY_BACKOFF_S)
                continue
            raise CliPreconditionError(
                f"gateway HTTP error: {exc.response.status_code} {url}",
                exit_code=4,
            ) from exc
        except (httpx.RequestError, OSError, ValueError) as exc:
            last_exc = exc
            if _is_transient(exc, None) and attempt < CLI_GATEWAY_GET_MAX_RETRIES:
                time.sleep(CLI_GATEWAY_GET_RETRY_BACKOFF_S)
                continue
            raise CliPreconditionError(
                f"gateway unreachable: {url} ({exc})",
                exit_code=4,
            ) from exc
    raise CliPreconditionError(
        f"gateway GET failed after retries: {url} ({last_exc})",
        exit_code=4,
    ) from last_exc


def gateway_json_request(
    method: str,
    path: str,
    *,
    process: ProcessSettings | None = None,
    workspace: WorkspaceConfig | None = None,
    json_body: dict[str, object] | None = None,
    require_token: bool = True,
    transport: httpx.BaseTransport | None = None,
    content_root: Path | None = None,
) -> httpx.Response:
    """Perform one JSON gateway call with auth and exit-code mapping.

    Mutating methods do not retry (`specs/23-cli.md` §2.3).

    Args:
        method (str): HTTP verb (``GET``, ``POST``, ``PUT``, ``DELETE``).
        path (str): Path under the gateway origin.
        process (ProcessSettings | None): Parsed env; default fresh settings.
        workspace (WorkspaceConfig | None): Parsed ``sevn.json`` for URL fallback.
        json_body (dict[str, object] | None): Optional JSON request body.
        require_token (bool): Fail before I/O when token missing and True.
        transport (httpx.BaseTransport | None): Optional transport for tests.
        content_root (Path | None): Workspace root for ``${SECRET:…}`` token expansion.

    Returns:
        httpx.Response: HTTP response (caller may inspect status and JSON).

    Raises:
        CliAuthError: Missing token when required, or HTTP 401/403.
        CliPreconditionError: Client errors, transport failures, or 5xx.

    Examples:
        >>> import httpx
        >>> t = httpx.MockTransport(lambda r: httpx.Response(200, json={}, request=r))
        >>> gateway_json_request(
        ...     "GET",
        ...     "/api/v1/admin/secrets",
        ...     workspace=WorkspaceConfig.minimal(),
        ...     transport=t,
        ...     require_token=False,
        ... ).status_code
        200
    """
    ps = process or ProcessSettings()
    base = resolve_gateway_base_url(process=ps, workspace=workspace)
    url = base + (path if path.startswith("/") else f"/{path}")
    auth_token = resolve_gateway_token(
        process=ps,
        workspace=workspace,
        content_root=content_root,
    )
    if require_token and not (auth_token or "").strip():
        raise CliAuthError(_GATEWAY_TOKEN_REQUIRED_MSG)
    headers: dict[str, str] = {"Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token.strip()}"
    timeout = CLI_GATEWAY_GET_DEFAULT_TIMEOUT_S
    verb = method.upper()
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.request(verb, url, headers=headers, json=json_body)
    except (httpx.RequestError, OSError, ValueError) as exc:
        raise CliPreconditionError(
            f"gateway unreachable: {url} ({exc})",
            exit_code=4,
        ) from exc
    if response.status_code in (401, 403):
        raise CliAuthError(f"gateway auth failed ({response.status_code}) for {url}")
    if response.status_code >= 500:
        raise CliPreconditionError(
            f"gateway HTTP {response.status_code}: {url}",
            exit_code=4,
        )
    return response


def proxy_healthz_get(
    proxy_origin: str,
    *,
    liveness: bool = True,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Response:
    """``GET {proxy}/healthz`` for doctor (`specs/07-egress-proxy.md`, `specs/23-cli.md` §3).

    Args:
        proxy_origin (str): Proxy base URL.
        liveness (bool): Use short timeout when True.
        transport (httpx.BaseTransport | None): Optional transport for tests.

    Returns:
        httpx.Response: Raw response (caller checks status).

    Raises:
        CliPreconditionError: When the proxy is unreachable after retries.

    Examples:
        >>> import httpx
        >>> t = httpx.MockTransport(lambda r: httpx.Response(200, request=r))
        >>> proxy_healthz_get("http://127.0.0.1:1", transport=t).status_code
        200
    """
    base = proxy_origin.strip().rstrip("/")
    url = f"{base}/healthz"
    timeout = CLI_GATEWAY_GET_LIVENESS_TIMEOUT_S if liveness else CLI_GATEWAY_GET_DEFAULT_TIMEOUT_S
    last_exc: BaseException | None = None
    for attempt in range(1 + CLI_GATEWAY_GET_MAX_RETRIES):
        try:
            with httpx.Client(timeout=timeout, transport=transport) as client:
                return client.get(url)
        except (httpx.RequestError, OSError, ValueError) as exc:
            last_exc = exc
            if _is_transient(exc, None) and attempt < CLI_GATEWAY_GET_MAX_RETRIES:
                time.sleep(CLI_GATEWAY_GET_RETRY_BACKOFF_S)
                continue
            raise CliPreconditionError(
                f"proxy unreachable: {url} ({exc})",
                exit_code=4,
            ) from exc
    raise CliPreconditionError(
        f"proxy GET failed after retries: {url} ({last_exc})",
        exit_code=4,
    ) from last_exc


def resolve_proxy_base_url(
    *,
    process: ProcessSettings | None = None,
    workspace: WorkspaceConfig | None = None,
) -> str:
    """Resolve proxy origin per ``specs/23-cli.md`` (``SEVN_PROXY_URL`` then config).

    Args:
        process (ProcessSettings | None): Parsed env; default fresh settings.
        workspace (WorkspaceConfig | None): Parsed ``sevn.json`` for port fallback.

    Returns:
        str: Origin without trailing slash.

    Examples:
        >>> isinstance(resolve_proxy_base_url(), str)
        True
    """
    ps = process or ProcessSettings()
    raw = (ps.proxy_url or "").strip()
    if raw:
        parsed = urlparse(raw)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise CliUsageError(f"SEVN_PROXY_URL is not a valid origin: {raw!r}")
        return raw.rstrip("/")
    proxy_section = workspace.proxy if workspace is not None else None
    port = DEFAULT_PROXY_PORT
    if isinstance(proxy_section, dict):
        raw_port = proxy_section.get("port")
        if raw_port is not None:
            port = int(raw_port)
    return f"http://127.0.0.1:{port}".rstrip("/")


def probe_proxy_listen_state(*, workspace: WorkspaceConfig | None = None) -> str:
    """Classify what is listening on the configured proxy port.

    Args:
        workspace (WorkspaceConfig | None): Parsed ``sevn.json`` for port fallback.

    Returns:
        str: ``running`` when ``GET /healthz`` succeeds, ``conflict`` when HTTP 404,
            else ``absent``.

    Examples:
        >>> probe_proxy_listen_state(workspace=WorkspaceConfig.minimal()) in (
        ...     "running",
        ...     "absent",
        ...     "conflict",
        ... )
        True
    """
    base = resolve_proxy_base_url(workspace=workspace)
    url = f"{base}/healthz"
    try:
        with httpx.Client(timeout=1.5) as client:
            response = client.get(url)
    except (httpx.RequestError, OSError, ValueError):
        return "absent"
    if response.status_code < 400:
        return "running"
    if response.status_code == 404:
        return "conflict"
    return "absent"


def proxy_listen_conflict_detail(*, workspace: WorkspaceConfig | None = None) -> str:
    """Return operator-facing detail when the proxy port is owned by a non-sevn process.

    Args:
        workspace (WorkspaceConfig | None): Parsed ``sevn.json`` for port fallback.

    Returns:
        str: Actionable message including the configured host/port.

    Examples:
        >>> "port" in proxy_listen_conflict_detail(
        ...     workspace=WorkspaceConfig.minimal()
        ... )
        True
    """
    base = resolve_proxy_base_url(workspace=workspace)
    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or DEFAULT_PROXY_PORT
    return (
        f"port {host}:{port} is in use but does not expose GET /healthz — "
        "stop the other process or change proxy.port in sevn.json, then start the sevn proxy"
    )
