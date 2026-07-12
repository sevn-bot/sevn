"""Remote deploy orchestration from export bundles.

Module: sevn.deploy.remote
Depends: os, stat, uuid, pathlib, typing, sevn.deploy.*, sevn.onboarding.export_bundle

Exports:
    DeployMode — check, dry-run, or deploy.
    DeployRunnerError — orchestration failure with CLI exit code.
    RemoteDeployRunner — SSH deploy step machine.
    validate_bundle — parse and permission-check export bundle.
    ValidatedBundle — parsed bundle path + metadata.

Private:
    _shell_quote — single-quote a shell argument.
    _run_check — SSH preflight mode.
    _run_dry_run — plan-only mode.
    _run_deploy — full deploy mode.
"""

from __future__ import annotations

import contextlib
import stat
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from sevn.deploy.inventory import DeployInventory, get_host
from sevn.deploy.report import DeployReport, StepStatus
from sevn.deploy.ssh_runner import SSHCommandError, SSHRunner
from sevn.onboarding.export_bundle import ExportBundle, ExportBundleError, parse_export_text

if TYPE_CHECKING:
    from pathlib import Path

_UNLOCK_ENV_KEYS = ("SEVN_SECRETS_PASSPHRASE", "SEVN_SECRETS_MASTER_KEY")


class DeployMode(StrEnum):
    """Remote deploy execution mode."""

    CHECK = "check"
    DRY_RUN = "dry-run"
    DEPLOY = "deploy"


class DeployRunnerError(RuntimeError):
    """Deploy orchestration failed."""

    def __init__(self, message: str, *, exit_code: int = 4) -> None:
        """Attach CLI exit code to a deploy failure.

        Args:
            message (str): Operator-facing failure text.
            exit_code (int): Typer exit code.

        Examples:
            >>> DeployRunnerError("x").exit_code
            4
        """
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True, slots=True)
class ValidatedBundle:
    """Bundle path plus parsed export metadata."""

    path: Path
    bundle: ExportBundle
    permission_warning: str | None = None


def validate_bundle(path: Path) -> ValidatedBundle:
    """Parse an export bundle and warn on loose permissions.

    Args:
        path (Path): Local ``.env`` bundle path.

    Returns:
        ValidatedBundle: Parsed bundle metadata.

    Raises:
        DeployRunnerError: When the file is missing or invalid.

    Examples:
        >>> from pathlib import Path
        >>> import os
        >>> import tempfile
        >>> text = (
        ...     "SEVN_EXPORT_VERSION=1\\n"
        ...     "SEVN_BOT_NAME=Sevn\\n"
        ...     "config.schema_version=1\\n"
        ...     "config.gateway.port=3001\\n"
        ... )
        >>> with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as handle:
        ...     _ = handle.write(text)
        ...     bundle_path = Path(handle.name)
        >>> os.chmod(bundle_path, 0o600)
        >>> validated = validate_bundle(bundle_path)
        >>> validated.bundle.bot_name
        'Sevn'
    """
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise DeployRunnerError(f"bundle not found: {resolved}", exit_code=2)
    try:
        bundle = parse_export_text(resolved.read_text(encoding="utf-8"))
    except ExportBundleError as exc:
        raise DeployRunnerError(exc.message, exit_code=exc.exit_code) from exc
    mode_bits = stat.S_IMODE(resolved.stat().st_mode)
    warning: str | None = None
    if mode_bits & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH):
        warning = f"bundle permissions are {oct(mode_bits)} — recommended 0600"
    return ValidatedBundle(path=resolved, bundle=bundle, permission_warning=warning)


def _shell_quote(value: str) -> str:
    """Return a single-quoted shell literal.

    Args:
        value (str): Raw argument text.

    Returns:
        str: Shell-safe single-quoted string.

    Examples:
        >>> _shell_quote("abc")
        "'abc'"
    """
    return "'" + value.replace("'", "'\"'\"'") + "'"


