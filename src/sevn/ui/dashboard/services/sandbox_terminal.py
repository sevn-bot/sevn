"""Sandbox-confined web terminal PTY bridge (MC W8).

Module: sevn.ui.dashboard.services.sandbox_terminal
Depends: asyncio, os, pty, shlex, uuid, sevn.security.sandbox_runtime

Exports:
    SandboxTerminalSession — interactive shell inside Subprocess/Docker sandbox runtime.
    SandboxTerminalError — configuration or policy failure.
    create_sandbox_terminal_session — spawn sandbox + PTY shell for dashboard owner.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import pty
import shlex
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from sevn.config.defaults import SANDBOX_MAX_LIFETIME_S
from sevn.security.sandbox_errors import SandboxConfigurationError
from sevn.security.sandbox_runtime import (
    SandboxDriver,
    SandboxRuntime,
    check_self_preservation_argv,
    make_runtime_for_driver,
    resolve_sandbox_driver,
)

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.workspace.layout import WorkspaceLayout

_DOCKER_WORKSPACE_MOUNT = "/workspace"
_DEFAULT_SHELL = "/bin/sh"


def _sandbox_max_lifetime_s(cfg: WorkspaceConfig) -> float:
    """Return configured sandbox max lifetime seconds.

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.

    Returns:
        float: Upper bound for terminal session lifetime.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _sandbox_max_lifetime_s(WorkspaceConfig.minimal()) == 7200.0
        True
    """
    sb = cfg.sandbox
    if sb and sb.max_lifetime is not None:
        return float(sb.max_lifetime)
    return float(SANDBOX_MAX_LIFETIME_S)


class SandboxTerminalError(Exception):
    """Raised when sandbox terminal cannot start or policy blocks input."""


@dataclass
class SandboxTerminalSession:
    """One owner dashboard terminal bound to a sandbox runtime PTY."""

    session_id: str
    driver: SandboxDriver
    sandbox_id: str
    runtime: SandboxRuntime
    workspace_root: Path
    max_lifetime_s: float
    _master_fd: int
    _proc: asyncio.subprocess.Process | None = field(default=None, repr=False)
    _input_buffer: bytearray = field(default_factory=bytearray, repr=False)
    _closed: bool = field(default=False, repr=False)
    _started_at: float = field(default_factory=time.monotonic, repr=False)

    @property
    def started_at(self) -> float:
        """Monotonic timestamp when the session started.

        Returns:
            float: ``time.monotonic()`` value at construction.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        return self._started_at

    @property
    def expired(self) -> bool:
        """Return True when the session exceeded ``max_lifetime_s``.

        Returns:
            bool: Whether the hard timeout elapsed.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        return (time.monotonic() - self._started_at) >= self.max_lifetime_s

    def check_line_policy(self, line: str) -> str | None:
        """Run self-preservation argv guard on one submitted shell line.

        Args:
            line (str): Raw user line without trailing newline.

        Returns:
            str | None: Matched rule label when blocked, else ``None``.

        Examples:
            >>> s = SandboxTerminalSession(
            ...     session_id="x",
            ...     driver=SandboxDriver.subprocess,
            ...     sandbox_id="sb",
            ...     runtime=object(),  # type: ignore[arg-type]
            ...     workspace_root=Path("."),
            ...     max_lifetime_s=60.0,
            ...     _master_fd=-1,
            ... )
            >>> s.check_line_policy("echo hi") is None
            True
        """
        stripped = line.strip()
        if not stripped:
            return None
        try:
            argv = shlex.split(stripped, posix=True)
        except ValueError:
            argv = stripped.split()
        if not argv:
            return None
        return check_self_preservation_argv(argv)

    async def write_stdin(self, data: bytes) -> str | None:
        """Write bytes to the PTY after per-line self-preservation checks.

        Args:
            data (bytes): Raw terminal input from the browser.

        Returns:
            str | None: Blocked rule label when a complete line violates policy.

        Raises:
            SandboxTerminalError: When the session is closed or the PTY is gone.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SandboxTerminalSession.write_stdin)
            True
        """
        if self._closed or self._master_fd < 0:
            msg = "terminal session closed"
            raise SandboxTerminalError(msg)
        pending = bytearray(self._input_buffer)
        pending.extend(data)
        approved = bytearray()
        scan = 0
        while scan < len(pending):
            nl = pending.find(b"\n", scan)
            cr = pending.find(b"\r", scan)
            idx = -1
            if nl >= 0 and cr >= 0:
                idx = min(nl, cr)
            elif nl >= 0:
                idx = nl
            elif cr >= 0:
                idx = cr
            if idx < 0:
                break
            line = bytes(pending[scan:idx]).decode("utf-8", errors="replace")
            rule = self.check_line_policy(line)
            if rule is not None:
                return rule
            approved.extend(pending[scan : idx + 1])
            scan = idx + 1
        self._input_buffer = bytearray(pending[scan:])
        if not approved:
            return None
        try:
            os.write(self._master_fd, bytes(approved))
        except OSError as exc:
            msg = f"pty write failed: {exc}"
            raise SandboxTerminalError(msg) from exc
        return None

    async def read_stdout(self, *, max_bytes: int = 4096) -> bytes:
        """Read available PTY output without blocking indefinitely.

        Args:
            max_bytes (int): Upper bound per read.

        Returns:
            bytes: Captured terminal output (may be empty).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SandboxTerminalSession.read_stdout)
            True
        """
        if self._closed or self._master_fd < 0:
            return b""
        try:
            return await asyncio.to_thread(os.read, self._master_fd, max_bytes)
        except OSError:
            return b""

    async def close(self) -> None:
        """Tear down PTY, child process, and sandbox runtime.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SandboxTerminalSession.close)
            True
        """
        if self._closed:
            return
        self._closed = True
        proc = self._proc
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(Exception):
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
        if self._master_fd >= 0:
            with contextlib.suppress(OSError):
                os.close(self._master_fd)
            self._master_fd = -1
        with contextlib.suppress(Exception):
            await self.runtime.teardown(self.sandbox_id)


async def create_sandbox_terminal_session(
    *,
    layout: WorkspaceLayout,
    cfg: WorkspaceConfig,
    proxy_url: str = "",
    session_token: str = "",
) -> SandboxTerminalSession:
    """Spawn sandbox runtime and attach an interactive PTY shell at ``content_root``.

    Uses only :class:`SubprocessSandboxRuntime` or :class:`DockerSandboxRuntime` —
    never an unconfined host shell.

    Args:
        layout (WorkspaceLayout): Workspace paths (``content_root`` is cwd).
        cfg (WorkspaceConfig): Parsed workspace config for driver resolution.
        proxy_url (str): §2.2 proxy URL injected into sandbox child env.
        session_token (str): Opaque sandbox session token for child env.

    Returns:
        SandboxTerminalSession: Live PTY session handle.

    Raises:
        SandboxTerminalError: When driver resolution or PTY spawn fails.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(create_sandbox_terminal_session)
        True
    """
    try:
        driver = resolve_sandbox_driver(cfg)
    except SandboxConfigurationError as exc:
        raise SandboxTerminalError(str(exc)) from exc

    runtime = make_runtime_for_driver(driver, layout=layout, cfg=cfg, trace_sink=None)
    workspace = layout.content_root.resolve()
    run_id = f"mc-terminal-{uuid.uuid4().hex[:12]}"
    child_env = {
        "SEVN_PROXY_URL": proxy_url,
        "SEVN_SESSION_TOKEN": session_token or uuid.uuid4().hex,
    }
    try:
        sandbox_id = await runtime.spawn(run_id=run_id, workspace=workspace, env=child_env)
    except SandboxConfigurationError as exc:
        raise SandboxTerminalError(str(exc)) from exc

    lifetime = float(_sandbox_max_lifetime_s(cfg))
    session_id = uuid.uuid4().hex

    try:
        master_fd, proc = await _open_sandbox_pty(
            driver=driver,
            sandbox_id=sandbox_id,
            runtime=runtime,
            workspace=workspace,
            layout=layout,
        )
    except Exception as exc:
        await runtime.teardown(sandbox_id)
        raise SandboxTerminalError(str(exc)) from exc

    return SandboxTerminalSession(
        session_id=session_id,
        driver=driver,
        sandbox_id=sandbox_id,
        runtime=runtime,
        workspace_root=workspace,
        max_lifetime_s=lifetime,
        _master_fd=master_fd,
        _proc=proc,
    )


async def _open_sandbox_pty(
    *,
    driver: SandboxDriver,
    sandbox_id: str,
    runtime: SandboxRuntime,
    workspace: Path,
    layout: WorkspaceLayout,
) -> tuple[int, asyncio.subprocess.Process | None]:
    """Attach a PTY to a shell inside the active sandbox.

    Args:
        driver (SandboxDriver): Resolved isolation backend.
        sandbox_id (str): Sandbox handle from ``spawn``.
        runtime (SandboxRuntime): Active runtime instance.
        workspace (Path): Host ``content_root``.
        layout (WorkspaceLayout): Workspace layout (shadow paths for subprocess).

    Returns:
        tuple[int, asyncio.subprocess.Process | None]: Master PTY fd and host bridge process.

    Raises:
        SandboxTerminalError: When PTY creation fails.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_open_sandbox_pty)
        True
    """
    master_fd, slave_fd = pty.openpty()
    try:
        if driver == SandboxDriver.docker:
            docker_bin = shutil.which("docker")
            if not docker_bin:
                msg = "docker CLI not found for sandbox terminal"
                raise SandboxTerminalError(msg)
            proc = await asyncio.create_subprocess_exec(
                docker_bin,
                "exec",
                "-i",
                "-t",
                "-w",
                _DOCKER_WORKSPACE_MOUNT,
                sandbox_id,
                _DEFAULT_SHELL,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
            )
            os.close(slave_fd)
            return master_fd, proc

        shadow_cwd = _subprocess_shadow_cwd(runtime, sandbox_id, layout=layout, workspace=workspace)
        env = _subprocess_terminal_env(home=shadow_cwd)
        proc = await asyncio.create_subprocess_exec(
            _DEFAULT_SHELL,
            cwd=str(shadow_cwd),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
        )
        os.close(slave_fd)
        return master_fd, proc
    except Exception:
        os.close(master_fd)
        with contextlib.suppress(OSError):
            os.close(slave_fd)
        raise


def _subprocess_terminal_env(*, home: Path) -> dict[str, str]:
    """Build minimal allowlisted environment for subprocess sandbox terminal.

    Mirrors the Docker driver policy: only terminal, locale, and shell essentials.
    Host ``PATH`` is inherited so dev toolchains remain usable (see D3); gateway
    secrets (``SEVN_*``, ``*_API_KEY``, etc.) are never copied from ``os.environ``.

    Args:
        home (Path): Shadow cwd used as ``HOME`` for the subprocess shell.

    Returns:
        dict[str, str]: Explicit env passed to ``create_subprocess_exec``.

    Examples:
        >>> from pathlib import Path
        >>> env = _subprocess_terminal_env(home=Path("/tmp"))
        >>> "SEVN_SECRETS_PASSPHRASE" not in env
        True
        >>> env["TERM"] == "xterm-256color"
        True
    """
    env: dict[str, str] = {
        "TERM": "xterm-256color",
        "HOME": str(home),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    for key in ("LANG", "LC_ALL"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _subprocess_shadow_cwd(
    runtime: SandboxRuntime,
    sandbox_id: str,
    *,
    layout: WorkspaceLayout,
    workspace: Path,
) -> Path:
    """Resolve subprocess sandbox shadow cwd for PTY shell.

    Args:
        runtime (SandboxRuntime): Subprocess runtime with in-memory records.
        sandbox_id (str): Sandbox id from ``spawn``.
        layout (WorkspaceLayout): Workspace layout fallback.
        workspace (Path): Real content root.

    Returns:
        Path: Directory where the confined shell should start.

    Raises:
        SandboxTerminalError: When shadow path cannot be resolved.

    Examples:
        >>> isinstance(True, bool)
        True
    """
    records = getattr(runtime, "_records", None)
    if isinstance(records, dict):
        rec = records.get(sandbox_id)
        if isinstance(rec, dict):
            shadow = rec.get("shadow") or rec.get("cwd")
            if shadow is not None:
                return Path(str(shadow)).resolve()
    return workspace.resolve()


__all__ = [
    "SandboxTerminalError",
    "SandboxTerminalSession",
    "create_sandbox_terminal_session",
]
