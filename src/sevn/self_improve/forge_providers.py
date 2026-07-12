"""Self-improve forge adapters (`specs/33-self-improvement.md` §11).

Exports:
    forge_api_base — REST base URL for github/gitlab/forgejo.
"""

from __future__ import annotations

from typing import Literal

ForgeProvider = Literal["github", "gitlab", "forgejo"]


def forge_api_base(provider: ForgeProvider, *, host: str | None = None) -> str:
    """Return the REST API base for a forge provider.

    Args:
        provider (ForgeProvider): Hub provider id from ``sevn.json``.
        host (str | None, optional): Self-hosted hostname for GitLab/Forgejo.

    Returns:
        str: API origin without trailing slash.

    Examples:
        >>> forge_api_base("github")
        'https://api.github.com'
        >>> forge_api_base("gitlab", host="gitlab.example.com")
        'https://gitlab.example.com/api/v4'
    """
    if provider == "github":
        return "https://api.github.com"
    if provider == "gitlab":
        base = (host or "gitlab.com").strip().rstrip("/")
        return f"https://{base}/api/v4"
    base = (host or "codeberg.org").strip().rstrip("/")
    return f"https://{base}/api/v1"


__all__ = ["ForgeProvider", "forge_api_base"]
