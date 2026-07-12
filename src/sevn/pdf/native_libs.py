"""WeasyPrint native library install helpers for onboarding and setup.

Module: sevn.pdf.native_libs
Depends: platform, shutil, subprocess, sevn.pdf.doctor_check

Exports:
    install_weasyprint_native_libs — best-effort brew/apt install for Pango/Cairo.
    maybe_install_pdf_native_libs_after_promote — macOS onboarding post-promote hook.

Examples:
    >>> maybe_install_pdf_native_libs_after_promote.__name__
    'maybe_install_pdf_native_libs_after_promote'
"""

from __future__ import annotations

import platform
import shutil
import subprocess  # nosec B404 — fixed brew/apt argv only; no shell

from sevn.pdf.doctor_check import probe_weasyprint_render, weasyprint_native_fix_commands

_DARWIN_BREW_PACKAGES = ("pango",)
_LINUX_APT_PACKAGES = (
    "libpango-1.0-0",
    "libpangoft2-1.0-0",
    "libharfbuzz0b",
    "libcairo2",
    "libffi8",
    "fontconfig",
)


def install_weasyprint_native_libs(*, timeout_s: float = 300.0) -> tuple[bool, str]:
    """Best-effort install of WeasyPrint Pango/Cairo native libraries.

    Mirrors ``make pdf-native-libs`` / ``weasyprint_native_fix_commands`` so
    onboarding and ``make setup`` share the same install surface as ``sevn doctor``.

    Args:
        timeout_s (float): Seconds before aborting the package-manager subprocess.

    Returns:
        tuple[bool, str]: ``(success, detail)`` — ``True`` when WeasyPrint probes OK
            after install (or was already OK).

    Examples:
        >>> ok, detail = install_weasyprint_native_libs()
        >>> isinstance(ok, bool) and isinstance(detail, str)
        True
    """
    if probe_weasyprint_render().ok:
        return True, "WeasyPrint native libs already OK"

    system = platform.system().lower()
    hint = weasyprint_native_fix_commands()

    if system == "darwin":
        if not shutil.which("brew"):
            return False, "Homebrew not found — run: brew install pango"
        argv = ["brew", "install", *_DARWIN_BREW_PACKAGES]
        success_detail = "installed WeasyPrint native libs via brew install pango"
        fail_prefix = "brew install pango"
    elif system == "linux":
        if not shutil.which("apt-get"):
            return False, f"apt-get not found — install manually: {hint}"
        argv = ["sudo", "apt-get", "install", "-y", *_LINUX_APT_PACKAGES]
        success_detail = "installed WeasyPrint native libs via apt-get"
        fail_prefix = "apt-get install"
    else:
        return False, f"unknown OS — install manually: {hint}"

    try:
        proc = subprocess.run(  # nosec B603 — allowlisted package-manager argv, no shell
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{fail_prefix} failed: {exc}"

    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        tail = stderr.splitlines()[-1] if stderr else hint
        return False, f"{fail_prefix} exited {proc.returncode}: {tail}"

    if probe_weasyprint_render().ok:
        return True, success_detail
    return False, f"{fail_prefix} finished but WeasyPrint still unavailable — run {hint}"


def maybe_install_pdf_native_libs_after_promote() -> str | None:
    """Install WeasyPrint natives during macOS onboarding when the probe fails.

    Best-effort and non-fatal: returns a summary line for handoff UI/logs, or
    ``None`` when skipped (non-macOS host or WeasyPrint already OK).

    Returns:
        str | None: Install outcome summary, or ``None`` when no action was taken.

    Examples:
        >>> maybe_install_pdf_native_libs_after_promote() is None or isinstance(
        ...     maybe_install_pdf_native_libs_after_promote(), str
        ... )
        True
    """
    if platform.system().lower() != "darwin":
        return None
    if probe_weasyprint_render().ok:
        return None
    ok, detail = install_weasyprint_native_libs()
    if ok:
        return detail
    return f"⚠️  {detail}"


__all__ = [
    "install_weasyprint_native_libs",
    "maybe_install_pdf_native_libs_after_promote",
]
