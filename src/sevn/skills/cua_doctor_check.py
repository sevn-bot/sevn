"""Cua computer-use skill doctor probes (`plan/cua-computer-use-skills-wave-plan.md` W0.5 / W6).

Module: sevn.skills.cua_doctor_check
Depends: ctypes, platform, shutil, subprocess, sevn.config.workspace_config, sevn.skills.*

Exports:
    CuaDoctorRow — one doctor probe outcome for cua skill readiness.
    probe_cua_skill_checks — binary and macOS TCC checks when skills are enabled.

Examples:
    >>> from sevn.config.workspace_config import WorkspaceConfig
    >>> rows = probe_cua_skill_checks(WorkspaceConfig.minimal())
    >>> isinstance(rows, list)
    True
"""

from __future__ import annotations

import ctypes
import ctypes.util
import platform
import shutil
import subprocess  # nosec B404
from dataclasses import dataclass

from sevn.config.workspace_config import WorkspaceConfig
from sevn.skills.computer_use import (
    computer_use_config_enabled,
    computer_use_uses_cua_driver_mcp,
    resolve_computer_use_target,
    resolve_cua_cli_command,
    resolve_cua_driver_command,
)
from sevn.skills.cua_agent import cua_agent_config_enabled
from sevn.skills.lume import lume_config_enabled, resolve_lume_command


@dataclass(frozen=True)
class CuaDoctorRow:
    """One doctor probe outcome for cua skill readiness."""

    check_id: str
    ok: bool
    detail: str
    hint: str | None = None
    severity: str = "warn"


def _binary_on_path(command: str) -> str | None:
    """Resolve a configured executable name to an absolute path when present.

    Args:
        command (str): Executable name or path from skill config.

    Returns:
        str | None: Resolved path when found on ``PATH``.

    Examples:
        >>> _binary_on_path("__definitely_missing_sevn_cua_binary__") is None
        True
    """
    resolved = shutil.which(command)
    if resolved:
        return resolved
    if "/" in command:
        path = shutil.which(command.split("/", 1)[-1])
        if path:
            return path
    return None


def _macos_accessibility_granted() -> bool | None:
    """Return whether the current process has macOS Accessibility (AX) trust.

    Returns:
        bool | None: ``True``/``False`` on Darwin; ``None`` when the probe is unavailable.

    Examples:
        >>> _macos_accessibility_granted() in (True, False, None)
        True
    """
    if platform.system() != "Darwin":
        return None
    lib_path = ctypes.util.find_library("ApplicationServices")
    if not lib_path:
        return None
    try:
        lib = ctypes.cdll.LoadLibrary(lib_path)
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        lib.AXIsProcessTrusted.argtypes = [ctypes.c_void_p]
        return bool(lib.AXIsProcessTrusted(None))
    except OSError:
        return None


def _macos_screen_recording_granted() -> bool | None:
    """Return whether the current process has macOS Screen Recording permission.

    Returns:
        bool | None: ``True``/``False`` on Darwin when CoreGraphics is available; else ``None``.

    Examples:
        >>> _macos_screen_recording_granted() in (True, False, None)
        True
    """
    if platform.system() != "Darwin":
        return None
    lib_path = ctypes.util.find_library("CoreGraphics")
    if not lib_path:
        return None
    try:
        lib = ctypes.cdll.LoadLibrary(lib_path)
        if not hasattr(lib, "CGPreflightScreenCaptureAccess"):
            return True
        lib.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        return bool(lib.CGPreflightScreenCaptureAccess())
    except OSError:
        return None


