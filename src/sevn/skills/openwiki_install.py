"""Install helpers for the LangChain OpenWiki npm CLI.

Module: sevn.skills.openwiki_install
Depends: shutil, subprocess

Constants:
    OPENWIKI_NPM_PACKAGE — upstream npm package name.
    MIN_NODE_MAJOR — minimum supported Node.js major version.

Exports:
    openwiki_cli_installed — whether ``openwiki`` is on PATH.
    check_node_for_openwiki — verify Node.js is present and new enough.
    run_openwiki_install — ``npm install -g openwiki`` (idempotent when skipped).
"""

from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404 — fixed-argv node/npm invocations, no shell

OPENWIKI_NPM_PACKAGE = "openwiki"
MIN_NODE_MAJOR = 20

_NODE_VERSION_RE = re.compile(r"v?(\d+)")


def openwiki_cli_installed() -> bool:
    """Return whether the ``openwiki`` executable is on PATH.

    Returns:
        bool: True when ``shutil.which("openwiki")`` succeeds.

    Examples:
        >>> isinstance(openwiki_cli_installed(), bool)
        True
    """
    return shutil.which("openwiki") is not None


def check_node_for_openwiki() -> tuple[bool, str]:
    """Verify Node.js is installed and meets the OpenWiki minimum version.

    Returns:
        tuple[bool, str]: ``(ok, detail)`` where ``detail`` explains failure or
            reports the detected Node version.

    Examples:
        >>> ok, _ = check_node_for_openwiki()
        >>> ok in (True, False)
        True
    """
    node = shutil.which("node")
    if node is None:
        return False, f"node not found on PATH (Node >= {MIN_NODE_MAJOR} required for OpenWiki)"
    try:
        completed = subprocess.run(  # nosec B603 — fixed argv, no shell
            [node, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"node --version failed: {exc}"
    version_text = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0:
        return False, f"node --version failed (exit {completed.returncode}): {version_text}"
    match = _NODE_VERSION_RE.search(version_text)
    if not match:
        return False, f"could not parse node version from {version_text!r}"
    major = int(match.group(1))
    if major < MIN_NODE_MAJOR:
        return (
            False,
            f"Node {version_text} is too old (OpenWiki requires Node >= {MIN_NODE_MAJOR})",
        )
    return True, f"Node {version_text} satisfies OpenWiki requirement (>= {MIN_NODE_MAJOR})"


def run_openwiki_install(*, skip_if_installed: bool = True) -> tuple[int, str]:
    """Install the upstream OpenWiki npm CLI globally.

    Args:
        skip_if_installed (bool, optional): When True, return success without running
            ``npm`` when ``openwiki`` is already on PATH.

    Returns:
        tuple[int, str]: ``(exit_code, detail)`` — ``0`` on success or skip.

    Examples:
        >>> code, msg = run_openwiki_install(skip_if_installed=True)
        >>> code in (0, 1)
        True
    """
    if skip_if_installed and openwiki_cli_installed():
        return 0, "openwiki CLI already on PATH"
    ok, node_detail = check_node_for_openwiki()
    if not ok:
        return 1, node_detail
    npm = shutil.which("npm")
    if npm is None:
        return 1, "npm not found on PATH (install Node.js/npm, then retry)"
    try:
        completed = subprocess.run(  # nosec B603 — fixed argv, no shell
            [npm, "install", "-g", OPENWIKI_NPM_PACKAGE],
            capture_output=True,
            text=True,
            check=False,
            timeout=600.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"npm install -g {OPENWIKI_NPM_PACKAGE} failed: {exc}"
    detail = (completed.stdout or "") + (completed.stderr or "")
    detail = (
        detail.strip() or f"npm install -g {OPENWIKI_NPM_PACKAGE} exited {completed.returncode}"
    )
    if completed.returncode != 0:
        return completed.returncode, detail
    if openwiki_cli_installed():
        return 0, f"installed {OPENWIKI_NPM_PACKAGE} globally ({node_detail})"
    return (
        1,
        f"npm reported success but openwiki is still missing from PATH — {detail}",
    )


__all__ = [
    "check_node_for_openwiki",
    "openwiki_cli_installed",
    "run_openwiki_install",
]
