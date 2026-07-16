"""Stop sevn-owned gateway processes during operator teardown.

Module: sevn.cli.gateway_teardown
Depends: os, subprocess, time, pathlib, sevn.cli.gateway_client, sevn.cli.service_manager,
    sevn.browser.lifecycle

Exports:
    stop_all_gateway_instances — stop units, unload labels, kill orphan listeners.
    stop_handoff_listeners — kill detached handoff uvicorn on proxy and gateway ports.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404
import sys
import time
from collections.abc import Callable
from pathlib import Path

from sevn.cli.errors import CliPreconditionError
from sevn.cli.gateway_client import (
    gateway_listen_conflict_detail,
    proxy_listen_conflict_detail,
)
from sevn.cli.service_manager import (
    _launchd_label,
    plan_install,
    remove_paired_unit_files,
    stop_paired_units,
)
from sevn.config.defaults import DEFAULT_PROXY_PORT
from sevn.config.loader import load_workspace


def _is_sevn_proxy_cmdline(cmdline: str) -> bool:
    """Return True when ``cmdline`` looks like the sevn proxy uvicorn factory.

    Args:
        cmdline (str): Process command line.

    Returns:
        bool: Whether the process may be stopped during handoff restart.

    Examples:
        >>> _is_sevn_proxy_cmdline("uvicorn sevn.proxy.app:create_app --factory")
        True
    """
    lower = cmdline.lower()
    return "sevn.proxy.app" in lower or (
        "uvicorn" in lower and "create_app" in lower and "sevn" in lower and "proxy" in lower
    )


def _is_sevn_gateway_cmdline(cmdline: str) -> bool:
    """Return True when ``cmdline`` looks like the sevn gateway uvicorn factory.

    Args:
        cmdline (str): Process command line.

    Returns:
        bool: Whether the process may be stopped during unboard.

    Examples:
        >>> _is_sevn_gateway_cmdline("uvicorn sevn.gateway.http_server:create_app --factory")
        True
    """
    lower = cmdline.lower()
    return "sevn.gateway.http_server" in lower or (
        "uvicorn" in lower and "create_app" in lower and "sevn" in lower
    )


def _pids_on_port(port: int) -> list[int]:
    """Return PIDs listening on ``port`` (best-effort).

    Args:
        port (int): TCP listen port.

    Returns:
        list[int]: Process ids, possibly empty.

    Examples:
        >>> isinstance(_pids_on_port(59999), list)
        True
    """
    if sys.platform == "darwin":
        cmd = ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"]
    else:
        cmd = ["lsof", "-nP", f"-i:{port}", "-sTCP:LISTEN", "-t"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # nosec B603
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    pids: list[int] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _read_cmdline(pid: int) -> str:
    """Return the command line for ``pid`` when readable.

    Args:
        pid (int): Process id.

    Returns:
        str: Command line or empty string.

    Examples:
        >>> isinstance(_read_cmdline(1), str)
        True
    """
    if sys.platform.startswith("linux"):
        path = Path(f"/proc/{pid}/cmdline")
        try:
            raw = path.read_bytes()
        except OSError:
            return ""
        return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")
    ps_bin = shutil.which("ps") or "/bin/ps"
    try:
        proc = subprocess.run(  # nosec B603
            [ps_bin, "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _terminate_pid(pid: int, *, dry_run: bool) -> None:
    """SIGTERM then SIGKILL via the shared escalate helper.

    Args:
        pid (int): Target process id.
        dry_run (bool): Print action only.

    Returns:
        None

    Examples:
        >>> _terminate_pid(1, dry_run=True) is None
        True
    """
    if dry_run:
        return
    from sevn.browser.lifecycle import terminate_pid

    terminate_pid(pid, escalate=True)


def _bootout_launchd_labels(*, home: Path, dry_run: bool) -> None:
    """Unload gateway/proxy launchd jobs by label even when plist files are gone.

    Args:
        home (Path): Operator home (for plan resolution).
        dry_run (bool): Print commands only.

    Returns:
        None

    Examples:
        >>> _bootout_launchd_labels(home=Path("/tmp"), dry_run=True) is None
        True
    """
    if sys.platform != "darwin":
        return
    plan = plan_install(home)
    if plan.platform != "launchd":
        return
    uid = str(Path.home().stat().st_uid)
    for path in (plan.gateway_unit_path, plan.proxy_unit_path):
        label = _launchd_label(path)
        target = f"gui/{uid}/{label}"
        cmd = ["launchctl", "bootout", target]
        if dry_run:
            continue
        subprocess.run(cmd, capture_output=True, check=False)  # nosec B603


def _kill_orphan_on_port(
    *,
    port: int,
    workspace_cfg: object,
    is_sevn_cmdline: Callable[[str], bool],
    conflict_detail: str,
    dry_run: bool,
) -> None:
    """Terminate sevn uvicorn listeners on ``port`` when cmdline matches.

    Args:
        port (int): TCP listen port.
        workspace_cfg (object): Parsed ``WorkspaceConfig`` (for error messages).
        is_sevn_cmdline (object): Callable ``(cmdline: str) -> bool``.
        conflict_detail (str): Operator-facing conflict message.
        dry_run (bool): Plan only.

    Raises:
        CliPreconditionError: Non-sevn process owns the port.

    Examples:
        >>> _kill_orphan_on_port(
        ...     port=59999,
        ...     workspace_cfg=object(),
        ...     is_sevn_cmdline=lambda _c: False,
        ...     conflict_detail="port busy",
        ...     dry_run=True,
        ... ) is None
        True
    """
    pids = _pids_on_port(port)
    if not pids:
        return
    for pid in pids:
        cmdline = _read_cmdline(pid)
        if not is_sevn_cmdline(cmdline):
            msg = f"port still in use by non-sevn process (pid {pid}); {conflict_detail}"
            raise CliPreconditionError(msg, exit_code=4)
        if dry_run:
            continue
        _terminate_pid(pid, dry_run=False)
    if not dry_run:
        time.sleep(0.3)


def _kill_orphan_proxy(*, workspace_cfg: object, dry_run: bool) -> None:
    """Terminate sevn uvicorn listeners on the configured proxy port.

    Args:
        workspace_cfg (object): Parsed ``WorkspaceConfig``.
        dry_run (bool): Plan only.

    Raises:
        CliPreconditionError: Foreign process on proxy port (exit 4).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _kill_orphan_proxy(workspace_cfg=WorkspaceConfig.minimal(), dry_run=True) is None
        True
    """
    proxy = getattr(workspace_cfg, "proxy", None)
    port = DEFAULT_PROXY_PORT
    if isinstance(proxy, dict):
        raw_port = proxy.get("port")
        if raw_port is not None:
            port = int(raw_port)
    _kill_orphan_on_port(
        port=port,
        workspace_cfg=workspace_cfg,
        is_sevn_cmdline=_is_sevn_proxy_cmdline,
        conflict_detail=proxy_listen_conflict_detail(workspace=workspace_cfg),  # type: ignore[arg-type]
        dry_run=dry_run,
    )


def _kill_orphan_gateway(*, workspace_cfg: object, dry_run: bool) -> None:
    """Terminate sevn uvicorn listeners on the configured gateway port.

    Uses the listen port from ``workspace_cfg`` (not ``GET /health``) so handoff
    or crashed gateways are still torn down during ``sevn unboard``.

    Args:
        workspace_cfg (object): Parsed ``WorkspaceConfig``.
        dry_run (bool): Plan only.

    Raises:
        CliPreconditionError: Foreign process on gateway port (exit 4).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _kill_orphan_gateway(workspace_cfg=WorkspaceConfig.minimal(), dry_run=True) is None
        True
    """
    gw = getattr(workspace_cfg, "gateway", None)
    from sevn.config.defaults import DEFAULT_GATEWAY_PORT

    port = int((gw.port if gw and gw.port is not None else None) or DEFAULT_GATEWAY_PORT)
    _kill_orphan_on_port(
        port=port,
        workspace_cfg=workspace_cfg,
        is_sevn_cmdline=_is_sevn_gateway_cmdline,
        conflict_detail=gateway_listen_conflict_detail(workspace=workspace_cfg),  # type: ignore[arg-type]
        dry_run=dry_run,
    )


def stop_handoff_listeners(*, workspace_cfg: object, dry_run: bool = False) -> None:
    """Stop detached handoff uvicorn processes on configured proxy and gateway ports.

    Args:
        workspace_cfg (object): Parsed ``WorkspaceConfig``.
        dry_run (bool): Plan only.

    Raises:
        CliPreconditionError: Non-sevn process owns a configured port.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> stop_handoff_listeners(workspace_cfg=WorkspaceConfig.minimal(), dry_run=True) is None
        True
    """
    _kill_orphan_proxy(workspace_cfg=workspace_cfg, dry_run=dry_run)
    _kill_orphan_gateway(workspace_cfg=workspace_cfg, dry_run=dry_run)


def stop_all_gateway_instances(*, operator_home: Path, dry_run: bool = False) -> None:
    """Stop gateway user units and any detached handoff uvicorn for ``operator_home``.

    Args:
        operator_home (Path): ``SEVN_HOME`` being removed.
        dry_run (bool): Print planned actions without side effects.

    Raises:
        CliPreconditionError: Non-sevn process owns the gateway port.

    Examples:
        >>> stop_all_gateway_instances(operator_home=Path("/tmp/x"), dry_run=True) is None
        True
    """
    unit_home = Path.home()
    stop_paired_units(home=unit_home, dry_run=dry_run)
    _bootout_launchd_labels(home=unit_home, dry_run=dry_run)
    remove_paired_unit_files(home=unit_home, dry_run=dry_run)

    sevn_json = operator_home / "workspace" / "sevn.json"
    if sevn_json.is_file():
        workspace_cfg, _layout = load_workspace(sevn_json=sevn_json)
    else:
        from sevn.config.workspace_config import WorkspaceConfig

        workspace_cfg = WorkspaceConfig.minimal()
    _kill_orphan_gateway(workspace_cfg=workspace_cfg, dry_run=dry_run)


__all__ = ["stop_all_gateway_instances", "stop_handoff_listeners"]
