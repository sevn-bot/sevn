"""Codex OAuth Responses transport helpers (W3.2 — D1/D7).

Module: sevn.proxy.codex_transport
Depends: sevn.security.oauth.constants

Exports:
    codex_responses_url — full upstream URL for Codex Responses.
    build_codex_request_headers — subscription headers for Codex OAuth egress.
"""

from __future__ import annotations

from sevn.security.oauth.constants import (
    CODEX_OAUTH_ORIGINATOR,
    CODEX_RESPONSES_BASE_URL,
    CODEX_RESPONSES_PATH,
)

_DROPPED_INBOUND_HEADERS: frozenset[str] = frozenset(
    {
        # Auth — never forward the client's OpenAI key to the Codex upstream.
        "x-api-key",
        # Framing — the body is re-serialized into the Responses schema; a stale
        # inbound content-length corrupts h11 framing (LocalProtocolError 500).
        "host",
        "content-length",
        "content-encoding",
        "transfer-encoding",
        # Hop-by-hop headers (RFC 7230 §6.1) — meaningful only for the inbound hop.
        "connection",
        "keep-alive",
        "accept-encoding",
        "te",
        "trailer",
        "upgrade",
        "proxy-authorization",
        "proxy-connection",
    }
)
"""Inbound header names (lower-case) never forwarded to the Codex upstream.

Combines the OAuth key strip (``x-api-key``) with HTTP framing / hop-by-hop
headers. ``host`` and ``content-length`` are the fatal pair: httpx derives both
from the URL and the serialized body, so forwarding the client's values breaks
the upstream request framing.
"""


def codex_responses_url() -> str:
    """Return the Codex Responses upstream URL (D7).

    Returns:
        str: ``https://chatgpt.com/backend-api/codex/responses``.

    Examples:
        >>> codex_responses_url()
        'https://chatgpt.com/backend-api/codex/responses'
    """
    return f"{CODEX_RESPONSES_BASE_URL}{CODEX_RESPONSES_PATH}"


def build_codex_request_headers(
    *,
    access_token: str,
    account_id: str,
    incoming: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build Codex subscription headers, stripping framing/hop-by-hop inbound headers (D1).

    Inbound client headers are merged only when they are neither already set by
    this builder nor in :data:`_DROPPED_INBOUND_HEADERS`. The dropped set covers
    ``x-api-key`` (auth leak) plus framing/hop-by-hop headers such as ``host`` and
    ``content-length``: the body is re-serialized into the Responses schema, so a
    forwarded inbound ``content-length`` no longer matches and h11 raises
    ``LocalProtocolError`` (HTTP 500). httpx recomputes ``host``/``content-length``
    from the URL and serialized body.

    Args:
        access_token (str): OAuth access token (JWT).
        account_id (str): ChatGPT account id from the credential blob.
        incoming (dict[str, str] | None): Optional client headers to merge, minus
            framing/hop-by-hop headers (see :data:`_DROPPED_INBOUND_HEADERS`).

    Returns:
        dict[str, str]: Headers for Codex Responses POST.

    Examples:
        >>> hdrs = build_codex_request_headers(
        ...     access_token="jwt",
        ...     account_id="acct-1",
        ...     incoming={"x-api-key": "drop-me", "host": "127.0.0.1:8787", "content-length": "285"},
        ... )
        >>> hdrs["authorization"]
        'Bearer jwt'
        >>> any(k.lower() in {"x-api-key", "host", "content-length"} for k in hdrs)
        False
    """
    headers: dict[str, str] = {
        "authorization": f"Bearer {access_token}",
        "chatgpt-account-id": account_id,
        "OpenAI-Beta": "responses=experimental",
        "originator": CODEX_OAUTH_ORIGINATOR,
        "accept": "text/event-stream",
        "content-type": "application/json",
    }
    if incoming:
        existing = {k.lower() for k in headers}
        for key, value in incoming.items():
            lower = key.lower()
            if lower in _DROPPED_INBOUND_HEADERS or lower in existing:
                continue
            headers[key] = value
    return headers


__all__ = [
    "build_codex_request_headers",
    "codex_responses_url",
]
