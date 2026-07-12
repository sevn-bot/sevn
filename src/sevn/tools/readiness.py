"""Tool readiness hints for registry surfaces and error envelopes (Wave W6 / W1).

Module: sevn.tools.readiness
Depends: typing

Exports:
    readiness_for_tool — readiness row for a registry tool name (or ``None``).
    readiness_notes_for_tools — map of tool name → one-line readiness note.
    set_tool_readiness_override — gateway-boot patch for scaffolding tool rows.

Examples:
    >>> row = readiness_for_tool("serp")
    >>> row is not None and row["status"] == "ready"
    True
    >>> readiness_for_tool("web_search")["status"]
    'needs_key'
    >>> readiness_for_tool("integration_call")["status"]
    'pending'
    >>> readiness_for_tool("sandbox_exec")["status"]
    'pending'
"""

from __future__ import annotations

from typing import Any, Final

Status = str

_STATUS_READY: Final[Status] = "ready"
_STATUS_NEEDS_KEY: Final[Status] = "needs_key"
_STATUS_NEEDS_PROXY: Final[Status] = "needs_proxy"
_STATUS_NEEDS_DEP: Final[Status] = "needs_dep"
_STATUS_PENDING: Final[Status] = "pending"

_SERP_FALLBACK: Final[str] = "Use serp for keyless DuckDuckGo search."

_READINESS: Final[dict[str, dict[str, Any]]] = {
    "serp": {
        "status": _STATUS_READY,
        "note": "Works out of the box via ddgs (no API key or proxy).",
    },
    "web_search": {
        "status": _STATUS_NEEDS_KEY,
        "note": (
            "Requires a Brave Search API key in egress proxy secrets; when the key "
            "or proxy is missing the call automatically answers via keyless serp. " + _SERP_FALLBACK
        ),
        "fallback_tool": "serp",
    },
    "web_fetch": {
        "status": _STATUS_READY,
        "note": (
            "Uses the egress proxy (/web/fetch); proxy is paired with the gateway "
            "in standard deployments."
        ),
    },
    "get_page_content": {
        "status": _STATUS_READY,
        "note": ("Wraps web_fetch + markdownify; requires egress proxy when proxy URL is set."),
    },
    "terminal_run": {
        "status": _STATUS_READY,
        "note": (
            "Interactive shell via pexpect; use process for pip install / long non-interactive "
            "commands (not terminal_run)."
        ),
    },
    "terminal_spawn": {
        "status": _STATUS_READY,
        "note": "Opens a persistent pexpect shell; health-probed with echo on spawn.",
    },
    "integration_call": {
        "status": _STATUS_PENDING,
        "note": (
            "Requires a live IntegrationProxyClient wired at gateway boot (W2). "
            "GitHub/Cursor tokens live in proxy secrets, never the gateway process."
        ),
    },
    "sandbox_exec": {
        "status": _STATUS_PENDING,
        "note": (
            "Requires a live SevnSandboxExecutorClient wired at gateway boot (W3). "
            "Install Deno and set sandbox.driver: pyodide_deno in sevn.json."
        ),
    },
}


_OVERRIDES: dict[str, dict[str, Any]] = {}


def set_tool_readiness_override(name: str, *, status: Status, note: str) -> None:
    """Set or replace a readiness row (gateway boot applies sandbox/integration wiring).

    Args:
        name (str): Registry tool name.
        status (Status): ``ready``, ``pending``, ``needs_key``, etc.
        note (str): One-line operator-facing note.

    Returns:
        None

    Examples:
        >>> set_tool_readiness_override("_doc_example_tool", status="ready", note="ok")
        >>> readiness_for_tool("_doc_example_tool")["status"]
        'ready'
    """
    _OVERRIDES[name.strip()] = {"status": status, "note": note}


def readiness_for_tool(name: str) -> dict[str, Any] | None:
    """Return a readiness row for ``name`` when known.

    Args:
        name (str): Registry tool name.

    Returns:
        dict[str, Any] | None: ``status``, ``note``, and optional ``fallback_tool``;
        ``None`` when no row is defined.

    Examples:
        >>> readiness_for_tool("web_search")["status"]
        'needs_key'
        >>> readiness_for_tool("read") is None
        True
    """
    key = name.strip()
    if key in _OVERRIDES:
        return dict(_OVERRIDES[key])
    row = _READINESS.get(key)
    if row is None:
        return None
    return dict(row)


def readiness_notes_for_tools(names: list[str]) -> dict[str, str]:
    """Collect one-line readiness notes for the given tool names.

    Args:
        names (list[str]): Registry tool names.

    Returns:
        dict[str, str]: Subset of ``names`` that have defined readiness notes.

    Examples:
        >>> notes = readiness_notes_for_tools(["serp", "web_search", "read"])
        >>> "serp" in notes and "web_search" in notes
        True
    """
    out: dict[str, str] = {}
    for name in names:
        row = readiness_for_tool(name)
        if row is not None:
            out[name] = str(row.get("note") or "")
    return out


__all__ = [
    "readiness_for_tool",
    "readiness_notes_for_tools",
    "set_tool_readiness_override",
]