def _macos_automation_granted() -> bool | None:
    """Probe Apple Events automation access via a minimal ``System Events`` script.

    Returns:
        bool | None: ``True`` when authorized; ``False`` when denied; ``None`` when inconclusive.

    Examples:
        >>> _macos_automation_granted() in (True, False, None)
        True
    """
    if platform.system() != "Darwin":
        return None
    try:
        proc = subprocess.run(  # nosec B603 B607
            ["osascript", "-e", 'tell application "System Events" to return 1'],
            check=False,
            capture_output=True,
            text=True,
            timeout=8.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == 0:
        return True
    combined = f"{proc.stdout}\n{proc.stderr}".lower()
    if "not authorized" in combined or "-1743" in combined:
        return False
    return None


def _binary_row(
    check_id: str,
    *,
    command: str,
    install_hint: str,
) -> CuaDoctorRow:
    """Build a binary-on-PATH doctor row.

    Args:
        check_id (str): Stable doctor check id.
        command (str): Executable to resolve.
        install_hint (str): Short remediation shown in ``detail``/``hint``.

    Returns:
        CuaDoctorRow: Probe outcome row.

    Examples:
        >>> row = _binary_row("cua_driver_binary", command="cua-driver", install_hint="install")
        >>> row.check_id
        'cua_driver_binary'
    """
    found = _binary_on_path(command)
    if found:
        return CuaDoctorRow(check_id=check_id, ok=True, detail=f"{command} at {found}")
    return CuaDoctorRow(
        check_id=check_id,
        ok=False,
        detail=f"{command} not on PATH",
        hint=install_hint,
        severity="warn",
    )


def _tcc_row(
    check_id: str,
    *,
    granted: bool | None,
    entitlement_label: str,
    settings_hint: str,
) -> CuaDoctorRow:
    """Build a macOS TCC entitlement doctor row.

    Args:
        check_id (str): Stable doctor check id.
        granted (bool | None): Probe result; ``None`` means inconclusive.
        entitlement_label (str): Human-readable entitlement name.
        settings_hint (str): System Settings navigation hint.

    Returns:
        CuaDoctorRow: Probe outcome row.

    Examples:
        >>> row = _tcc_row("cua_tcc_accessibility", granted=True, entitlement_label="Accessibility", settings_hint="Privacy")
        >>> row.ok
        True
    """
    if granted is True:
        return CuaDoctorRow(
            check_id=check_id,
            ok=True,
            detail=f"{entitlement_label} granted for this process",
        )
    if granted is False:
        return CuaDoctorRow(
            check_id=check_id,
            ok=False,
            detail=f"{entitlement_label} not granted for this process",
            hint=settings_hint,
            severity="warn",
        )
    return CuaDoctorRow(
        check_id=check_id,
        ok=False,
        detail=f"{entitlement_label} could not be verified on this host",
        hint=settings_hint,
        severity="warn",
    )


def probe_cua_skill_checks(cfg: WorkspaceConfig | None) -> list[CuaDoctorRow]:
    """Run cua skill binary and TCC probes when the relevant skills are enabled.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace settings.

    Returns:
        list[CuaDoctorRow]: Rows to append to ``sevn doctor`` (may be empty).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> probe_cua_skill_checks(WorkspaceConfig.minimal())
        []
    """
    rows: list[CuaDoctorRow] = []
    cu_enabled = computer_use_config_enabled(cfg)
    agent_enabled = cua_agent_config_enabled(cfg)
    lume_enabled = lume_config_enabled(cfg)

    if cu_enabled and computer_use_uses_cua_driver_mcp(cfg):
        rows.append(
            _binary_row(
                "cua_driver_binary",
                command=resolve_cua_driver_command(cfg),
                install_hint="Run the cua-driver install.sh onboarding action or install from trycua/cua releases.",
            ),
        )

    needs_cua_cli = agent_enabled or (cu_enabled and resolve_computer_use_target(cfg) != "host")
    if needs_cua_cli:
        rows.append(
            _binary_row(
                "cua_cli_binary",
                command=resolve_cua_cli_command(cfg),
                install_hint="Run `pip install cua` (or the onboarding install action) for the sandbox CLI.",
            ),
        )

    if lume_enabled:
        rows.append(
            _binary_row(
                "lume_binary",
                command=resolve_lume_command(cfg),
                install_hint="Run the lume install.sh onboarding action or install lume for Apple-Silicon VMs.",
            ),
        )

    if cu_enabled and computer_use_uses_cua_driver_mcp(cfg) and platform.system() == "Darwin":
        settings_hint = (
            "Open System Settings → Privacy & Security and grant Accessibility, "
            "Screen Recording, and Automation to the terminal or app running sevn."
        )
        rows.append(
            _tcc_row(
                "cua_tcc_accessibility",
                granted=_macos_accessibility_granted(),
                entitlement_label="Accessibility",
                settings_hint=settings_hint,
            ),
        )
        rows.append(
            _tcc_row(
                "cua_tcc_screen_recording",
                granted=_macos_screen_recording_granted(),
                entitlement_label="Screen Recording",
                settings_hint=settings_hint,
            ),
        )
        rows.append(
            _tcc_row(
                "cua_tcc_automation",
                granted=_macos_automation_granted(),
                entitlement_label="Automation (Apple Events)",
                settings_hint=settings_hint,
            ),
        )

    return rows


__all__ = ["CuaDoctorRow", "probe_cua_skill_checks"]
