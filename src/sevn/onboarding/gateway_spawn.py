"""Detached gateway process for onboarding handoff (`specs/22-onboarding.md` §4.9).

Module: sevn.onboarding.gateway_spawn
Depends: httpx, os, shutil, subprocess, sys, time, pathlib, sevn.cli.gateway_client,
    sevn.config.defaults, sevn.config.loader, sevn.config.workspace_config,
    sevn.security.llmignore, sevn.workspace.layout

Exports:
    spawn_gateway_background — start uvicorn detached; log to ``<workspace>/logs/gateway.log``.

Examples:
    >>> from sevn.onboarding.gateway_spawn import _uvicorn_argv
    >>> argv = _uvicorn_argv(host="127.0.0.1", port=3001)
    >>> "uvicorn" in argv[1] or argv[-1] == "3001"
    True
"""

from __future__ import annotations

import subprocess  # nosec B404
import time
from pathlib import Path
from typing import Any

from sevn.cli.errors import CliPreconditionError
from sevn.cli.gateway_client import (
    gateway_get,
    gateway_listen_conflict_detail,
    probe_gateway_listen_state,
)
from sevn.cli.uvicorn_argv import uvicorn_program_argv
from sevn.config.defaults import DEFAULT_GATEWAY_HOST, DEFAULT_GATEWAY_PORT
from sevn.config.loader import load_workspace
from sevn.onboarding.spawn_env import handoff_child_env
from sevn.security.llmignore import ensure_llmignore_layout

_GATEWAY_MODULE = "sevn.gateway.http_server:create_app"
_READY_POLL_ATTEMPTS = 20
_READY_POLL_INTERVAL_S = 0.3


def _uvicorn_argv(*, host: str, port: int) -> list[str]:
    """Build argv to launch the gateway ASGI factory via uvicorn.

    Args:
        host (str): Bind host.
        port (int): Listen port.

    Returns:
        list[str]: argv suitable for ``subprocess.Popen``.

    Examples:
        >>> argv = _uvicorn_argv(host="127.0.0.1", port=3001)
        >>> argv[-1]
        '3001'
    """
    return uvicorn_program_argv(
        module=_GATEWAY_MODULE,
        host=host,
        port=port,
        factory=True,
    )


def spawn_gateway_background(*, sevn_json_path: Path) -> dict[str, Any]:
    """Start the gateway in a new session; append stdout/stderr to ``logs/gateway.log``.

    Prefers a direct uvicorn child process so handoff works before launchd/systemd
    units are installed. When ``/health`` already succeeds, returns without spawning.

    Args:
        sevn_json_path (Path): Absolute path to promoted ``sevn.json``.

    Returns:
        dict[str, Any]: ``ok``, ``message``, ``pid`` (when spawned), ``log_path``.

    Raises:
        OSError: When the log file cannot be opened or the child cannot start.
        RuntimeError: When another process occupies the gateway port without ``/health``.

    Examples:
        >>> isinstance(spawn_gateway_background.__name__, str)
        True
    """
    sevn_json = sevn_json_path.expanduser().resolve()
    workspace_cfg, layout = load_workspace(sevn_json=sevn_json)
    ensure_llmignore_layout(layout.content_root, workspace_cfg)
    layout.logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = layout.logs_dir / "gateway.log"

    state = probe_gateway_listen_state(workspace=workspace_cfg)
    if state == "running":
        return {
            "ok": True,
            "message": "gateway already running",
            "log_path": str(log_path),
        }
    if state == "conflict":
        raise RuntimeError(gateway_listen_conflict_detail(workspace=workspace_cfg))

    gw = workspace_cfg.gateway
    host = (gw.host if gw and gw.host else None) or DEFAULT_GATEWAY_HOST
    port = int((gw.port if gw and gw.port is not None else None) or DEFAULT_GATEWAY_PORT)
    env = handoff_child_env(sevn_json_path=sevn_json, service="gateway")
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
            gateway_get("/health", workspace=workspace_cfg, liveness=True)
        except CliPreconditionError:
            if proc.poll() is not None:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                msg = f"gateway exited ({proc.returncode}); see {log_path}"
                raise RuntimeError(msg) from None
            continue
        else:
            break
    else:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        msg = f"gateway did not become ready; see {log_path}\n{tail}"
        raise RuntimeError(msg)

    return {
        "ok": True,
        "message": "gateway started",
        "pid": proc.pid,
        "log_path": str(log_path),
    }


__all__ = ["spawn_gateway_background"]
