"""Thin ``httpx`` helpers shared by API-based ``job-ops`` extractors.

Module: job-ops/scripts/lib/httpclient.py
"""

from __future__ import annotations

from typing import Any

import httpx

USER_AGENT = "Mozilla/5.0 (compatible; sevn-job-ops/0.1)"
DEFAULT_TIMEOUT = 20.0

HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
JSON_ACCEPT = "application/json"


class ChallengeError(RuntimeError):
    """Raised when a board returns an anti-bot challenge instead of data."""

    def __init__(self, url: str) -> None:
        """Store the challenge URL the operator must solve headed."""
        super().__init__(f"challenge required at {url}")
        self.url = url


def get_text(
    url: str, *, headers: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT
) -> str:
    """GET ``url`` and return the response body text.

    Args:
        url (str): Target URL.
        headers (dict[str, str] | None): Extra request headers.
        timeout (float): Per-request timeout in seconds.

    Returns:
        str: Response body.
    """
    hdrs = {"user-agent": USER_AGENT, "accept": HTML_ACCEPT}
    if headers:
        hdrs.update(headers)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers=hdrs)
        resp.raise_for_status()
        return resp.text


def get_json(
    url: str, *, headers: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT
) -> Any:
    """GET ``url`` and parse a JSON response body."""
    hdrs = {"user-agent": USER_AGENT, "accept": JSON_ACCEPT}
    if headers:
        hdrs.update(headers)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers=hdrs)
        resp.raise_for_status()
        return resp.json()


def post_json(
    url: str,
    *,
    json_body: Any,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """POST ``json_body`` to ``url`` and parse a JSON response body."""
    hdrs = {"user-agent": USER_AGENT, "accept": JSON_ACCEPT, "content-type": JSON_ACCEPT}
    if headers:
        hdrs.update(headers)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.post(url, json=json_body, headers=hdrs)
        resp.raise_for_status()
        return resp.json()
