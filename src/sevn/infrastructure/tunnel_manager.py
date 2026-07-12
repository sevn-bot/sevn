"""Tunnel process lifecycle manager for cloudflared, ngrok, and tailscale.

Module: sevn.infrastructure.tunnel_manager
Depends: json, os, signal, subprocess, time, dataclasses, pathlib,
    sevn.infrastructure.tunnel_config

Constants:
    RUNNABLE_MODES — re-exported from :mod:`sevn.infrastructure.tunnel_config`.
    default_manager — module-level singleton used by the ops API.

Exports:
    TunnelStatus — process health snapshot.
    TunnelManager — start/stop/status for a tunnel child process.
    tunnel_pid_file — shared pid-file path so CLI and dashboard agree on state.

Supported modes: ``cloudflare`` (cloudflared), ``cloudflare_quick`` (trycloudflare.com),
``ngrok``, ``tailscale_serve`` and
``tailscale_funnel``. When a ``pid_file`` is supplied the manager records the spawned
PID so a short-lived CLI process can track and stop the tunnel across separate
invocations (``sevn tunnel start`` / ``sevn tunnel stop``).
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess  # nosec B404
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sevn.infrastructure.tunnel_config import (
    RUNNABLE_MODES,
    TAILSCALE_MODES,
    build_tunnel_launch,
    build_tunnel_stop,
    is_tailscale_mode,
)

if TYPE_CHECKING:
    from pathlib import Path

_STOP_POLL_ATTEMPTS: int = 50
_STOP_POLL_INTERVAL_S: float = 0.1


def tunnel_pid_file(content_root: Path) -> Path:
    """Return the shared tunnel pid-file path for a workspace.

    Both the CLI (``sevn tunnel``) and the dashboard ops API bind to this path so a
    tunnel started on one surface is observed and stopped on the other.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        Path: ``<content_root>/.sevn/tunnel.pid``.

    Examples:
        >>> from pathlib import Path
        >>> tunnel_pid_file(Path("/w")) == Path("/w/.sevn/tunnel.pid")
        True
    """
    return content_root / ".sevn" / "tunnel.pid"


def _pid_alive(pid: int) -> bool:
    """Return True when a process with ``pid`` exists and is signalable.

    Args:
        pid (int): Candidate process id.

    Returns:
        bool: Whether the process is alive (``os.kill(pid, 0)`` succeeds).

    Examples:
        >>> import os
        >>> _pid_alive(os.getpid())
        True
        >>> _pid_alive(0)
        False
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _mode_mismatch_error(running_mode: str, config_mode: str) -> str:
    """Format a mode-mismatch error for status/start responses.

    Args:
        running_mode (str): Mode recorded for the live tunnel process.
        config_mode (str): Mode from ``infrastructure.tunnel.mode``.

    Returns:
        str: Human-readable error message.

    Examples:
        >>> "ngrok" in _mode_mismatch_error("ngrok", "cloudflare")
        True
    """
    return (
        f"tunnel running as {running_mode!r} "
        f"but config specifies {config_mode!r}; stop it or start to replace"
    )


