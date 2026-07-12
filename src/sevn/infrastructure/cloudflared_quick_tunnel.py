"""Cloudflare quick tunnel helpers (trycloudflare.com, no account required).

Module: sevn.infrastructure.cloudflared_quick_tunnel
Depends: re, subprocess, time, urllib.parse

Exports:
    extract_quick_tunnel_url — parse a trycloudflare.com URL from cloudflared logs.
    read_quick_tunnel_url — block until cloudflared prints the quick-tunnel URL.
"""

from __future__ import annotations

import re
import threading
import time
from typing import TYPE_CHECKING, TextIO
from urllib.parse import urlparse

if TYPE_CHECKING:
    import subprocess  # nosec B404 — type-only Popen annotation for read_quick_tunnel_url

QUICK_TUNNEL_URL_RE = re.compile(
    r"https://[a-zA-Z0-9-]+\.trycloudflare\.com/?",
    re.IGNORECASE,
)


def extract_quick_tunnel_url(text: str) -> str | None:
    """Return the first quick-tunnel HTTPS URL found in ``text``.

    Args:
        text (str): cloudflared log line or accumulated stderr.

    Returns:
        str | None: Normalized ``https://<host>/`` URL when matched.

    Examples:
        >>> extract_quick_tunnel_url(
        ...     "Visit it at https://abc-def.trycloudflare.com"
        ... )
        'https://abc-def.trycloudflare.com/'
        >>> extract_quick_tunnel_url("no url here") is None
        True
    """
    match = QUICK_TUNNEL_URL_RE.search(text)
    if match is None:
        return None
    parsed = urlparse(match.group(0).rstrip("/"))
    host = (parsed.hostname or "").strip()
    if not host:
        return None
    return f"https://{host}/"


def _drain_stderr(stderr: TextIO) -> None:
    """Read and discard remaining stderr so the child process cannot block on a full pipe.

    Args:
        stderr (TextIO): Open stderr stream from a running child process.

    Examples:
        >>> _drain_stderr  # doctest: +SKIP
    """
    try:
        for _line in stderr:
            pass
    except (OSError, ValueError):
        return


def read_quick_tunnel_url(
    proc: subprocess.Popen[bytes],
    *,
    timeout: float = 45.0,
) -> str:
    """Wait for cloudflared to publish a quick-tunnel URL on stderr.

    Args:
        proc (subprocess.Popen[bytes]): Running ``cloudflared tunnel --url …`` process
            spawned with ``stderr=subprocess.PIPE``.
        timeout (float): Seconds to wait for the URL before failing.

    Returns:
        str: Normalized ``https://<host>/`` Mission Control origin.

    Raises:
        RuntimeError: When stderr is unavailable, the process exits early, or no URL
            appears before ``timeout``.

    Examples:
        >>> read_quick_tunnel_url  # doctest: +SKIP
    """
    if proc.stderr is None:
        msg = "cloudflared quick tunnel requires stderr=PIPE to discover the public URL"
        raise RuntimeError(msg)

    deadline = time.monotonic() + timeout
    pending = ""
    while time.monotonic() < deadline:
        exit_code = proc.poll()
        if exit_code is not None and exit_code != 0:
            tail = pending.strip()
            msg = f"cloudflared quick tunnel exited with code {exit_code}" + (
                f": {tail}" if tail else ""
            )
            raise RuntimeError(msg)

        line = proc.stderr.readline()
        if not line:
            time.sleep(0.1)
            continue
        text = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
        pending += text
        url = extract_quick_tunnel_url(pending)
        if url is not None:
            threading.Thread(
                target=_drain_stderr,
                args=(proc.stderr,),
                daemon=True,
            ).start()
            return url

    msg = (
        "timed out waiting for Cloudflare quick tunnel URL "
        "(expected https://*.trycloudflare.com in cloudflared logs)"
    )
    raise RuntimeError(msg)


__all__ = ["extract_quick_tunnel_url", "read_quick_tunnel_url"]
