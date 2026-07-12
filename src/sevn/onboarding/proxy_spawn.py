"""Detached egress proxy for onboarding handoff (`specs/22-onboarding.md` §4.9).



Module: sevn.onboarding.proxy_spawn
Depends: os, subprocess, time, pathlib, sevn.cli.gateway_client, sevn.cli.uvicorn_argv,
    sevn.cli.workspace, sevn.config.loader, sevn.logging.setup



Exports:

    spawn_proxy_background — start uvicorn proxy factory detached; log to ``logs/proxy.log``.



Examples:

    >>> from sevn.onboarding.proxy_spawn import _uvicorn_argv
    >>> argv = _uvicorn_argv(host="127.0.0.1", port=8787)
    >>> argv[-1]
    '8787'
"""

from __future__ import annotations

import subprocess  # nosec B404
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sevn.cli.errors import CliPreconditionError
from sevn.cli.gateway_client import (
    probe_proxy_listen_state,
    proxy_healthz_get,
    proxy_listen_conflict_detail,
    resolve_proxy_base_url,
)
from sevn.cli.uvicorn_argv import uvicorn_program_argv
from sevn.config.loader import load_workspace
from sevn.onboarding.spawn_env import handoff_child_env

_PROXY_MODULE = "sevn.proxy.app:create_app"
_READY_POLL_ATTEMPTS = 20
_READY_POLL_INTERVAL_S = 0.3


def _uvicorn_argv(*, host: str, port: int) -> list[str]:
    """Build argv to launch the proxy ASGI factory via uvicorn.



    Args:

        host (str): Bind host.
        port (int): Listen port.



    Returns:

        list[str]: argv suitable for ``subprocess.Popen``.



    Examples:

        >>> argv = _uvicorn_argv(host="127.0.0.1", port=8787)
        >>> argv[-1]
        '8787'
    """

    return uvicorn_program_argv(
        module=_PROXY_MODULE,
        host=host,
        port=port,
        factory=True,
    )


def _proxy_host_port(*, sevn_json_path: Path) -> tuple[str, int]:
    """Resolve proxy bind host/port from workspace config and env.



    Args:

        sevn_json_path (Path): Absolute path to promoted ``sevn.json``.



    Returns:

        tuple[str, int]: Host and port for uvicorn ``--host`` / ``--port``.



    Examples:

        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> sj = td / "sevn.json"
        >>> _ = sj.write_text(
        ...     '{"schema_version": 1, "workspace_root": ".",'
        ...     ' "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        ...     encoding="utf-8",
        ... )
        >>> host, port = _proxy_host_port(sevn_json_path=sj)
        >>> port == 8787
        True
    """

    workspace_cfg, _layout = load_workspace(sevn_json=sevn_json_path)
    origin = resolve_proxy_base_url(workspace=workspace_cfg)
    parsed = urlparse(origin)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8787
    return host, port


def spawn_proxy_background(*, sevn_json_path: Path) -> dict[str, Any]:
    """Start the egress proxy in a new session; append stdout/stderr to ``logs/proxy.log``.



    Prefers a direct uvicorn child so handoff works before launchd/systemd units exist.
    When ``GET /healthz`` already succeeds, returns without spawning.



    Args:

        sevn_json_path (Path): Absolute path to promoted ``sevn.json``.



    Returns:

        dict[str, Any]: ``ok``, ``message``, ``pid`` (when spawned), ``log_path``.



    Raises:

        OSError: When the log file cannot be opened or the child cannot start.
        RuntimeError: When another process occupies the proxy port without ``/healthz``.



    Examples:

        >>> isinstance(spawn_proxy_background.__name__, str)
        True
    """

    sevn_json = sevn_json_path.expanduser().resolve()
    workspace_cfg, layout = load_workspace(sevn_json=sevn_json)
    layout.logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = layout.logs_dir / "proxy.log"
    state = probe_proxy_listen_state(workspace=workspace_cfg)
    if state == "running":
        return {
            "ok": True,
            "message": "proxy already running",
            "log_path": str(log_path),
        }
    if state == "conflict":
        raise RuntimeError(proxy_listen_conflict_detail(workspace=workspace_cfg))
    host, port = _proxy_host_port(sevn_json_path=sevn_json)
    proxy_origin = resolve_proxy_base_url(workspace=workspace_cfg)
    env = handoff_child_env(
        sevn_json_path=sevn_json,
        service="proxy",
        extra={"SEVN_PROXY_URL": proxy_origin},
    )
    try:
        proc = subprocess.Popen(  # nosec B603
            _uvicorn_argv(host=host, port=port),
            cwd=str(sevn_json.parent),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        raise
    for _ in range(_READY_POLL_ATTEMPTS):
        time.sleep(_READY_POLL_INTERVAL_S)
        try:
            proxy_healthz_get(proxy_origin, liveness=True)
        except CliPreconditionError:
            if proc.poll() is not None:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                msg = f"proxy exited ({proc.returncode}); see {log_path}"
                raise RuntimeError(msg) from None
            continue
        else:
            break
    else:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        msg = f"proxy did not become ready; see {log_path}\n{tail}"
        raise RuntimeError(msg)
    return {
        "ok": True,
        "message": "proxy started",
        "pid": proc.pid,
        "log_path": str(log_path),
    }


__all__ = ["spawn_proxy_background"]