def _stop_popen(proc: subprocess.Popen[bytes]) -> None:
    """Terminate a managed child process gracefully, then kill if needed.

    Args:
        proc (subprocess.Popen[bytes]): Child process handle.

    Examples:
        >>> _stop_popen.__name__
        '_stop_popen'
    """
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _run_tailscale_stop(mode: str) -> None:
    """Reset Tailscale serve/funnel state (best effort).

    Args:
        mode (str): ``tailscale_serve`` or ``tailscale_funnel``.

    Examples:
        >>> _run_tailscale_stop.__name__
        '_run_tailscale_stop'
    """
    with contextlib.suppress(OSError, RuntimeError, ValueError):
        argv = build_tunnel_stop(mode)
        subprocess.run(  # nosec B603
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def _stop_recorded_tunnel(record: dict[str, Any]) -> None:
    """Stop the tunnel described by a pidfile record.

    Args:
        record (dict[str, Any]): ``{"pid", "mode", "hostname"}`` from the pid file.

    Examples:
        >>> _stop_recorded_tunnel({"pid": 0, "mode": "tailscale_funnel", "hostname": ""}) is None
        True
    """
    stored_mode = str(record.get("mode") or "")
    file_pid = int(record["pid"])
    if is_tailscale_mode(stored_mode):
        _run_tailscale_stop(stored_mode)
    elif file_pid > 0 and _pid_alive(file_pid):
        _stop_pid(file_pid)


def _stop_pid(pid: int) -> None:
    """Send SIGTERM then SIGKILL to a tunnel process by PID.

    Args:
        pid (int): Process id recorded in the pid file.

    Examples:
        >>> _stop_pid.__name__
        '_stop_pid'
    """
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGTERM)
        for _ in range(_STOP_POLL_ATTEMPTS):
            if not _pid_alive(pid):
                return
            time.sleep(_STOP_POLL_INTERVAL_S)
        os.kill(pid, signal.SIGKILL)


@dataclass
class TunnelStatus:
    """Snapshot of tunnel process health.

    Attributes:
        mode: Configured tunnel mode (from sevn.json infrastructure.tunnel.mode).
        pid: OS PID of the running tunnel process, or None if not running.
        healthy: True when the child process is alive and not yet exited.
        public_url: Derived HTTPS URL from ``hostname`` config when healthy, else None.
        error: Last exit error string if the process died unexpectedly, else None.
    """

    mode: str
    pid: int | None
    healthy: bool
    public_url: str | None
    error: str | None
    mission_control_url: str | None = None


