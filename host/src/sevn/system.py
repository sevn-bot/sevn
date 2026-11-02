"""First host methods: system.info, system.ping, and sync.since (D13).

Also the host probes behind ``sevn doctor`` (plan 0025 D7). Each probe returns a short
string, is bounded in time, and never raises for an expected failure; :func:`run_checks`
runs several at once and turns a hang into ``timeout`` and an exception into ``error: …``.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from sevn import __version__
from sevn.contracts.methods import (
    SyncSinceParams,
    SyncSinceResult,
    SystemCaps,
    SystemInfoParams,
    SystemInfoResult,
    SystemPingParams,
    SystemPingResult,
)
from sevn.protocol import PROTOCOL_VERSION
from sevn.protocol.registry import Ctx, method
from sevn.sandbox.policy import allow_all_enabled


@method("system.info", params=SystemInfoParams, result=SystemInfoResult, mutating=False)
async def system_info(ctx: Ctx, _params: SystemInfoParams) -> SystemInfoResult:
    identity = ctx.hub.identity
    allow_all = await asyncio.to_thread(allow_all_enabled)
    return SystemInfoResult(
        host_id=identity.host_id,
        version=__version__,
        proto=PROTOCOL_VERSION,
        caps=SystemCaps(allow_all=allow_all),
        host_pubkey_fp=identity.host_pubkey_fp,
    )


@method("system.ping", params=SystemPingParams, result=SystemPingResult, mutating=True)
async def system_ping(ctx: Ctx, params: SystemPingParams) -> SystemPingResult:
    event = await ctx.hub.emit("system.ping", "system", {"note": params.note})
    return SystemPingResult(seq=event.seq)


@method("sync.since", params=SyncSinceParams, result=SyncSinceResult, mutating=False)
async def sync_since(ctx: Ctx, params: SyncSinceParams) -> SyncSinceResult:
    page = await ctx.hub.sync_since(ctx, params.seq, limit=params.limit)
    return SyncSinceResult(host_seq=page.host_seq, next_seq=page.next_seq, more=page.more)


# --- doctor probes (plan 0025 D7) ---------------------------------------------

#: The time each doctor check may take.
CHECK_TIMEOUT = 2.0
#: Shown for the Linux-only checks on other platforms.
NOT_APPLICABLE = "n/a"
#: The AppArmor sysctl behind Ubuntu 24.04's user-namespace restriction.
USERNS_SYSCTL = "kernel.apparmor_restrict_unprivileged_userns"
USERNS_BLOCKED = f"userns-blocked ({USERNS_SYSCTL})"
UNAVAILABLE_IN_CONTAINER = "unavailable-in-container"

_OS_RELEASE = (Path("etc/os-release"), Path("usr/lib/os-release"))
_PORTALS_DIR = Path("/usr/share/xdg-desktop-portal/portals")
# bwrap wording differs between versions (0.8-0.12); match on substrings (plan 0025 W0.5).
_NO_NAMESPACE = (
    "No permissions to create new namespace",
    "No permissions to create a new namespace",
)
_PROC_MOUNT = "Can't mount proc on"
_USERNS_DENIED = (
    "setting up uid map: Permission denied",
    "Failed RTM_NEWADDR: Operation not permitted",
)


def run_checks(
    checks: Mapping[str, Callable[[], object]], timeout: float = CHECK_TIMEOUT
) -> dict[str, object]:
    """Run every check at once and wait at most ``timeout`` seconds for all of them.

    A check still running at the deadline reports ``timeout`` (its daemon thread is left
    behind and cannot delay exit); a check that raises reports ``error: <message>``.
    """
    results: dict[str, object] = {}
    guard = threading.Lock()

    def work(key: str, check: Callable[[], object]) -> None:
        try:
            value = check()
        except Exception as exc:  # noqa: BLE001 — a doctor check reports, it never raises
            value = f"error: {exc}" if str(exc) else f"error: {type(exc).__name__}"
        with guard:
            results[key] = value

    threads = [
        threading.Thread(target=work, args=(key, check), name=f"sevn-doctor-{key}", daemon=True)
        for key, check in checks.items()
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    with guard:
        return {key: results.get(key, "timeout") for key in checks}


def in_container(root: Path = Path("/")) -> bool:
    """Whether this process runs in a Docker or Podman container."""
    return (root / ".dockerenv").exists() or (root / "run" / ".containerenv").exists()


def _os_release_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if not sep or key.startswith("#"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key.strip()] = value
    return fields


def classify_platform(os_release: str | None, *, in_container: bool) -> str:
    """``container``, ``ubuntu <version>``, the os-release ``ID`` (``arch``, ``debian``), or
    ``linux`` when there is no os-release."""
    if in_container:
        return "container"
    fields = _os_release_fields(os_release or "")
    ident = fields.get("ID", "").strip().lower()
    if ident == "":
        return "linux"
    if ident == "ubuntu":
        version = fields.get("VERSION_ID", "").strip()
        return f"ubuntu {version}" if version else "ubuntu"
    return ident


def probe_platform(*, os_release: Path | None = None, root: Path | None = None) -> str:
    """The host platform for ``sevn doctor``. macOS reports ``macos <version>``."""
    if os_release is None and root is None:
        if sys.platform == "darwin":
            version = platform.mac_ver()[0]
            return f"macos {version}" if version else "macos"
        if not sys.platform.startswith("linux"):
            return sys.platform
    base = Path("/") if root is None else root
    candidates = [os_release] if os_release is not None else [base / item for item in _OS_RELEASE]
    text: str | None = None
    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        break
    return classify_platform(text, in_container=in_container(base))


def probe_service() -> str:
    """The ``sevn service status`` state (plan 0025 D1), or ``n/a`` on other platforms."""
    from sevn.service import ServiceError, UnsupportedPlatformError, manager

    try:
        return manager().status().state
    except UnsupportedPlatformError:
        return NOT_APPLICABLE
    except ServiceError as exc:
        return f"error: {exc.message}"


def classify_bwrap(returncode: int, stderr: str, *, in_container: bool) -> str:
    """Map a ``bwrap`` probe run to ``ok``, ``userns-blocked (…)``,
    ``unavailable-in-container`` or ``failed: …`` (plan 0025 W0.5)."""
    if returncode == 0:
        return "ok"
    if any(marker in stderr for marker in _NO_NAMESPACE):
        return UNAVAILABLE_IN_CONTAINER if in_container else USERNS_BLOCKED
    if _PROC_MOUNT in stderr and "Operation not permitted" in stderr:
        return UNAVAILABLE_IN_CONTAINER
    if any(marker in stderr for marker in _USERNS_DENIED):
        return USERNS_BLOCKED
    detail = next((line.strip() for line in stderr.splitlines() if line.strip()), "")
    if detail:
        return f"failed: {detail[:200]}"
    return f"failed (exit {returncode})"


def probe_bubblewrap(*, in_container: bool, timeout: float = CHECK_TIMEOUT) -> str:
    """Run ``/bin/true`` under the workspace sandbox's own ``bwrap`` argv and classify it.

    ``which bwrap`` is not enough: a kernel or container that blocks user namespaces only
    shows at exec time. A run past ``timeout`` is killed and reports ``timeout``.
    """
    binary = shutil.which("bwrap")
    if binary is None or not Path(binary).is_absolute():
        return "missing"
    from sevn.sandbox.bubblewrap import argv as bwrap_argv

    with tempfile.TemporaryDirectory(prefix="sevn-bwrap-probe-") as scratch:
        workspace = Path(scratch)
        args = bwrap_argv("/bin/true", workspace=workspace, shared=workspace, network=False)
        try:
            completed = subprocess.run(  # noqa: S603 — sevn's own bwrap argv, no shell
                args,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "timeout"
        except OSError as exc:
            return f"failed: {exc.strerror or type(exc).__name__}"
    return classify_bwrap(completed.returncode, completed.stderr, in_container=in_container)


def classify_display(env: Mapping[str, str]) -> str:
    """``wayland`` when ``WAYLAND_DISPLAY`` is set, else ``x11`` for ``DISPLAY``, else ``none``."""
    if env.get("WAYLAND_DISPLAY", "").strip():
        return "wayland"
    if env.get("DISPLAY", "").strip():
        return "x11"
    return "none"


def probe_display() -> str:
    return classify_display(os.environ)


def probe_portals(portals_dir: Path = _PORTALS_DIR) -> str:
    """``xdg-desktop-portal (<backends>)`` from the installed ``*.portal`` files, or ``none``.

    Informational for screen and computer control (plans 0060, 0075).
    """
    try:
        names = sorted(item.stem for item in portals_dir.glob("*.portal") if item.is_file())
    except OSError:
        names = []
    if not names:
        return "none"
    return f"xdg-desktop-portal ({', '.join(names)})"


def probe_linger() -> str:
    """``on`` or ``off`` from ``loginctl show-user``; ``unknown`` when it cannot tell.

    Only reads the setting. sevn never runs ``loginctl enable-linger``.
    """
    from sevn.service.systemd import SystemdService

    linger = SystemdService.for_user().linger()
    if linger is None:
        return "unknown"
    return "on" if linger else "off"