class RemoteDeployRunner:
    """Execute remote deploy steps over SSH."""

    def __init__(
        self,
        *,
        inventory: DeployInventory,
        host_id: str,
        mode: DeployMode,
        bundle_path: Path | None = None,
        install_sevn: bool = False,
        force: bool = False,
    ) -> None:
        """Configure a deploy run for one inventory host.

        Args:
            inventory (DeployInventory): Loaded inventory document.
            host_id (str): Host key under ``[hosts.<id>]``.
            mode (DeployMode): Check, dry-run, or deploy execution mode.
            bundle_path (Path | None): Export bundle for deploy modes.
            install_sevn (bool): Reserved remote install.sh hook.
            force (bool): Reserved redeploy override flag.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost, DeployInventory
            >>> inv = DeployInventory(
            ...     path=Path("x.toml"),
            ...     hosts={
            ...         "staging": DeployHost(
            ...             host_id="staging",
            ...             host="h",
            ...             user="u",
            ...             identity_file=Path("/tmp/id"),
            ...             remote_home="/home/u/.sevn",
            ...         )
            ...     },
            ... )
            >>> RemoteDeployRunner(
            ...     inventory=inv, host_id="staging", mode=DeployMode.CHECK
            ... ).report.mode
            'check'
        """
        self._inventory = inventory
        self._host = get_host(inventory, host_id)
        self._mode = mode
        self._bundle_path = bundle_path
        self._install_sevn = install_sevn
        self._force = force
        _ = (self._install_sevn, self._force)
        self._runner = SSHRunner(host=self._host, dry_run=mode is DeployMode.DRY_RUN)
        self._report = DeployReport(
            host_id=host_id,
            bundle_path=str(bundle_path) if bundle_path else "",
            bot_name="",
            mode=mode.value,
        )

    @property
    def report(self) -> DeployReport:
        """Return the in-memory deploy report.

        Returns:
            DeployReport: Mutable report accumulator.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost, DeployInventory
            >>> inv = DeployInventory(
            ...     path=Path("x.toml"),
            ...     hosts={
            ...         "staging": DeployHost(
            ...             host_id="staging",
            ...             host="h",
            ...             user="u",
            ...             identity_file=Path("/tmp/id"),
            ...             remote_home="/home/u/.sevn",
            ...         )
            ...     },
            ... )
            >>> runner = RemoteDeployRunner(
            ...     inventory=inv, host_id="staging", mode=DeployMode.DRY_RUN
            ... )
            >>> runner.report.mode
            'dry-run'
        """
        return self._report

    @property
    def planned_commands(self) -> list[tuple[str, ...]]:
        """Return ssh/scp argv tuples planned during dry-run.

        Returns:
            list[tuple[str, ...]]: Planned commands in execution order.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost, DeployInventory
            >>> inv = DeployInventory(
            ...     path=Path("x.toml"),
            ...     hosts={
            ...         "staging": DeployHost(
            ...             host_id="staging",
            ...             host="h",
            ...             user="u",
            ...             identity_file=Path("/tmp/id"),
            ...             remote_home="/home/u/.sevn",
            ...         )
            ...     },
            ... )
            >>> runner = RemoteDeployRunner(
            ...     inventory=inv, host_id="staging", mode=DeployMode.DRY_RUN
            ... )
            >>> runner.planned_commands
            []
        """
        return self._runner.planned_commands

    def run(self) -> DeployReport:
        """Execute the configured mode.

        Returns:
            DeployReport: Outcome report (also on ``self.report``).

        Raises:
            DeployRunnerError: On fatal preflight failures in check/deploy modes.

        Examples:
            >>> from pathlib import Path
            >>> import os
            >>> import tempfile
            >>> from sevn.deploy.inventory import DeployHost, DeployInventory
            >>> text = (
            ...     "SEVN_EXPORT_VERSION=1\\n"
            ...     "SEVN_BOT_NAME=Sevn\\n"
            ...     "config.schema_version=1\\n"
            ...     "config.gateway.port=3001\\n"
            ... )
            >>> with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as handle:
            ...     _ = handle.write(text)
            ...     bundle_path = Path(handle.name)
            >>> os.chmod(bundle_path, 0o600)
            >>> inv = DeployInventory(
            ...     path=Path("inventory.toml"),
            ...     hosts={
            ...         "staging": DeployHost(
            ...             host_id="staging",
            ...             host="203.0.113.10",
            ...             user="sevn",
            ...             identity_file=Path("/tmp/id"),
            ...             remote_home="/home/sevn/.sevn",
            ...         )
            ...     },
            ... )
            >>> runner = RemoteDeployRunner(
            ...     inventory=inv,
            ...     host_id="staging",
            ...     mode=DeployMode.DRY_RUN,
            ...     bundle_path=bundle_path,
            ... )
            >>> report = runner.run()
            >>> report.mode
            'dry-run'
        """
        if self._mode is DeployMode.CHECK:
            self._run_check()
        elif self._mode is DeployMode.DRY_RUN:
            self._run_dry_run()
        else:
            self._run_deploy()
        self._report.remote.setdefault("sevn_home", self._host.remote_home)
        return self._report

    def _run_check(self) -> None:
        """Run SSH preflight and remote ``sevn`` discovery steps.

        Examples:
            >>> RemoteDeployRunner._run_check  # doctest: +SKIP
        """
        try:
            result = self._runner.ssh_preflight()
            self._report.add_step("preflight", status="ok", duration_ms=result.duration_ms)
        except SSHCommandError as exc:
            self._report.add_step("preflight", status="failed", detail=str(exc))
            self._report.fail(str(exc))
            raise DeployRunnerError(str(exc), exit_code=4) from exc
        try:
            which = self._runner.remote_which_sevn()
            self._report.add_step("remote_sevn", status="ok", detail=which.stdout.strip())
        except SSHCommandError as exc:
            self._report.add_step("remote_sevn", status="failed", detail=str(exc))
            self._report.fail("remote sevn not found — install sevn on the host first")
            raise DeployRunnerError(self._report.errors[-1], exit_code=4) from exc
        version = self._runner.remote_sevn_version()
        self._report.remote["sevn_version"] = version.stdout.strip()
        self._report.add_step("remote_version", status="ok", detail=version.stdout.strip())
        disk = self._runner.remote_disk_hint()
        self._report.add_step("disk_hint", status="ok", detail=disk.stdout.strip())

    def _run_dry_run(self) -> None:
        """Record planned ssh/scp steps without executing them.

        Examples:
            >>> RemoteDeployRunner._run_dry_run  # doctest: +SKIP
        """
        if self._bundle_path is None:
            raise DeployRunnerError("dry-run requires --bundle", exit_code=2)
        validated = validate_bundle(self._bundle_path)
        self._report.bot_name = validated.bundle.bot_name
        if validated.permission_warning:
            self._report.add_step(
                "bundle_permissions",
                status="planned",
                detail=validated.permission_warning,
            )
        self._report.add_step("bundle_validate", status="planned")
        remote_tmp = f"/tmp/sevn-deploy-{uuid.uuid4().hex}.env"  # nosec B108 — remote VPS temp path per deploy plan
        self._runner.scp_upload(validated.path, remote_tmp)
        self._report.add_step("scp_bundle", status="planned", remote_path=remote_tmp)
        onboard_cmd = (
            f"SEVN_HOME={_shell_quote(self._host.remote_home)} "
            f"sevn onboard fast {_shell_quote(remote_tmp)}"
        )
        self._runner.ssh_exec(onboard_cmd)
        self._report.add_step("remote_onboard_fast", status="planned", command=onboard_cmd)
        self._runner.ssh_exec(
            f"SEVN_HOME={_shell_quote(self._host.remote_home)} sevn gateway install"
        )
        self._runner.ssh_exec(
            f"SEVN_HOME={_shell_quote(self._host.remote_home)} sevn proxy install"
        )
        self._report.add_step("remote_unit_install", status="planned")
        self._runner.ssh_exec(
            f"SEVN_HOME={_shell_quote(self._host.remote_home)} sevn gateway start"
        )
        self._runner.ssh_exec(f"SEVN_HOME={_shell_quote(self._host.remote_home)} sevn proxy start")
        self._report.add_step("remote_unit_start", status="planned")
        gw_url = f"http://127.0.0.1:{self._host.gateway_port}/healthz"
        px_url = f"http://127.0.0.1:{self._host.proxy_port}/healthz"
        self._runner.ssh_exec(f"curl -sf {_shell_quote(gw_url)}")
        self._runner.ssh_exec(f"curl -sf {_shell_quote(px_url)}")
        self._report.add_step("health_gateway", status="planned", url=gw_url)
        self._report.add_step("health_proxy", status="planned", url=px_url)
        self._runner.ssh_exec(f"rm -f {_shell_quote(remote_tmp)}")
        self._report.add_step("cleanup", status="planned")

    def _run_deploy(self) -> None:
        """Transfer bundle, onboard remotely, install units, and health-check.

        Examples:
            >>> RemoteDeployRunner._run_deploy  # doctest: +SKIP
        """
        if self._bundle_path is None:
            raise DeployRunnerError("deploy requires --bundle", exit_code=2)
        self._run_check()
        validated = validate_bundle(self._bundle_path)
        self._report.bot_name = validated.bundle.bot_name
        if validated.permission_warning:
            self._report.add_step(
                "bundle_permissions",
                status="ok",
                detail=validated.permission_warning,
            )
        self._report.add_step("bundle_validate", status="ok")
        remote_tmp = f"/tmp/sevn-deploy-{uuid.uuid4().hex}.env"  # nosec B108 — remote VPS temp path per deploy plan
        try:
            scp = self._runner.scp_upload(validated.path, remote_tmp)
            self._report.add_step(
                "scp_bundle",
                status="ok",
                duration_ms=scp.duration_ms,
                remote_path=remote_tmp,
            )
            self._runner.ssh_exec(f"chmod 600 {_shell_quote(remote_tmp)}")
            env_prefix = self._remote_env_for_bundle(validated.bundle.secrets)
            onboard_cmd = (
                f"{env_prefix} sevn onboard fast {_shell_quote(remote_tmp)}"
                if env_prefix
                else f"SEVN_HOME={_shell_quote(self._host.remote_home)} "
                f"sevn onboard fast {_shell_quote(remote_tmp)}"
            )
            onboard = self._runner.ssh_exec(onboard_cmd)
            self._report.add_step(
                "remote_onboard_fast",
                status="ok",
                duration_ms=onboard.duration_ms,
            )
            for label, cmd in (
                ("gateway_install", "sevn gateway install"),
                ("proxy_install", "sevn proxy install"),
            ):
                full = (
                    f"{env_prefix} {cmd}"
                    if env_prefix
                    else f"SEVN_HOME={_shell_quote(self._host.remote_home)} {cmd}"
                )
                result = self._runner.ssh_exec(full)
                self._report.add_step(label, status="ok", duration_ms=result.duration_ms)
            self._report.add_step("remote_unit_install", status="ok")
            for label, cmd in (
                ("gateway_start", "sevn gateway start"),
                ("proxy_start", "sevn proxy start"),
            ):
                full = (
                    f"{env_prefix} {cmd}"
                    if env_prefix
                    else f"SEVN_HOME={_shell_quote(self._host.remote_home)} {cmd}"
                )
                result = self._runner.ssh_exec(full)
                self._report.add_step(label, status="ok", duration_ms=result.duration_ms)
            self._report.add_step("remote_unit_start", status="ok")
            self._run_health_checks()
            self._run_remote_doctor(env_prefix)
        except SSHCommandError as exc:
            self._report.fail(str(exc))
            raise DeployRunnerError(str(exc), exit_code=4) from exc
        finally:
            with contextlib.suppress(SSHCommandError):
                self._runner.ssh_exec(f"rm -f {_shell_quote(remote_tmp)}", check=False)
            self._report.add_step("cleanup", status="ok")

    def _remote_env_for_bundle(self, secrets: dict[str, str]) -> str:
        """Build remote env prefix for unlock vars present in the bundle.

        Args:
            secrets (dict[str, str]): Parsed export secrets map.

        Returns:
            str: Space-separated ``KEY='value'`` prefix.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.deploy.inventory import DeployHost, DeployInventory
            >>> inv = DeployInventory(
            ...     path=Path("x.toml"),
            ...     hosts={
            ...         "staging": DeployHost(
            ...             host_id="staging",
            ...             host="h",
            ...             user="u",
            ...             identity_file=Path("/tmp/id"),
            ...             remote_home="/home/u/.sevn",
            ...         )
            ...     },
            ... )
            >>> runner = RemoteDeployRunner(
            ...     inventory=inv, host_id="staging", mode=DeployMode.CHECK
            ... )
            >>> "SEVN_HOME=" in runner._remote_env_for_bundle({})
            True
        """
        parts = [f"SEVN_HOME={_shell_quote(self._host.remote_home)}"]
        for key in _UNLOCK_ENV_KEYS:
            value = secrets.get(key, "").strip()
            if value:
                parts.append(f"{key}={_shell_quote(value)}")
        return " ".join(parts)

    def _run_health_checks(self) -> None:
        """Probe gateway and proxy ``/healthz`` endpoints on the remote host.

        Examples:
            >>> RemoteDeployRunner._run_health_checks  # doctest: +SKIP
        """
        gw_url = f"http://127.0.0.1:{self._host.gateway_port}/healthz"
        px_url = f"http://127.0.0.1:{self._host.proxy_port}/healthz"
        gw = self._runner.ssh_exec(f"curl -sf {_shell_quote(gw_url)}")
        self._report.add_step(
            "health_gateway",
            status="ok",
            duration_ms=gw.duration_ms,
            url=gw_url,
        )
        self._report.remote["gateway_active"] = True
        px = self._runner.ssh_exec(f"curl -sf {_shell_quote(px_url)}")
        self._report.add_step(
            "health_proxy",
            status="ok",
            duration_ms=px.duration_ms,
            url=px_url,
        )
        self._report.remote["proxy_active"] = True

    def _run_remote_doctor(self, env_prefix: str) -> None:
        """Append remote ``sevn doctor --json`` output to the report.

        Args:
            env_prefix (str): Remote env prefix for unlock vars.

        Examples:
            >>> RemoteDeployRunner._run_remote_doctor  # doctest: +SKIP
        """
        cmd = (
            f"{env_prefix} sevn doctor --json"
            if env_prefix
            else f"SEVN_HOME={_shell_quote(self._host.remote_home)} sevn doctor --json"
        )
        result = self._runner.ssh_exec(cmd, check=False)
        detail = result.stdout.strip() or result.stderr.strip()
        doctor_status: StepStatus = "ok" if result.exit_code == 0 else "failed"
        self._report.add_step(
            "remote_doctor",
            status=doctor_status,
            duration_ms=result.duration_ms,
            detail=detail[:500] if detail else None,
        )