class TunnelManager:
    """Lifecycle manager for a tunnel child process.

    Tracks a single subprocess.Popen handle. When ``pid_file`` is set the spawned PID
    is also persisted so a fresh process (e.g. a later CLI invocation) can observe and
    stop a tunnel it did not itself spawn. Thread-safe enough for single-process
    FastAPI (GIL + asyncio.to_thread dispatches are serialised by the event loop).

    Examples:
        >>> mgr = TunnelManager()
        >>> s = mgr.status({"mode": "none"})
        >>> s.healthy
        False
    """

    def __init__(self, *, pid_file: Path | None = None) -> None:
        """Initialize with no running child process.

        Args:
            pid_file (Path | None): Optional path used to persist the spawned PID for
                cross-process status/stop. When None the manager is in-process only.

        Examples:
            >>> TunnelManager()._process is None
            True
            >>> TunnelManager(pid_file=None)._pid_file is None
            True
        """
        self._process: subprocess.Popen[bytes] | None = None
        self._pid_file = pid_file
        self._started_mode: str | None = None

    def attach_pid_file(self, pid_file: Path) -> None:
        """Bind this manager to a shared pid file (idempotent).

        Used by the long-lived gateway singleton so that a tunnel started by the CLI
        (or vice versa) is observed and stopped consistently across both surfaces.

        Args:
            pid_file (Path): Shared pid-file path (see :func:`tunnel_pid_file`).

        Examples:
            >>> from pathlib import Path
            >>> mgr = TunnelManager()
            >>> mgr.attach_pid_file(Path("/w/.sevn/tunnel.pid"))
            >>> mgr._pid_file == Path("/w/.sevn/tunnel.pid")
            True
        """
        self._pid_file = pid_file

    def _read_pid_file_record(self) -> dict[str, Any] | None:
        """Read PID and metadata from ``pid_file`` when present and valid.

        Returns:
            dict[str, Any] | None: ``{"pid", "mode", "hostname"}`` or None when unusable.

        Examples:
            >>> TunnelManager()._read_pid_file_record() is None
            True
        """
        if self._pid_file is None or not self._pid_file.is_file():
            return None
        try:
            data = json.loads(self._pid_file.read_text(encoding="utf-8"))
            pid = int(data["pid"])
            mode = str(data.get("mode") or "")
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if pid <= 0 and mode not in TAILSCALE_MODES:
            return None
        return {
            "pid": pid,
            "mode": mode,
            "hostname": str(data.get("hostname") or ""),
        }

    def _pid_from_file(self) -> int | None:
        """Read the recorded PID from ``pid_file`` when present and valid.

        Returns:
            int | None: Stored PID, or None when no usable pid file exists.

        Examples:
            >>> TunnelManager()._pid_from_file() is None
            True
        """
        record = self._read_pid_file_record()
        return None if record is None else int(record["pid"])

    def _write_pid_file(self, pid: int, mode: str, hostname: str) -> None:
        """Persist the spawned PID and metadata to ``pid_file``.

        Args:
            pid (int): Spawned process id.
            mode (str): Tunnel mode that was started.
            hostname (str): Public hostname for status display (may be empty).

        Raises:
            RuntimeError: When the pid file cannot be written.

        Examples:
            >>> TunnelManager()._write_pid_file(1, "cloudflare", "") is None
            True
        """
        if self._pid_file is None:
            return
        try:
            self._pid_file.parent.mkdir(parents=True, exist_ok=True)
            self._pid_file.write_text(
                json.dumps({"pid": pid, "mode": mode, "hostname": hostname}),
                encoding="utf-8",
            )
        except OSError as exc:
            raise RuntimeError(
                f"failed to write tunnel pid file {self._pid_file}: {exc}",
            ) from exc

    def _clear_pid_file(self) -> None:
        """Remove the pid file if present (best effort).

        Examples:
            >>> TunnelManager()._clear_pid_file() is None
            True
        """
        if self._pid_file is not None:
            with contextlib.suppress(OSError):
                self._pid_file.unlink(missing_ok=True)

    def _resolve_live_tunnel(
        self,
        config_mode: str,
    ) -> tuple[int | None, bool, str | None]:
        """Resolve pid, health, and error for the current tunnel process.

        Args:
            config_mode (str): Mode from ``infrastructure.tunnel.mode``.

        Returns:
            tuple[int | None, bool, str | None]: ``(pid, healthy, error)``.

        Examples:
            >>> TunnelManager()._resolve_live_tunnel("none")
            (None, False, None)
        """
        mode = str(config_mode or "none")
        pid: int | None = None
        healthy = False
        error: str | None = None

        if self._process is not None:
            ret = self._process.poll()
            if ret is None:
                pid = self._process.pid
                if self._started_mode and self._started_mode != mode:
                    error = _mode_mismatch_error(self._started_mode, mode)
                else:
                    healthy = True
            else:
                exit_error = f"tunnel process exited with code {ret}"
                dead_pid = self._process.pid
                self._process = None
                self._started_mode = None
                record = self._read_pid_file_record()
                if record is not None:
                    file_pid = int(record["pid"])
                    if file_pid == dead_pid or not _pid_alive(file_pid):
                        self._clear_pid_file()
                    else:
                        stored_mode = str(record.get("mode") or "")
                        pid = file_pid
                        if stored_mode and stored_mode != mode:
                            error = _mode_mismatch_error(stored_mode, mode)
                        else:
                            healthy = True
                        return pid, healthy, error
                error = exit_error
            return pid, healthy, error

        record = self._read_pid_file_record()
        if record is not None:
            file_pid = int(record["pid"])
            stored_mode = str(record.get("mode") or "")
            if stored_mode in TAILSCALE_MODES and file_pid <= 0:
                pid = None
                if stored_mode and stored_mode != mode:
                    error = _mode_mismatch_error(stored_mode, mode)
                else:
                    healthy = True
            elif _pid_alive(file_pid):
                pid = file_pid
                if stored_mode and stored_mode != mode:
                    error = _mode_mismatch_error(stored_mode, mode)
                else:
                    healthy = True
            else:
                self._clear_pid_file()
        return pid, healthy, error

    def _public_hostname(
        self,
        tunnel_config: dict[str, Any],
        *,
        healthy: bool,
    ) -> str:
        """Resolve the public hostname for status display.

        Quick tunnels publish a fresh ``*.trycloudflare.com`` host on each start; prefer
        the live value from the pid file when the process is healthy.

        Args:
            tunnel_config (dict[str, Any]): ``infrastructure.tunnel`` sub-dict.
            healthy (bool): Whether the tunnel process is currently healthy.

        Returns:
            str: Hostname for ``public_url`` / ``mission_control_url`` (may be empty).

        Examples:
            >>> TunnelManager()._public_hostname({"hostname": "bot.example.com"}, healthy=True)
            'bot.example.com'
        """
        hostname = str(tunnel_config.get("hostname") or "").strip()
        if not healthy:
            return hostname
        record = self._read_pid_file_record()
        if record is None:
            return hostname
        live = str(record.get("hostname") or "").strip()
        return live or hostname

    def _start_cloudflare_quick(self, tunnel_config: dict[str, Any]) -> TunnelStatus:
        """Spawn a Cloudflare quick tunnel and capture the published URL.

        Args:
            tunnel_config (dict[str, Any]): Prepared tunnel runtime config.

        Returns:
            TunnelStatus: State after spawn attempt.

        Raises:
            RuntimeError: When URL discovery fails or the pid file cannot be written.

        Examples:
            >>> TunnelManager()._start_cloudflare_quick({"mode": "cloudflare_quick"})  # doctest: +SKIP
        """
        from sevn.infrastructure.cloudflared_quick_tunnel import read_quick_tunnel_url

        argv, env = build_tunnel_launch("cloudflare_quick", tunnel_config)
        proc = subprocess.Popen(  # nosec B603
            argv,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            close_fds=True,
            start_new_session=True,
        )
        try:
            public_url = read_quick_tunnel_url(proc)
        except RuntimeError:
            _stop_popen(proc)
            raise
        hostname = public_url.removeprefix("https://").rstrip("/")
        try:
            self._write_pid_file(proc.pid, "cloudflare_quick", hostname)
        except RuntimeError:
            _stop_popen(proc)
            raise
        self._process = proc
        self._started_mode = "cloudflare_quick"
        return self.status(tunnel_config)

    def status(self, tunnel_config: dict[str, Any]) -> TunnelStatus:
        """Return the current process health snapshot without side effects.

        Args:
            tunnel_config (dict[str, Any]): ``infrastructure.tunnel`` sub-dict from sevn.json.

        Returns:
            TunnelStatus: Live process state.

        Examples:
            >>> TunnelManager().status({"mode": "none"}).healthy
            False
        """
        mode = str(tunnel_config.get("mode", "none") or "none")
        pid, healthy, error = self._resolve_live_tunnel(mode)
        hostname = self._public_hostname(tunnel_config, healthy=healthy)
        public_url = f"https://{hostname}" if hostname and healthy else None
        from sevn.infrastructure.cloudflare_tunnel_api import tunnel_mission_control_url

        mission_control_url = tunnel_mission_control_url(hostname) if healthy else None
        return TunnelStatus(
            mode=mode,
            pid=pid,
            healthy=healthy,
            public_url=public_url,
            error=error,
            mission_control_url=mission_control_url,
        )

    def start(self, tunnel_config: dict[str, Any], *, confirm: bool) -> TunnelStatus:
        """Spawn the tunnel child process for the configured mode.

        Args:
            tunnel_config (dict[str, Any]): ``infrastructure.tunnel`` sub-dict with any
                ``${SECRET:…}`` refs already expanded to plaintext.
            confirm (bool): Must be True — explicit caller acknowledgement.

        Returns:
            TunnelStatus: State after spawn attempt.

        Raises:
            ValueError: When ``confirm`` is False or the mode is not runnable.
            RuntimeError: When the provider binary is missing or credentials are absent.

        Examples:
            >>> TunnelManager().start({"mode": "cloudflare"}, confirm=False)
            Traceback (most recent call last):
                ...
            ValueError: confirm=True required to start the tunnel
        """
        if not confirm:
            raise ValueError("confirm=True required to start the tunnel")

        mode = str(tunnel_config.get("mode") or "none")
        if mode not in RUNNABLE_MODES:
            raise ValueError(
                f"start does not support mode={mode!r} (expected one of {sorted(RUNNABLE_MODES)})",
            )

        if self._process is not None and self._process.poll() is None:
            if self._started_mode is None or self._started_mode == mode:
                record = self._read_pid_file_record()
                if record is not None:
                    stored_mode = str(record.get("mode") or "")
                    if stored_mode != mode:
                        _stop_recorded_tunnel(record)
                        self._clear_pid_file()
                return self.status(tunnel_config)
            _stop_popen(self._process)
            self._process = None
            self._started_mode = None

        record = self._read_pid_file_record()
        if record is not None:
            stored_mode = str(record.get("mode") or "")
            file_pid = int(record["pid"])
            if stored_mode == mode and (
                (stored_mode in TAILSCALE_MODES and file_pid <= 0) or _pid_alive(file_pid)
            ):
                return self.status(tunnel_config)
            _stop_recorded_tunnel(record)
            self._clear_pid_file()

        argv, env = build_tunnel_launch(mode, tunnel_config)

        if mode == "cloudflare_quick":
            return self._start_cloudflare_quick(tunnel_config)

        if is_tailscale_mode(mode):
            completed = subprocess.run(  # nosec B603
                argv,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode != 0:
                err = completed.stderr.decode(errors="replace") if completed.stderr else ""
                raise RuntimeError(err.strip() or f"tailscale {mode} failed")
            hostname = str(tunnel_config.get("hostname") or "").strip()
            try:
                self._write_pid_file(0, mode, hostname)
            except RuntimeError as exc:
                _run_tailscale_stop(mode)
                raise exc
            self._process = None
            self._started_mode = mode
            return self.status(tunnel_config)

        proc = subprocess.Popen(  # nosec B603
            argv,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        hostname = str(tunnel_config.get("hostname") or "").strip()
        try:
            self._write_pid_file(proc.pid, mode, hostname)
        except RuntimeError:
            _stop_popen(proc)
            raise
        self._process = proc
        self._started_mode = mode
        return self.status(tunnel_config)

    def stop(self, tunnel_config: dict[str, Any], *, confirm: bool) -> TunnelStatus:
        """Terminate the tunnel child process.

        Args:
            tunnel_config (dict[str, Any]): ``infrastructure.tunnel`` sub-dict.
            confirm (bool): Must be True — explicit caller acknowledgement.

        Returns:
            TunnelStatus: State after teardown (healthy=False).

        Raises:
            ValueError: When ``confirm`` is False.

        Examples:
            >>> TunnelManager().stop({"mode": "none"}, confirm=False)
            Traceback (most recent call last):
                ...
            ValueError: confirm=True required to stop the tunnel
        """
        if not confirm:
            raise ValueError("confirm=True required to stop the tunnel")

        if self._process is not None and self._process.poll() is None:
            _stop_popen(self._process)

        self._process = None
        self._started_mode = None

        record = self._read_pid_file_record()
        if record is not None:
            _stop_recorded_tunnel(record)
        else:
            mode = str(tunnel_config.get("mode") or "none")
            if is_tailscale_mode(mode):
                _run_tailscale_stop(mode)

        self._clear_pid_file()
        return self.status(tunnel_config)


#: Module-level singleton; pid file bound once at gateway boot (``http_server``).
default_manager: TunnelManager = TunnelManager()

__all__ = [
    "RUNNABLE_MODES",
    "TunnelManager",
    "TunnelStatus",
    "default_manager",
    "tunnel_pid_file",
]
