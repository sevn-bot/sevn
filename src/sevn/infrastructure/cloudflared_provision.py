"""cloudflared install and Cloudflare dashboard credential parsing.

Module: sevn.infrastructure.cloudflared_provision
Depends: platform, re, shutil, subprocess, sevn.infrastructure.tunnel_config

Exports:
    parse_cloudflared_tunnel_input — extract a tunnel token from dashboard paste text.
    ensure_cloudflared_binary — install cloudflared when missing (Homebrew on macOS).
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess  # nosec B404
from collections.abc import Callable

from sevn.infrastructure.tunnel_config import install_hint_for_binary

_SERVICE_INSTALL_RE = re.compile(
    r"cloudflared\s+service\s+install\s+(\S+)",
    re.IGNORECASE,
)
_RUN_TOKEN_RE = re.compile(
    r"cloudflared\s+tunnel\s+run\b.*--token\s+(\S+)",
    re.IGNORECASE,
)

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def parse_cloudflared_tunnel_input(text: str) -> str:
    """Extract a Cloudflare tunnel token from operator paste text.

    Accepts the dashboard **Install as service** command, a ``cloudflared tunnel run``
    invocation, or a bare token string.

    Args:
        text (str): Raw stdin / prompt input from the operator.

    Returns:
        str: Tunnel token plaintext.

    Raises:
        ValueError: When the input is empty or cannot be parsed.

    Examples:
        >>> parse_cloudflared_tunnel_input(
        ...     "sudo cloudflared service install eyJhIjoiYSJ9"
        ... )
        'eyJhIjoiYSJ9'
        >>> parse_cloudflared_tunnel_input("eyJhIjoiYSJ9")
        'eyJhIjoiYSJ9'
    """
    raw = text.strip()
    if not raw:
        msg = "paste the Cloudflare Install as service command or tunnel token"
        raise ValueError(msg)
    if match := _SERVICE_INSTALL_RE.search(raw):
        return match.group(1).strip()
    if match := _RUN_TOKEN_RE.search(raw):
        return match.group(1).strip()
    if " " not in raw:
        return raw
    msg = (
        "could not parse a tunnel token — paste the full Install as service command "
        "from the Cloudflare dashboard"
    )
    raise ValueError(msg)


def ensure_cloudflared_binary(
    *,
    timeout_s: float = 300.0,
    runner: Runner | None = None,
) -> tuple[str | None, str]:
    """Return a cloudflared path, installing via Homebrew on macOS when missing.

    Args:
        timeout_s (float): Seconds before aborting a package-manager subprocess.
        runner (Runner | None): Injectable subprocess runner for tests.

    Returns:
        tuple[str | None, str]: ``(absolute_path, detail)`` — path is ``None`` when
            installation failed or no automated installer exists.

    Examples:
        >>> path, detail = ensure_cloudflared_binary()
        >>> isinstance(detail, str) and (path is None or isinstance(path, str))
        True
    """
    existing = shutil.which("cloudflared")
    if existing:
        return existing, "cloudflared already on PATH"

    system = platform.system().lower()
    if system == "darwin" and shutil.which("brew"):
        argv = ["brew", "install", "cloudflared"]
        run = runner or _default_runner
        try:
            proc = run(argv)
        except (OSError, subprocess.SubprocessError) as exc:
            return None, f"brew install cloudflared failed: {exc}"
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return None, f"brew install cloudflared failed: {err or proc.returncode}"
        installed = shutil.which("cloudflared")
        if installed:
            return installed, "installed cloudflared via brew"
        return None, "brew install cloudflared finished but cloudflared is still not on PATH"

    return None, install_hint_for_binary("cloudflared")


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a package-manager argv with captured output (production default).

    Args:
        argv (list[str]): Command argv.

    Returns:
        subprocess.CompletedProcess[str]: Completed process record.

    Examples:
        >>> _default_runner.__name__
        '_default_runner'
    """
    return subprocess.run(  # nosec B603
        argv,
        capture_output=True,
        text=True,
        timeout=300.0,
        check=False,
    )


__all__ = ["ensure_cloudflared_binary", "parse_cloudflared_tunnel_input"]
