"""HTTPS URL → ``raw/`` fetch helper (`specs/27-second-brain.md` §2.4, §5).

Invoked from the gateway with ``httpx``; enforces allowlist, size, MIME, timeout. No partial
writes on rejection (`specs/27-second-brain.md` §6).

Exports:
    SecondBrainFetchError — policy or transport failure.
    fetch_url_to_raw — stream GET and atomically write under the sources role directory.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from sevn.second_brain.errors import SecondBrainError
from sevn.second_brain.paths import VaultLayout, effective_scope

if TYPE_CHECKING:
    from sevn.config.workspace_config import SecondBrainFetchConfig, SecondBrainWorkspaceConfig


class SecondBrainFetchError(SecondBrainError):
    """Fetch blocked by policy or transport."""


def _host_allowed(host: str, domains: list[str]) -> bool:
    """Return True when ``host`` matches an allowlisted domain (suffix or exact).

    Args:
        host (str): Lowercased hostname from the URL (no trailing dot).
        domains (list[str]): Configured allowlist entries (may include leading ``.``).

    Returns:
        bool: True when ``host`` equals an entry or ends with ``.<entry>``.

    Examples:
        >>> _host_allowed("a.example.com", ["example.com"])
        True
        >>> _host_allowed("evil.com", ["example.com"])
        False
    """
    h = host.lower().rstrip(".")
    for d in domains:
        dl = d.lower().strip().lstrip(".")
        if h == dl or h.endswith("." + dl):
            return True
    return False


def _mime_allowed(ct: str | None) -> bool:
    """Return True for allowed ``Content-Type`` values (text or PDF).

    Args:
        ct (str | None): Raw ``Content-Type`` header value, or ``None`` when absent.

    Returns:
        bool: True when the base type is ``text/*`` or ``application/pdf``.

    Examples:
        >>> _mime_allowed("text/html; charset=utf-8")
        True
        >>> _mime_allowed("application/octet-stream")
        False
    """
    if not ct:
        return False
    base = ct.split(";", maxsplit=1)[0].strip().lower()
    return base.startswith("text/") or base == "application/pdf"


def _filename_from_url(url: str, host: str) -> str:
    """Derive a filesystem-safe filename for storing the fetched body under ``raw/``.

    Args:
        url (str): Full HTTPS URL (path segment may suggest an extension).
        host (str): Hostname used when building a slug from path + host.

    Returns:
        str: Filename ending in ``.md``, ``.txt``, ``.html``, or ``.pdf`` when the URL path
        ends with one of those; otherwise a slug from host + path (capped) with ``.md``.

    Examples:
        >>> _filename_from_url("https://x/y/doc.pdf", "x")
        'doc.pdf'
        >>> _filename_from_url("https://h.example/p/q", "h.example").endswith(".md")
        True
    """
    path = urlparse(url).path or "/"
    seg = Path(path).name
    if seg and seg.endswith((".md", ".txt", ".html", ".pdf")):
        return seg
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", f"{host}{path}".lower()).strip("-")
    return (slug or "fetched")[:180] + ".md"


def _resolve_sources_dir(
    *,
    scope_root: Path,
    workspace_root: Path | None,
    sb_cfg: SecondBrainWorkspaceConfig | None,
    scope: str | None,
) -> Path:
    """Return the sources role directory for fetch writes.

    Args:
        scope_root (Path): Vault user scope root (legacy fallback parent).
        workspace_root (Path | None): Workspace content root for layout resolution.
        sb_cfg (SecondBrainWorkspaceConfig | None): Second Brain slice when layout-aware.
        scope (str | None): Scope id when ``sb_cfg`` is set.

    Returns:
        Path: Resolved sources directory (``raw/`` legacy or PARA ``_sources/``).

    Examples:
        >>> p = _resolve_sources_dir(
        ...     scope_root=Path("/tmp/u"),
        ...     workspace_root=None,
        ...     sb_cfg=None,
        ...     scope=None,
        ... )
        >>> p.name
        'raw'
    """
    if workspace_root is not None and sb_cfg is not None:
        layout = VaultLayout(workspace_root, sb_cfg, effective_scope(scope, sb_cfg))
        return layout.role_dir("sources")
    return (scope_root / "raw").resolve()


async def fetch_url_to_raw(
    *,
    url: str,
    scope_root: Path,
    fetch_cfg: SecondBrainFetchConfig,
    client: httpx.AsyncClient | None = None,
    workspace_root: Path | None = None,
    sb_cfg: SecondBrainWorkspaceConfig | None = None,
    scope: str | None = None,
) -> dict[str, object]:
    """GET ``url`` and atomically write under the active layout sources directory.

    Args:
        url (str): HTTPS URL to retrieve.
        scope_root (Path): Vault user scope root (legacy fallback when layout args omitted).
        fetch_cfg (SecondBrainFetchConfig): Allowlist, size, timeout policy.
        client (httpx.AsyncClient | None): Optional shared client; otherwise a short-lived one.
        workspace_root (Path | None): Workspace content root for :class:`VaultLayout` resolution.
        sb_cfg (SecondBrainWorkspaceConfig | None): Second Brain slice for layout-aware paths.
        scope (str | None): Scope id when ``sb_cfg`` is set.

    Returns:
        dict[str, object]: ``raw_relpath``, ``bytes_written``, and ``host`` metadata.

    Examples:
        >>> fetch_url_to_raw.__name__
        'fetch_url_to_raw'
    """

    parsed = urlparse(url)
    if parsed.scheme != "https":
        msg = "only HTTPS URLs are allowed for second_brain fetch"
        raise SecondBrainFetchError(msg)
    host = parsed.hostname or ""
    if not host:
        msg = "URL has no hostname"
        raise SecondBrainFetchError(msg)
    if not _host_allowed(host, list(fetch_cfg.allow_domains)):
        msg = (
            f"host {host!r} is not in second_brain.fetch.allow_domains "
            f"(configure sevn.json second_brain.fetch.allow_domains)"
        )
        raise SecondBrainFetchError(msg)

    max_bytes = int(fetch_cfg.max_response_mib) * 1024 * 1024
    timeout = httpx.Timeout(float(fetch_cfg.timeout_seconds))

    if client is None:
        own_client = True
        http_client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    else:
        own_client = False
        http_client = client
    buf = bytearray()
    try:
        async with http_client.stream(
            "GET",
            url,
            headers={"User-Agent": "sevn-second-brain/1.0"},
        ) as resp:
            if resp.status_code >= 400:
                msg = f"HTTP {resp.status_code} from host {host}"
                raise SecondBrainFetchError(msg)
            ct = resp.headers.get("content-type")
            if not _mime_allowed(ct):
                msg = f"disallowed Content-Type {ct!r} (need text/* or application/pdf)"
                raise SecondBrainFetchError(msg)
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    msg = (
                        f"response exceeds second_brain.fetch.max_response_mib="
                        f"{fetch_cfg.max_response_mib} (no partial write)"
                    )
                    raise SecondBrainFetchError(msg)
    finally:
        if own_client:
            await http_client.aclose()

    raw_dir = _resolve_sources_dir(
        scope_root=scope_root,
        workspace_root=workspace_root,
        sb_cfg=sb_cfg,
        scope=scope,
    )
    raw_dir.mkdir(parents=True, exist_ok=True)
    name = _filename_from_url(url, host)
    dest = raw_dir / name
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        tmp.write_bytes(bytes(buf))
        tmp.replace(dest)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise

    rel = dest.relative_to(raw_dir).as_posix()
    return {"raw_relpath": rel, "bytes_written": len(buf), "host": host}


__all__ = ["SecondBrainFetchError", "fetch_url_to_raw"]
