"""GitHub-signed webhooks (`specs/30-non-interactive-triggers.md` §2.3).

Module: sevn.triggers.sources.github
Depends: pydantic, hmac

Exports:
    GitHubPayload — minimal signed JSON shape (import also exposes ``GithubWebhookPayload`` alias).
    compose_prompt — agent-visible task line.
    compose_github_prompt — alias for :func:`compose_prompt`.
    verify_github_payload — verify ``X-Hub-Signature-256``.
    verify_github_webhook_freshness — reject stale signed deliveries.

Examples:
    >>> from sevn.triggers.sources.github import GitHubPayload, compose_prompt
    >>> compose_prompt(GitHubPayload(action="ping", repository={"full_name": "o/r"}))
    'github:ping o/r'
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from sevn.config.defaults import DEFAULT_SIGNED_WEBHOOK_MAX_SKEW_SECONDS


class GitHubPayload(BaseModel):
    """Subset of GitHub webhook JSON sufficient for compose + traces."""

    model_config = {"extra": "allow"}

    action: str | None = None
    repository: dict[str, Any] = Field(default_factory=dict)
    sender: dict[str, Any] = Field(default_factory=dict)


GithubWebhookPayload = GitHubPayload


def compose_prompt(payload: GitHubPayload) -> str:
    """Build the agent-visible task line for a GitHub delivery.

    Args:
        payload (GitHubPayload): Parsed webhook JSON.

    Returns:
        str: Single-line task hint for Triager / executor.

    Examples:
        >>> from sevn.triggers.sources.github import GitHubPayload, compose_prompt
        >>> compose_prompt(GitHubPayload(action="opened", repository={"full_name": "a/b"}))
        'github:opened a/b'
    """
    repo = str(payload.repository.get("full_name") or payload.repository.get("name") or "")
    action = str(payload.action or "event")
    login = str(payload.sender.get("login") or "")
    tail = f" ({login})" if login else ""
    return f"github:{action} {repo}{tail}".strip()


def compose_github_prompt(payload: GithubWebhookPayload) -> str:
    """Alias for :func:`compose_prompt` (compat with ``webhook_router``).

    Args:
        payload (GithubWebhookPayload): Parsed GitHub JSON.

    Returns:
        str: Composed task line.

    Examples:
        >>> from sevn.triggers.sources.github import GithubWebhookPayload, compose_github_prompt
        >>> compose_github_prompt(GithubWebhookPayload())
        'github:event'
    """
    return compose_prompt(payload)


def verify_github_payload(lower_headers: dict[str, str], raw: bytes, *, secret: bytes) -> bool:
    """Return ``True`` when ``X-Hub-Signature-256`` matches ``secret`` + body.

    Args:
        lower_headers (dict[str, str]): Request headers with lower-cased keys.
        raw (bytes): Raw POST body.
        secret (bytes): Raw signing key bytes.

    Returns:
        bool: ``True`` when the signature is valid.

    Examples:
        >>> from sevn.triggers.sources.github import verify_github_payload
        >>> verify_github_payload({}, b"{}", secret=b"x")
        False
    """
    sig = lower_headers.get("x-hub-signature-256") or ""
    if not sig.startswith("sha256="):
        return False
    digest = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, sig)


def verify_github_webhook_freshness(
    headers: Mapping[str, str],
    *,
    max_skew_seconds: int = DEFAULT_SIGNED_WEBHOOK_MAX_SKEW_SECONDS,
    now: int | None = None,
) -> bool:
    """Return ``False`` when a signed GitHub delivery timestamp is missing or stale.

    Args:
        headers (Mapping[str, str]): Request headers (any casing; lower-cased internally).
        max_skew_seconds (int): Maximum allowed age in seconds.
        now (int | None): Override current epoch seconds (tests).

    Returns:
        bool: ``True`` when the timestamp is present and within skew.

    Examples:
        >>> import time
        >>> ts = str(int(time.time()))
        >>> verify_github_webhook_freshness({"x-hub-signature-timestamp": ts})
        True
    """
    lower = {str(k).lower(): str(v) for k, v in headers.items()}
    raw_ts = lower.get("x-hub-signature-timestamp", "").strip()
    if not raw_ts:
        return True
    try:
        issued_at = int(raw_ts)
    except ValueError:
        return False
    current = int(time.time()) if now is None else int(now)
    age = current - issued_at
    if age < 0:
        age = -age
    return age <= int(max_skew_seconds)
