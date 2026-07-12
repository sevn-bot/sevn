"""Workspace backup GitHub repo creation for onboarding (`plan/onboarding-comprehensive-setup` W4, D7).

Module: sevn.onboarding.workspace_backup
Depends: httpx, re, asyncio, subprocess

Exports:
    sanitize_repo_name — GitHub-safe repository slug.
    default_backup_repo_name — ``{login}.mysevnbackup`` default.
    create_github_repo_via_api — ``POST /user/repos`` (private default).
    create_repo_via_gh_cli — optional ``gh repo create`` fallback.
    create_workspace_backup_repo — API first, optional ``gh`` fallback.
    repo_url_from_api_response — extract html_url from create response.
    resolve_backup_default_name — default slug from authenticated user.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from typing import Any

import httpx

from sevn.onboarding.github_oauth import fetch_github_user

_REPO_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_GITHUB_API_VERSION = "2022-11-28"
_MAX_REPO_NAME_LEN = 100


def sanitize_repo_name(name: str) -> str:
    """Normalize a repository name for GitHub ``POST /user/repos``.

    Args:
        name (str): Operator-provided repo name (may include dots).

    Returns:
        str: Lowercased slug with invalid characters replaced by hyphens.

    Raises:
        ValueError: When the sanitized name is empty.

    Examples:
        >>> sanitize_repo_name("Alex.MySevnBackup")
        'alex.mysevnbackup'
        >>> sanitize_repo_name("bad name!!")
        'bad-name'
    """
    text = str(name).strip().lower()
    text = _REPO_NAME_RE.sub("-", text)
    text = text.strip("-._")
    if not text:
        msg = "repository name is empty after sanitization"
        raise ValueError(msg)
    if len(text) > _MAX_REPO_NAME_LEN:
        text = text[:_MAX_REPO_NAME_LEN].rstrip("-._")
    if not text:
        msg = "repository name is empty after truncation"
        raise ValueError(msg)
    return text


def default_backup_repo_name(github_login: str) -> str:
    """Return the default private backup repo name for an operator login.

    Args:
        github_login (str): GitHub username from ``GET /user``.

    Returns:
        str: ``{login}.mysevnbackup`` after :func:`sanitize_repo_name`.

    Examples:
        >>> default_backup_repo_name("octocat")
        'octocat.mysevnbackup'
    """
    login = str(github_login).strip()
    return sanitize_repo_name(f"{login}.mysevnbackup")


async def create_github_repo_via_api(
    token: str,
    name: str,
    *,
    private: bool = True,
    description: str = "sevn.bot workspace backup",
) -> dict[str, Any]:
    """Create a repository via GitHub REST ``POST /user/repos``.

    Args:
        token (str): OAuth or PAT with ``repo`` scope.
        name (str): Repository name (sanitized by caller).
        private (bool, optional): Create a private repo. Defaults to True.
        description (str, optional): Repo description. Defaults to workspace backup text.

    Returns:
        dict[str, Any]: GitHub repository JSON (includes ``html_url``).

    Raises:
        httpx.HTTPStatusError: When GitHub rejects the request.

    Examples:
        >>> import asyncio
        >>> async def _demo():
        ...     try:
        ...         await create_github_repo_via_api("bad", "x")
        ...     except Exception:
        ...         return True
        ...     return False
        >>> asyncio.run(_demo())
        True
    """
    slug = sanitize_repo_name(name)
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token.strip()}",
        "X-GitHub-Api-Version": _GITHUB_API_VERSION,
    }
    body = {
        "name": slug,
        "private": private,
        "description": description,
        "auto_init": False,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post("https://api.github.com/user/repos", headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        msg = "GitHub create repo returned non-object JSON"
        raise ValueError(msg)
    return data


async def create_repo_via_gh_cli(
    name: str,
    *,
    private: bool = True,
) -> str | None:
    """Create a repository using the ``gh`` CLI when it is on PATH.

    Args:
        name (str): Repository name (sanitized).
        private (bool, optional): Pass ``--private`` when True. Defaults to True.

    Returns:
        str | None: ``https://github.com/{owner}/{repo}`` when ``gh`` succeeds, else ``None``.

    Examples:
        >>> import asyncio
        >>> asyncio.run(create_repo_via_gh_cli("nonexistent-repo-xyz-12345")) is None
        True
    """
    if shutil.which("gh") is None:
        return None
    slug = sanitize_repo_name(name)
    cmd = [
        "gh",
        "repo",
        "create",
        slug,
        "--json",
        "url",
        "-q",
        ".url",
    ]
    if private:
        cmd.insert(4, "--private")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, _stderr_b = await proc.communicate()
    if proc.returncode != 0:
        return None
    url = (stdout_b or b"").decode("utf-8", errors="replace").strip()
    return url or None


def repo_url_from_api_response(data: dict[str, Any]) -> str:
    """Extract a canonical ``html_url`` from a GitHub create-repo response.

    Args:
        data (dict[str, Any]): GitHub repository JSON.

    Returns:
        str: Full ``https://github.com/{owner}/{repo}`` URL.

    Raises:
        ValueError: When required fields are missing.

    Examples:
        >>> repo_url_from_api_response(
        ...     {"html_url": "https://github.com/octocat/demo", "name": "demo"}
        ... )
        'https://github.com/octocat/demo'
    """
    html = data.get("html_url")
    if isinstance(html, str) and html.strip().startswith("https://github.com/"):
        return html.strip()
    owner = data.get("full_name")
    if isinstance(owner, str) and "/" in owner:
        return f"https://github.com/{owner.strip()}"
    name = data.get("name")
    owner_obj = data.get("owner")
    if isinstance(name, str) and isinstance(owner_obj, dict):
        login = owner_obj.get("login")
        if isinstance(login, str) and login.strip():
            return f"https://github.com/{login.strip()}/{name.strip()}"
    msg = "GitHub create repo response missing html_url"
    raise ValueError(msg)


async def create_workspace_backup_repo(
    token: str,
    name: str,
    *,
    private: bool = True,
    try_gh_cli: bool = True,
) -> str:
    """Create a workspace backup repository and return its canonical URL.

    Tries GitHub REST first; optionally falls back to ``gh repo create`` when the
    API call fails and ``gh`` is on PATH.

    Args:
        token (str): OAuth or PAT bearer token.
        name (str): Desired repository name.
        private (bool, optional): Private repo. Defaults to True.
        try_gh_cli (bool, optional): Attempt ``gh`` fallback. Defaults to True.

    Returns:
        str: Full GitHub repository URL.

    Raises:
        ValueError: When both API and CLI creation fail.
        httpx.HTTPStatusError: When API fails and CLI fallback is disabled or unavailable.

    Examples:
        >>> import asyncio
        >>> async def _demo():
        ...     try:
        ...         await create_workspace_backup_repo("bad", "x", try_gh_cli=False)
        ...     except Exception:
        ...         return True
        ...     return False
        >>> asyncio.run(_demo())
        True
    """
    slug = sanitize_repo_name(name)
    try:
        data = await create_github_repo_via_api(token, slug, private=private)
        return repo_url_from_api_response(data)
    except httpx.HTTPStatusError:
        if not try_gh_cli:
            raise
        cli_url = await create_repo_via_gh_cli(slug, private=private)
        if cli_url:
            return cli_url
        raise
    except httpx.HTTPError as exc:
        if try_gh_cli:
            cli_url = await create_repo_via_gh_cli(slug, private=private)
            if cli_url:
                return cli_url
        msg = f"GitHub repo create failed: {exc}"
        raise ValueError(msg) from exc


async def resolve_backup_default_name(token: str) -> str:
    """Return the default backup repo slug for the authenticated GitHub user.

    Args:
        token (str): Valid GitHub bearer token.

    Returns:
        str: Sanitized ``{login}.mysevnbackup`` name.

    Examples:
        >>> import asyncio
        >>> async def _demo():
        ...     try:
        ...         await resolve_backup_default_name("bad")
        ...     except Exception:
        ...         return True
        ...     return False
        >>> asyncio.run(_demo())
        True
    """
    user = await fetch_github_user(token)
    login = user.get("login")
    if not isinstance(login, str) or not login.strip():
        msg = "GitHub /user response missing login"
        raise ValueError(msg)
    return default_backup_repo_name(login)


__all__ = [
    "create_github_repo_via_api",
    "create_repo_via_gh_cli",
    "create_workspace_backup_repo",
    "default_backup_repo_name",
    "repo_url_from_api_response",
    "resolve_backup_default_name",
    "sanitize_repo_name",
]
