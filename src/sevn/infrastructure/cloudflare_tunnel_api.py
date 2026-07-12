"""Cloudflare Tunnel API provisioning (create tunnel, ingress, DNS).

Module: sevn.infrastructure.cloudflare_tunnel_api
Depends: dataclasses, httpx, sevn.infrastructure.tunnel_config

Exports:
    CloudflareTunnelProvisionResult — outcome of a full API provision pass.
    CloudflareApiError — Cloudflare API failure with operator-facing detail.
    provision_cloudflare_tunnel — create tunnel, route hostname, create DNS, return token.
    dns_record_name_for_zone — map FQDN hostname to a zone-relative DNS name.
    normalize_public_hostname — normalize operator hostname/URL paste to a FQDN.
    tunnel_mission_control_url — HTTPS origin for Mission Control via tunnel hostname.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from sevn.infrastructure.tunnel_config import coerce_tunnel_local_port

_CF_API_BASE = "https://api.cloudflare.com/client/v4"
_TUNNEL_NAME_SAFE_RE = re.compile(r"[^a-z0-9-]+")


class _HttpClient(Protocol):
    """Minimal HTTP client surface used by Cloudflare API helpers."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Issue an HTTP request and return the response.

        Args:
            method (str): HTTP method.
            url (str): Absolute request URL.
            headers (dict[str, str] | None): Optional request headers.
            json (dict[str, Any] | None): Optional JSON request body.
            timeout (float | None): Optional request timeout in seconds.

        Returns:
            httpx.Response: HTTP response object.

        Examples:
            >>> _HttpClient.request  # doctest: +SKIP
        """
        ...


@dataclass(frozen=True)
class CloudflareTunnelProvisionResult:
    """Outcome of a Cloudflare API tunnel provision pass.

    Attributes:
        tunnel_id (str): Cloudflare tunnel UUID.
        tunnel_token (str): Connector token for ``cloudflared tunnel run --token``.
        hostname (str): Public hostname routed to the local gateway.
        public_url (str): HTTPS URL for the published hostname.
        zone_id (str): Cloudflare zone id used for DNS.
        tunnel_name (str): Tunnel name created or reused in the account.
    """

    tunnel_id: str
    tunnel_token: str
    hostname: str
    public_url: str
    zone_id: str
    tunnel_name: str


class CloudflareApiError(RuntimeError):
    """Cloudflare API request failed.

    Examples:
        >>> str(CloudflareApiError("bad token"))
        'bad token'
    """


def tunnel_mission_control_url(hostname: str | None) -> str | None:
    """Return the HTTPS Mission Control origin for a tunnel hostname.

    Args:
        hostname (str | None): Public tunnel hostname (for example ``sevn.example.com``).

    Returns:
        str | None: ``https://<hostname>/`` when hostname is non-empty.

    Examples:
        >>> tunnel_mission_control_url("sevn.example.com")
        'https://sevn.example.com/'
        >>> tunnel_mission_control_url(None) is None
        True
    """
    host = str(hostname or "").strip().rstrip("/")
    if not host:
        return None
    return f"https://{host}/"


def dns_record_name_for_zone(hostname: str, zone_name: str) -> str:
    """Map a FQDN hostname to the DNS record ``name`` for a Cloudflare zone.

    Args:
        hostname (str): Public hostname (for example ``sevn.example.com``).
        zone_name (str): Zone apex (for example ``example.com``).

    Returns:
        str: ``@`` for apex hostnames, otherwise the left-hand label(s).

    Raises:
        ValueError: When ``hostname`` is not under ``zone_name``.

    Examples:
        >>> dns_record_name_for_zone("sevn.example.com", "example.com")
        'sevn'
        >>> dns_record_name_for_zone("example.com", "example.com")
        '@'
    """
    host = hostname.strip().lower().rstrip(".")
    zone = zone_name.strip().lower().rstrip(".")
    if host == zone:
        return "@"
    suffix = f".{zone}"
    if host.endswith(suffix):
        return host[: -len(suffix)]
    msg = f"hostname {hostname!r} is not under zone {zone_name!r}"
    raise ValueError(msg)


def _tunnel_name_for_hostname(hostname: str) -> str:
    """Derive a stable Cloudflare tunnel name from a public hostname.

    Args:
        hostname (str): Public hostname.

    Returns:
        str: Account-unique tunnel name prefixed with ``sevn-``.

    Examples:
        >>> _tunnel_name_for_hostname("bot.example.com")
        'sevn-bot-example-com'
    """
    slug = _TUNNEL_NAME_SAFE_RE.sub("-", hostname.strip().lower())
    slug = slug.strip("-") or "sevn"
    return f"sevn-{slug[:48]}"


def _local_service_url(*, gateway_port: int | None, tunnel_config: dict[str, Any]) -> str:
    """Return the local origin URL cloudflared should forward to.

    Args:
        gateway_port (int | None): Explicit gateway port override.
        tunnel_config (dict[str, Any]): Tunnel sub-dict for port coercion.

    Returns:
        str: ``http://127.0.0.1:<port>`` for ingress configuration.

    Examples:
        >>> _local_service_url(gateway_port=3001, tunnel_config={})
        'http://127.0.0.1:3001'
    """
    port = coerce_tunnel_local_port(tunnel_config) if gateway_port is None else gateway_port
    return f"http://127.0.0.1:{port}"


def _api_json(
    client: _HttpClient,
    method: str,
    path: str,
    *,
    api_token: str,
    body: dict[str, Any] | None = None,
) -> Any:
    """Call a Cloudflare API path and return the ``result`` payload.

    Args:
        client (_HttpClient): HTTP client implementation.
        method (str): HTTP method.
        path (str): API path under ``/client/v4``.
        api_token (str): Bearer API token.
        body (dict[str, Any] | None): Optional JSON request body.

    Returns:
        Any: Parsed ``result`` field from a successful response.

    Raises:
        CloudflareApiError: When the response is not successful JSON.

    Examples:
        >>> _api_json  # doctest: +SKIP
    """
    response = client.request(
        method,
        f"{_CF_API_BASE}{path}",
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=60.0,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        msg = f"Cloudflare API returned non-JSON ({response.status_code})"
        raise CloudflareApiError(msg) from exc
    if response.status_code >= 400 or not payload.get("success", False):
        errors = payload.get("errors") or [{"message": response.text}]
        detail = "; ".join(str(err.get("message", err)) for err in errors)
        raise CloudflareApiError(detail or f"Cloudflare API HTTP {response.status_code}")
    return payload.get("result")


def _find_zone_for_hostname(
    client: _HttpClient,
    *,
    account_id: str,
    api_token: str,
    hostname: str,
) -> dict[str, Any]:
    """Resolve the Cloudflare zone that owns ``hostname``.

    Args:
        client (_HttpClient): HTTP client implementation.
        account_id (str): Cloudflare account id.
        api_token (str): Bearer API token.
        hostname (str): Public hostname to publish.

    Returns:
        dict[str, Any]: Matching zone record with ``id`` and ``name``.

    Raises:
        CloudflareApiError: When no zone matches the hostname.

    Examples:
        >>> _find_zone_for_hostname  # doctest: +SKIP
    """
    host = hostname.strip().lower().rstrip(".")
    zones = _api_json(
        client,
        "GET",
        f"/zones?account.id={account_id}&per_page=50",
        api_token=api_token,
    )
    if not isinstance(zones, list):
        msg = "Cloudflare zones lookup returned unexpected payload"
        raise CloudflareApiError(msg)
    matches = [
        zone
        for zone in zones
        if isinstance(zone, dict)
        and (
            host == str(zone.get("name", "")).strip().lower().rstrip(".")
            or host.endswith(f".{str(zone.get('name', '')).strip().lower().rstrip('.')}")
        )
    ]
    if not matches:
        msg = (
            f"no Cloudflare zone found for hostname {hostname!r} — add the domain to your "
            "account first (https://developers.cloudflare.com/tunnel/setup/)"
        )
        raise CloudflareApiError(msg)
    matches.sort(key=lambda zone: len(str(zone.get("name", ""))), reverse=True)
    return matches[0]


def _find_tunnel_by_name(
    client: _HttpClient,
    *,
    account_id: str,
    api_token: str,
    tunnel_name: str,
) -> dict[str, Any] | None:
    """Return an existing tunnel dict when ``tunnel_name`` is already provisioned.

    Args:
        client (_HttpClient): HTTP client implementation.
        account_id (str): Cloudflare account id.
        api_token (str): Bearer API token.
        tunnel_name (str): Tunnel name to look up.

    Returns:
        dict[str, Any] | None: Tunnel record or ``None`` when absent.

    Examples:
        >>> _find_tunnel_by_name  # doctest: +SKIP
    """
    tunnels = _api_json(
        client,
        "GET",
        f"/accounts/{account_id}/cfd_tunnel?name={tunnel_name}&is_deleted=false",
        api_token=api_token,
    )
    if not isinstance(tunnels, list):
        return None
    for tunnel in tunnels:
        if isinstance(tunnel, dict) and str(tunnel.get("name")) == tunnel_name:
            return tunnel
    return None


def _create_or_reuse_tunnel(
    client: _HttpClient,
    *,
    account_id: str,
    api_token: str,
    tunnel_name: str,
) -> tuple[str, str]:
    """Create a remote-managed tunnel or reuse an existing one by name.

    Args:
        client (_HttpClient): HTTP client implementation.
        account_id (str): Cloudflare account id.
        api_token (str): Bearer API token.
        tunnel_name (str): Desired tunnel name.

    Returns:
        tuple[str, str]: ``(tunnel_id, connector_token)``.

    Raises:
        CloudflareApiError: When create/token fetch does not return credentials.

    Examples:
        >>> _create_or_reuse_tunnel  # doctest: +SKIP
    """
    existing = _find_tunnel_by_name(
        client,
        account_id=account_id,
        api_token=api_token,
        tunnel_name=tunnel_name,
    )
    if existing and existing.get("id"):
        tunnel_id = str(existing["id"])
        token_result = _api_json(
            client,
            "POST",
            f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token",
            api_token=api_token,
        )
        token = str((token_result or {}).get("token") or "").strip()
        if not token:
            msg = f"Cloudflare did not return a connector token for tunnel {tunnel_id}"
            raise CloudflareApiError(msg)
        return tunnel_id, token

    created = _api_json(
        client,
        "POST",
        f"/accounts/{account_id}/cfd_tunnel",
        api_token=api_token,
        body={"name": tunnel_name, "config_src": "cloudflare"},
    )
    if not isinstance(created, dict):
        msg = "Cloudflare tunnel create returned unexpected payload"
        raise CloudflareApiError(msg)
    tunnel_id = str(created.get("id") or "").strip()
    token = str(created.get("token") or "").strip()
    if not tunnel_id or not token:
        msg = "Cloudflare tunnel create did not return id and token"
        raise CloudflareApiError(msg)
    return tunnel_id, token


def _put_tunnel_ingress(
    client: _HttpClient,
    *,
    account_id: str,
    api_token: str,
    tunnel_id: str,
    hostname: str,
    service_url: str,
) -> None:
    """Publish ingress rules that route ``hostname`` to the local gateway.

    Args:
        client (_HttpClient): Cloudflare API HTTP client.
        account_id (str): Cloudflare account id.
        api_token (str): API token with tunnel write permission.
        tunnel_id (str): Cloudflare tunnel UUID.
        hostname (str): Public hostname for Mission Control.
        service_url (str): Local origin URL (e.g. ``http://127.0.0.1:3001``).

    Examples:
        >>> _put_tunnel_ingress  # doctest: +SKIP
    """
    _api_json(
        client,
        "PUT",
        f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
        api_token=api_token,
        body={
            "config": {
                "ingress": [
                    {"hostname": hostname, "service": service_url, "originRequest": {}},
                    {"service": "http_status:404"},
                ]
            }
        },
    )


def _ensure_dns_cname(
    client: _HttpClient,
    *,
    zone_id: str,
    api_token: str,
    hostname: str,
    zone_name: str,
    tunnel_id: str,
) -> None:
    """Create or update the proxied CNAME that points ``hostname`` at the tunnel.

    Args:
        client (_HttpClient): Cloudflare API HTTP client.
        zone_id (str): Cloudflare zone id for the hostname domain.
        api_token (str): API token with DNS write permission.
        hostname (str): Full public hostname.
        zone_name (str): Zone apex name (e.g. ``example.com``).
        tunnel_id (str): Cloudflare tunnel UUID.

    Examples:
        >>> _ensure_dns_cname  # doctest: +SKIP
    """
    record_name = dns_record_name_for_zone(hostname, zone_name)
    target = f"{tunnel_id}.cfargotunnel.com"
    existing = _api_json(
        client,
        "GET",
        f"/zones/{zone_id}/dns_records?type=CNAME&name={hostname}",
        api_token=api_token,
    )
    records = existing if isinstance(existing, list) else []
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("content", "")).strip() == target:
            return
        record_id = str(record.get("id") or "").strip()
        if record_id:
            _api_json(
                client,
                "PUT",
                f"/zones/{zone_id}/dns_records/{record_id}",
                api_token=api_token,
                body={
                    "type": "CNAME",
                    "proxied": True,
                    "name": record_name,
                    "content": target,
                },
            )
            return
    _api_json(
        client,
        "POST",
        f"/zones/{zone_id}/dns_records",
        api_token=api_token,
        body={
            "type": "CNAME",
            "proxied": True,
            "name": record_name,
            "content": target,
        },
    )


def provision_cloudflare_tunnel(
    *,
    account_id: str,
    api_token: str,
    hostname: str,
    gateway_port: int | None = None,
    tunnel_config: dict[str, Any] | None = None,
    client: _HttpClient | None = None,
) -> CloudflareTunnelProvisionResult:
    """Provision a remote-managed Cloudflare tunnel and publish ``hostname``.

    Implements the API steps from Cloudflare's tunnel setup guide: create (or reuse)
    a tunnel, configure ingress to the local gateway, and create the DNS CNAME.

    Args:
        account_id (str): Cloudflare account id.
        api_token (str): API token with Tunnel + DNS write permissions.
        hostname (str): Public hostname to publish (for example ``sevn.example.com``).
        gateway_port (int | None): Local gateway port when not in ``tunnel_config``.
        tunnel_config (dict[str, Any] | None): Optional tunnel sub-dict for port coercion.
        client (_HttpClient | None): Injectable HTTP client for tests.

    Returns:
        CloudflareTunnelProvisionResult: Tunnel credentials and public URL metadata.

    Raises:
        CloudflareApiError: When the Cloudflare API rejects a step.
        ValueError: When required inputs are empty.

    Examples:
        >>> provision_cloudflare_tunnel  # doctest: +SKIP
    """
    acct = account_id.strip()
    token = api_token.strip()
    host = hostname.strip().lower()
    if not acct:
        msg = "account_id is required"
        raise ValueError(msg)
    if not token:
        msg = "api_token is required"
        raise ValueError(msg)
    if not host or "." not in host:
        msg = "hostname must be a FQDN like sevn.example.com"
        raise ValueError(msg)

    http = client or httpx.Client()
    owns_client = client is None
    try:
        zone = _find_zone_for_hostname(http, account_id=acct, api_token=token, hostname=host)
        zone_id = str(zone.get("id") or "").strip()
        zone_name = str(zone.get("name") or "").strip()
        if not zone_id or not zone_name:
            msg = "Cloudflare zone lookup did not return id/name"
            raise CloudflareApiError(msg)

        tunnel_name = _tunnel_name_for_hostname(host)
        tunnel_id, tunnel_token = _create_or_reuse_tunnel(
            http,
            account_id=acct,
            api_token=token,
            tunnel_name=tunnel_name,
        )
        service_url = _local_service_url(
            gateway_port=gateway_port,
            tunnel_config=tunnel_config or {},
        )
        _put_tunnel_ingress(
            http,
            account_id=acct,
            api_token=token,
            tunnel_id=tunnel_id,
            hostname=host,
            service_url=service_url,
        )
        _ensure_dns_cname(
            http,
            zone_id=zone_id,
            api_token=token,
            hostname=host,
            zone_name=zone_name,
            tunnel_id=tunnel_id,
        )
    finally:
        if owns_client and isinstance(http, httpx.Client):
            http.close()

    public_url = tunnel_mission_control_url(host)
    if public_url is None:
        msg = "failed to derive public URL"
        raise CloudflareApiError(msg)
    return CloudflareTunnelProvisionResult(
        tunnel_id=tunnel_id,
        tunnel_token=tunnel_token,
        hostname=host,
        public_url=public_url,
        zone_id=zone_id,
        tunnel_name=tunnel_name,
    )


def normalize_public_hostname(value: str) -> str:
    """Normalize a public hostname, rejecting URLs with paths.

    Args:
        value (str): Hostname or accidental URL paste.

    Returns:
        str: Lowercased hostname without scheme or path.

    Raises:
        ValueError: When the value is empty or not a hostname.

    Examples:
        >>> normalize_public_hostname("https://Sevn.Example.com/path")
        'sevn.example.com'
    """
    raw = value.strip()
    if "://" in raw:
        parsed = urlparse(raw)
        raw = parsed.hostname or ""
    raw = raw.split("/", 1)[0].strip().lower()
    if not raw or "." not in raw:
        msg = "hostname must look like sevn.example.com"
        raise ValueError(msg)
    return raw


__all__ = [
    "CloudflareApiError",
    "CloudflareTunnelProvisionResult",
    "dns_record_name_for_zone",
    "normalize_public_hostname",
    "provision_cloudflare_tunnel",
    "tunnel_mission_control_url",
]
