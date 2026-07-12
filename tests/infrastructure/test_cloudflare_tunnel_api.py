"""Tests for Cloudflare Tunnel API provisioning."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from sevn.infrastructure.cloudflare_tunnel_api import (
    CloudflareApiError,
    dns_record_name_for_zone,
    normalize_public_hostname,
    provision_cloudflare_tunnel,
)


class _FakeClient:
    """Minimal HTTP client stub for Cloudflare API tests."""

    def __init__(self, handlers: dict[tuple[str, str], Any]) -> None:
        self.handlers = handlers
        self.calls: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        _ = headers, json, timeout
        path = url.replace("https://api.cloudflare.com/client/v4", "")
        self.calls.append((method, path))
        payload = self.handlers[(method, path)]
        return httpx.Response(200, json={"success": True, "result": payload})

    def close(self) -> None:
        return None


def test_dns_record_name_for_zone_subdomain() -> None:
    assert dns_record_name_for_zone("sevn.example.com", "example.com") == "sevn"


def test_normalize_public_hostname_strips_url() -> None:
    assert normalize_public_hostname("https://Sevn.Example.com/app") == "sevn.example.com"


def test_provision_cloudflare_tunnel_happy_path() -> None:
    handlers: dict[tuple[str, str], Any] = {
        ("GET", "/zones?account.id=acct&per_page=50"): [{"id": "zone123", "name": "example.com"}],
        ("GET", "/accounts/acct/cfd_tunnel?name=sevn-sevn-example-com&is_deleted=false"): [],
        ("POST", "/accounts/acct/cfd_tunnel"): {
            "id": "tunnel-uuid",
            "token": "connector-token",
        },
        ("PUT", "/accounts/acct/cfd_tunnel/tunnel-uuid/configurations"): {},
        ("GET", "/zones/zone123/dns_records?type=CNAME&name=sevn.example.com"): [],
        ("POST", "/zones/zone123/dns_records"): {"id": "dns1"},
    }
    client = _FakeClient(handlers)
    result = provision_cloudflare_tunnel(
        account_id="acct",
        api_token="api-token",
        hostname="sevn.example.com",
        gateway_port=3001,
        client=client,
    )
    assert result.tunnel_id == "tunnel-uuid"
    assert result.tunnel_token == "connector-token"
    assert result.public_url == "https://sevn.example.com/"
    assert ("POST", "/accounts/acct/cfd_tunnel") in client.calls


def test_provision_cloudflare_tunnel_missing_zone_raises() -> None:
    client = _FakeClient({("GET", "/zones?account.id=acct&per_page=50"): []})
    with pytest.raises(CloudflareApiError, match="no Cloudflare zone"):
        provision_cloudflare_tunnel(
            account_id="acct",
            api_token="api-token",
            hostname="sevn.example.com",
            client=client,
        )
