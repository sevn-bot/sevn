"""Subprocess ssh/scp helpers for remote deploy (BatchMode only).

Module: sevn.deploy.ssh_runner
Depends: subprocess, pathlib, typing, sevn.deploy.inventory

Exports:
    SSHCommandError — non-zero ssh/scp exit with captured output.
    SSHRunner — stdlib ssh/scp backend.
    SSHResult — command outcome with stdout/stderr/duration.

Private:
    _ssh_target — ``user@host`` target string.
    _ssh_argv — build ssh argv for a remote command.
    _scp_argv — build scp argv for an upload.
"""

from __future__ import annotations

import subprocess  # nosec B404
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sevn.deploy.inventory import DeployHost


class SSHCommandError(RuntimeError):
    """Remote command failed."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        """Attach stderr/stdout captured from a failed remote command.

        Args:
            message (str): Operator-facing failure text.
            exit_code (int): ssh/scp exit code.
            stdout (str): Captured stdout.
            stderr (str): Captured stderr.

        Examples:
            >>> err = SSHCommandError("fail", exit_code=255)
            >>> err.exit_code
            255
        """
        super().__init__(message)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


@dataclass(frozen=True, slots=True)
class SSHResult:
    """Outcome of one ssh/scp invocation."""

    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


class SSHRunner:
    """Execute ssh/scp against a deploy host using system binaries."""

    def __init__(self, *, host: DeployHost, dry_run: bool = False) -> None:
        """Bind a deploy host and optional dry-run transcript mode.

        Args:
            host (DeployHost): Target host entry.
            dry_run (bool): Record planned commands without subprocess I/O.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost
            >>> SSHRunner(
            ...     host=DeployHost(
            ...         host_id="x",
            ...         host="h",
            ...         user="u",
            ...         identity_file=Path("/tmp/id"),
            ...         remote_home="/home/u/.sevn",
            ...     ),
            ...     dry_run=True,
            ... ).planned_commands
            []
        """
        self._host = host
        self._dry_run = dry_run
        self.planned_commands: list[tuple[str, ...]] = []

    def _ssh_target(self) -> str:
        """Return the ssh ``user@host`` target.

        Returns:
            str: Target string for ssh/scp.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost
            >>> runner = SSHRunner(
            ...     host=DeployHost(
            ...         host_id="x",
            ...         host="203.0.113.10",
            ...         user="sevn",
            ...         identity_file=Path("/tmp/id"),
            ...         remote_home="/home/sevn/.sevn",
            ...     )
            ... )
            >>> runner._ssh_target()
            'sevn@203.0.113.10'
        """
        return f"{self._host.user}@{self._host.host}"

    def _ssh_argv(self, remote_command: str) -> list[str]:
        """Build argv for ``ssh BatchMode`` remote execution.

        Args:
            remote_command (str): Remote shell command.

        Returns:
            list[str]: Local ssh argv.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost
            >>> runner = SSHRunner(
            ...     host=DeployHost(
            ...         host_id="x",
            ...         host="h",
            ...         user="u",
            ...         identity_file=Path("/tmp/id"),
            ...         remote_home="/home/u/.sevn",
            ...     )
            ... )
            >>> runner._ssh_argv("echo ok")[0]
            'ssh'
        """
        identity = str(self._host.identity_file)
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-i",
            identity,
            self._ssh_target(),
            remote_command,
        ]

    def _scp_argv(self, local_path: Path, remote_path: str) -> list[str]:
        """Build argv for ``scp BatchMode`` upload.

        Args:
            local_path (Path): Local source file.
            remote_path (str): Remote destination path.

        Returns:
            list[str]: Local scp argv.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost
            >>> runner = SSHRunner(
            ...     host=DeployHost(
            ...         host_id="x",
            ...         host="h",
            ...         user="u",
            ...         identity_file=Path("/tmp/id"),
            ...         remote_home="/home/u/.sevn",
            ...     )
            ... )
            >>> runner._scp_argv(Path("/tmp/b.env"), "/tmp/remote.env")[0]
            'scp'
        """
        identity = str(self._host.identity_file)
        return [
            "scp",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-i",
            identity,
            str(local_path),
            f"{self._ssh_target()}:{remote_path}",
        ]

    def run(
        self,
        argv: Sequence[str],
        *,
        check: bool = True,
        input_text: str | None = None,
    ) -> SSHResult:
        """Run a local argv list (ssh/scp).

        Args:
            argv (Sequence[str]): Command argv.
            check (bool): Raise :class:`SSHCommandError` on non-zero exit.
            input_text (str | None): Optional stdin payload.

        Returns:
            SSHResult: Captured outcome.

        Raises:
            SSHCommandError: When ``check`` is True and exit code is non-zero.

        Examples:
            >>> runner = SSHRunner(host=__import__("sevn.deploy.inventory", fromlist=["DeployHost"]).DeployHost(
            ...     host_id="x", host="h", user="u", identity_file=Path("/tmp/id"), remote_home="/home/u/.sevn"
            ... ), dry_run=True)
            >>> result = runner.run(["echo", "ok"], check=False)
            >>> result.exit_code
            0
        """
        cmd = tuple(str(part) for part in argv)
        self.planned_commands.append(cmd)
        if self._dry_run:
            return SSHResult(command=cmd, exit_code=0, stdout="", stderr="", duration_ms=0)
        started = time.monotonic()
        proc = subprocess.run(  # nosec B603
            list(cmd),
            capture_output=True,
            text=True,
            input=input_text,
            check=False,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        result = SSHResult(
            command=cmd,
            exit_code=int(proc.returncode),
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            duration_ms=duration_ms,
        )
        if check and result.exit_code != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.exit_code}"
            raise SSHCommandError(
                f"command failed: {' '.join(cmd)} — {detail}",
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result

    def ssh_exec(self, remote_command: str, *, check: bool = True) -> SSHResult:
        """Run one remote shell command via ssh.

        Args:
            remote_command (str): Remote shell command string.
            check (bool): Raise on non-zero exit.

        Returns:
            SSHResult: Captured outcome.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost
            >>> host = DeployHost(
            ...     host_id="x", host="h", user="u", identity_file=Path("/tmp/id"), remote_home="/home/u/.sevn"
            ... )
            >>> runner = SSHRunner(host=host, dry_run=True)
            >>> runner.ssh_exec("echo ok").exit_code
            0
        """
        return self.run(self._ssh_argv(remote_command), check=check)

    def scp_upload(self, local_path: Path, remote_path: str, *, check: bool = True) -> SSHResult:
        """Upload a local file via scp.

        Args:
            local_path (Path): Local source path.
            remote_path (str): Remote destination path.
            check (bool): Raise on non-zero exit.

        Returns:
            SSHResult: Captured outcome.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost
            >>> host = DeployHost(
            ...     host_id="x", host="h", user="u", identity_file=Path("/tmp/id"), remote_home="/home/u/.sevn"
            ... )
            >>> runner = SSHRunner(host=host, dry_run=True)
            >>> runner.scp_upload(Path("/tmp/b.env"), "/tmp/remote.env").exit_code
            0
        """
        return self.run(self._scp_argv(local_path, remote_path), check=check)

    def ssh_preflight(self) -> SSHResult:
        """Verify BatchMode SSH connectivity.

        Returns:
            SSHResult: ``echo sevn-deploy-ok`` outcome.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost
            >>> host = DeployHost(
            ...     host_id="x", host="h", user="u", identity_file=Path("/tmp/id"), remote_home="/home/u/.sevn"
            ... )
            >>> SSHRunner(host=host, dry_run=True).ssh_preflight().stdout
            ''
        """
        return self.ssh_exec("echo sevn-deploy-ok")

    def remote_which_sevn(self) -> SSHResult:
        """Locate remote ``sevn`` binary.

        Returns:
            SSHResult: ``which sevn`` outcome.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost
            >>> host = DeployHost(
            ...     host_id="x", host="h", user="u", identity_file=Path("/tmp/id"), remote_home="/home/u/.sevn"
            ... )
            >>> SSHRunner(host=host, dry_run=True).remote_which_sevn().exit_code
            0
        """
        return self.ssh_exec("command -v sevn || which sevn")

    def remote_sevn_version(self) -> SSHResult:
        """Read remote ``sevn --version``.

        Returns:
            SSHResult: Version string on stdout.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost
            >>> host = DeployHost(
            ...     host_id="x", host="h", user="u", identity_file=Path("/tmp/id"), remote_home="/home/u/.sevn"
            ... )
            >>> SSHRunner(host=host, dry_run=True).remote_sevn_version().exit_code
            0
        """
        return self.ssh_exec("sevn --version 2>/dev/null || sevn version")

    def remote_disk_hint(self) -> SSHResult:
        """Return remote free disk space for remote home parent.

        Returns:
            SSHResult: ``df -h`` snippet.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost
            >>> host = DeployHost(
            ...     host_id="x", host="h", user="u", identity_file=Path("/tmp/id"), remote_home="/home/u/.sevn"
            ... )
            >>> SSHRunner(host=host, dry_run=True).remote_disk_hint().exit_code
            0
        """
        parent = str(Path(self._host.remote_home).parent)
        return self.ssh_exec(f"df -h {parent} 2>/dev/null | tail -n 1")
