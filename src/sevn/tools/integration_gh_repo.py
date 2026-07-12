"""Legacy ``gh_repo_*`` aliases mapped to :func:`integration_call` payloads (`specs/11-tools-registry.md` §4.1).

v1 does **not** register standalone GitHub thin tools in the merged catalog. GitHub REST access
flows through ``integration_call`` with ``service=\"github\"`` and REST-shaped ``method`` /
``args`` routed by the egress proxy when integration dispatch is enabled.

Module: sevn.tools.integration_gh_repo
Depends: typing

Exports:
    legacy_gh_repo_integration_kwargs — map historic ``gh_repo_*`` names to ``integration_call`` kwargs.

Examples:
    >>> from sevn.tools.integration_gh_repo import legacy_gh_repo_integration_kwargs
    >>> legacy_gh_repo_integration_kwargs("gh_repo_get", args={"owner": "a", "repo": "b"})
    {'service': 'github', 'method': 'repos.get', 'args': {'owner': 'a', 'repo': 'b'}}
    >>> legacy_gh_repo_integration_kwargs("unknown", args={}) is None
    True
"""

from __future__ import annotations

from typing import Any, Final

GITHUB_INTEGRATION_SERVICE: Final[str] = "github"

_LEGACY_GH_REPO_METHODS: Final[dict[str, tuple[str, str]]] = {
    "gh_repo_get": (GITHUB_INTEGRATION_SERVICE, "repos.get"),
    "gh_repo_list_issues": (GITHUB_INTEGRATION_SERVICE, "issues.list_for_repo"),
    "gh_repo_create_issue": (GITHUB_INTEGRATION_SERVICE, "issues.create"),
}


def legacy_gh_repo_integration_kwargs(
    tool_name: str,
    *,
    args: dict[str, Any],
) -> dict[str, Any] | None:
    """Translate a deprecated ``gh_repo_*`` name into ``integration_call`` keyword arguments.

    Args:
        tool_name (str): Historic thin-tool name.
        args (dict[str, Any]): Payload forwarded as the integration ``args`` object.

    Returns:
        dict[str, Any] | None: ``{\"service\", \"method\", \"args\"}`` when ``tool_name`` matches
            a bundled alias; otherwise ``None``.

    Examples:
        >>> legacy_gh_repo_integration_kwargs(
        ...     "gh_repo_list_issues", args={"owner": "o", "repo": "r"}
        ... )["method"]
        'issues.list_for_repo'
    """

    pair = _LEGACY_GH_REPO_METHODS.get(tool_name)
    if pair is None:
        return None
    service, method = pair
    return {"service": service, "method": method, "args": dict(args)}


__all__ = [
    "GITHUB_INTEGRATION_SERVICE",
    "legacy_gh_repo_integration_kwargs",
]
