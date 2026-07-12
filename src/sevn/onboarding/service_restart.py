"""Restart gateway + proxy after onboarding promote (`specs/22-onboarding.md` §4.9).

Module: sevn.onboarding.service_restart
Depends: pathlib, time, sevn.cli.gateway_client, sevn.cli.gateway_teardown, sevn.cli.service_manager

Exports:
    restart_services_after_promote — stop paired units then restart proxy before gateway.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sevn.cli.gateway_client import probe_gateway_listen_state, probe_proxy_listen_state
from sevn.cli.gateway_teardown import stop_handoff_listeners
from sevn.cli.service_manager import (
    control_unit,
    propagate_daemon_proxy_env,
    propagate_daemon_secret_env,
    stop_paired_units,
    unit_file_exists,
)
from sevn.config.loader import load_workspace

_PORT_WAIT_TIMEOUT_S = 15.0
_PORT_POLL_INTERVAL_S = 0.3


def _wait_for_ports_absent(*, workspace_cfg: object) -> None:
    """Poll until configured proxy and gateway ports are not serving sevn health checks.

    Args:
        workspace_cfg (object): Parsed ``WorkspaceConfig``.

    Examples:
        >>> _wait_for_ports_absent.__name__
        '_wait_for_ports_absent'
    """
    deadline = time.monotonic() + _PORT_WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        proxy_state = probe_proxy_listen_state(workspace=workspace_cfg)  # type: ignore[arg-type]
        gateway_state = probe_gateway_listen_state(workspace=workspace_cfg)  # type: ignore[arg-type]
        if proxy_state == "absent" and gateway_state == "absent":
            return
        time.sleep(_PORT_POLL_INTERVAL_S)


def restart_services_after_promote(*, sevn_json_path: Path) -> dict[str, Any]:
    """Stop then restart paired services so promote does not leave stale listeners.

    When launchd/systemd units exist, stops both services, clears handoff orphans,
    propagates secrets unlock env from the current process, then restarts proxy before
    gateway. Without units, falls back to detached handoff spawns (proxy then gateway).

    Args:
        sevn_json_path (Path): Promoted ``sevn.json`` path.

    Returns:
        dict[str, Any]: ``ok``, ``mode`` (``daemon`` or ``spawn``), and status lines.

    Examples:
        >>> restart_services_after_promote.__name__
        'restart_services_after_promote'
    """
    sevn_json = sevn_json_path.expanduser().resolve()
    workspace_cfg, _layout = load_workspace(sevn_json=sevn_json)
    home = Path.home()
    has_proxy_unit = unit_file_exists(home=home, service="proxy")
    has_gateway_unit = unit_file_exists(home=home, service="gateway")

    propagate_daemon_secret_env()
    propagate_daemon_proxy_env()
    stop_paired_units(home=home)
    stop_handoff_listeners(workspace_cfg=workspace_cfg)
    _wait_for_ports_absent(workspace_cfg=workspace_cfg)

    if has_proxy_unit or has_gateway_unit:
        lines: list[str] = []
        if has_proxy_unit:
            lines.append(control_unit(home=home, service="proxy", action="start"))
        if has_gateway_unit:
            lines.append(control_unit(home=home, service="gateway", action="start"))
        return {"ok": True, "mode": "daemon", "lines": lines}

    from sevn.onboarding.gateway_spawn import spawn_gateway_background
    from sevn.onboarding.proxy_spawn import spawn_proxy_background

    proxy_body = spawn_proxy_background(sevn_json_path=sevn_json)
    gateway_body = spawn_gateway_background(sevn_json_path=sevn_json)
    return {
        "ok": True,
        "mode": "spawn",
        "proxy": proxy_body,
        "gateway": gateway_body,
        "message": (
            f"{proxy_body.get('message', 'proxy')}; {gateway_body.get('message', 'gateway')}"
        ),
    }


__all__ = ["restart_services_after_promote"]
