"""Discogs OAuth 1.0a handshake helpers for Telegram setup (D20).

Module: sevn.integrations.discogs.oauth
Depends: discogs_client (optional ``[discogs]`` extra)

Exports:
    DiscogsOAuthError — safe operator-facing OAuth failure.
    begin_oauth — obtain request token pair and authorize URL.
    complete_oauth — exchange verifier for access token pair.

Examples:
    >>> from sevn.integrations.discogs.oauth import DiscogsOAuthError
    >>> err = DiscogsOAuthError("bad verifier")
    >>> err.message
    'bad verifier'
"""

from __future__ import annotations

try:
    import discogs_client
    from discogs_client.exceptions import AuthorizationError, HTTPError
except ImportError:  # pragma: no cover - optional [discogs] extra
    discogs_client = None
    AuthorizationError = Exception
    HTTPError = Exception

_DEFAULT_USER_AGENT = "sevn-discogs/1.0"

__all__ = [
    "DiscogsOAuthError",
    "begin_oauth",
    "complete_oauth",
]


class DiscogsOAuthError(Exception):
    """OAuth handshake failure with a safe operator message."""

    def __init__(self, message: str) -> None:
        """Store the operator-safe failure text.

        Args:
            message (str): Error description without secrets.

        Examples:
            >>> DiscogsOAuthError("nope").message
            'nope'
        """
        self.message = message
        super().__init__(message)


def begin_oauth(
    consumer_key: str,
    consumer_secret: str,
    user_agent: str,
) -> tuple[str, str, str]:
    """Start OAuth 1.0a and return request credentials plus authorize URL.

    Args:
        consumer_key (str): Discogs application consumer key.
        consumer_secret (str): Discogs application consumer secret.
        user_agent (str): User-Agent header value for API calls.

    Returns:
        tuple[str, str, str]: ``(request_token, request_secret, authorize_url)``.

    Raises:
        DiscogsOAuthError: When the optional extra is missing or request token fails.

    Examples:
        >>> begin_oauth.__name__
        'begin_oauth'
    """
    if discogs_client is None:
        raise DiscogsOAuthError(
            "discogs extra not installed: run 'uv sync --extra discogs'",
        )

    key = consumer_key.strip()
    secret = consumer_secret.strip()
    if not key or not secret:
        raise DiscogsOAuthError("Consumer key and secret are required.")

    client = discogs_client.Client(
        user_agent.strip() or _DEFAULT_USER_AGENT,
        consumer_key=key,
        consumer_secret=secret,
    )
    try:
        result = client.get_authorize_url()
    except AuthorizationError as exc:
        raise DiscogsOAuthError(
            "Could not get OAuth request token — check consumer credentials.",
        ) from exc

    if not isinstance(result, tuple) or len(result) != 3:
        raise DiscogsOAuthError("Unexpected authorize URL response from Discogs.")

    request_token, request_secret, authorize_url = result
    url = str(authorize_url)
    if url.startswith("?"):
        url = f"https://www.discogs.com/oauth/authorize{url}"
    elif not url.startswith("http"):
        url = f"https://www.discogs.com{url}"
    return str(request_token), str(request_secret), url


def complete_oauth(
    consumer_key: str,
    consumer_secret: str,
    request_token: str,
    request_secret: str,
    verifier: str,
    user_agent: str,
) -> tuple[str, str]:
    """Exchange a verifier for OAuth access credentials.

    Args:
        consumer_key (str): Discogs application consumer key.
        consumer_secret (str): Discogs application consumer secret.
        request_token (str): Request token from :func:`begin_oauth`.
        request_secret (str): Request secret from :func:`begin_oauth`.
        verifier (str): Verifier pasted by the operator after authorization.
        user_agent (str): User-Agent header value for API calls.

    Returns:
        tuple[str, str]: ``(access_token, access_token_secret)``.

    Raises:
        DiscogsOAuthError: When the optional extra is missing or token exchange fails.

    Examples:
        >>> complete_oauth.__name__
        'complete_oauth'
    """
    if discogs_client is None:
        raise DiscogsOAuthError(
            "discogs extra not installed: run 'uv sync --extra discogs'",
        )

    key = consumer_key.strip()
    secret = consumer_secret.strip()
    token = request_token.strip()
    req_secret = request_secret.strip()
    code = verifier.strip()
    if not all((key, secret, token, req_secret, code)):
        raise DiscogsOAuthError("Consumer credentials, request token, and verifier are required.")

    client = discogs_client.Client(
        user_agent.strip() or _DEFAULT_USER_AGENT,
        consumer_key=key,
        consumer_secret=secret,
        token=token,
        secret=req_secret,
    )
    try:
        access_token, access_secret = client.get_access_token(code)
    except HTTPError as exc:
        raise DiscogsOAuthError(
            "Could not exchange verifier for access token — check the verifier and retry.",
        ) from exc

    return str(access_token), str(access_secret)
