"""launchd/systemd unit install and control (`specs/23-cli.md` §4.2, `prd/06`).

Exports:
    ServiceManagerError — install or control preflight failure.
    InstallPlan — planned unit paths for gateway + proxy.
    plan_install — resolve platform-specific unit paths.
    install_paired_units — write gateway + proxy user units.
    unit_file_exists — whether a sevn-managed unit file is on disk.
    unit_is_active — platform probe for gateway or proxy user unit.
    both_units_installed_and_active — gateway and proxy present and active.
    stop_paired_units — best-effort stop of gateway + proxy user units.
    remove_paired_unit_files — delete sevn-managed unit files from disk.
    control_unit — start/stop/restart/status via launchctl or systemd --user.
    propagate_daemon_secret_env — pass unlock env from shell into user session.
    propagate_daemon_proxy_env — publish ``SEVN_PROXY_URL`` into user session.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sevn.cli.uvicorn_argv import uvicorn_program_argv
from sevn.config.loader import operator_home_dir

ServiceName = Literal["gateway", "proxy"]
ServiceAction = Literal["start", "stop", "restart", "status"]
_DAEMON_SECRET_ENV_KEYS: tuple[str, ...] = ("SEVN_SECRETS_PASSPHRASE", "SEVN_SECRETS_MASTER_KEY")


class ServiceManagerError(RuntimeError):
    """Service unit install or control failed."""


@dataclass(frozen=True, slots=True)
class InstallPlan:
    """Planned unit paths for gateway and proxy."""

    gateway_unit_path: Path
    proxy_unit_path: Path
    platform: str


def _launchd_paths(home: Path) -> InstallPlan:
    """Return launchd plist paths under ``~/Library/LaunchAgents``.

    Args:
        home (Path): Operator home directory.

    Returns:
        InstallPlan: Gateway and proxy plist paths.

    Examples:
        >>> p = _launchd_paths(Path("/tmp/h"))
        >>> p.platform
        'launchd'
    """
    agents = home / "Library" / "LaunchAgents"
    return InstallPlan(
        gateway_unit_path=agents / "ai.sevn.gateway.plist",
        proxy_unit_path=agents / "ai.sevn.proxy.plist",
        platform="launchd",
    )


def _systemd_paths(home: Path) -> InstallPlan:
    """Return systemd user unit paths under ``~/.config/systemd/user``.

    Args:
        home (Path): Operator home directory.

    Returns:
        InstallPlan: Gateway and proxy unit paths.

    Examples:
        >>> p = _systemd_paths(Path("/tmp/h"))
        >>> p.platform
        'systemd'
    """
    units = home / ".config" / "systemd" / "user"
    return InstallPlan(
        gateway_unit_path=units / "sevn-gateway.service",
        proxy_unit_path=units / "sevn-proxy.service",
        platform="systemd",
    )


def plan_install(home: Path) -> InstallPlan:
    """Return unit paths for the current OS.

    Args:
        home (Path): Operator home directory.

    Returns:
        InstallPlan: Target plist/unit paths.

    Raises:
        ServiceManagerError: When the OS is unsupported.

    Examples:
        >>> plan = plan_install(Path("/tmp/home"))
        >>> plan.platform in ("launchd", "systemd")
        True
    """
    system = sys.platform
    if system == "darwin":
        return _launchd_paths(home)
    if system.startswith("linux"):
        return _systemd_paths(home)
    msg = f"service manager install unsupported on {system!r}"
    raise ServiceManagerError(msg)


def _unit_path(plan: InstallPlan, service: ServiceName) -> Path:
    """Resolve one service unit path from an install plan.

    Args:
        plan (InstallPlan): Planned gateway/proxy paths.
        service (ServiceName): ``gateway`` or ``proxy``.

    Returns:
        Path: Unit file path for the service.

    Examples:
        >>> plan = _launchd_paths(Path("/tmp/h"))
        >>> _unit_path(plan, "gateway").name
        'ai.sevn.gateway.plist'
    """
    if service == "gateway":
        return plan.gateway_unit_path
    return plan.proxy_unit_path


def _launchd_label(path: Path) -> str:
    """Derive launchd label from plist filename stem.

    Args:
        path (Path): Plist path.

    Returns:
        str: Label string (filename without extension).

    Examples:
        >>> _launchd_label(Path("ai.sevn.gateway.plist"))
        'ai.sevn.gateway'
    """
    return path.stem


def _render_launchd_plist(
    *,
    label: str,
    module: str,
    port: int,
    operator_home: Path,
    working_directory: Path | None = None,
    log_basename: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> str:
    """Render a minimal launchd plist for one uvicorn service.

    Args:
        label (str): launchd label key.
        module (str): Uvicorn module or factory target.
        port (int): Listen port.
        operator_home (Path): ``SEVN_HOME`` for the gateway/proxy process.
        working_directory (Path | None, optional): ``WorkingDirectory``; defaults to
            ``{operator_home}/workspace`` for the gateway factory app.
        log_basename (str | None, optional): Active log filename under ``logs/``; sets
            stdout/stderr paths and ``SEVN_SERVICE_LOG`` when provided.
        extra_env (dict[str, str] | None, optional): Additional ``EnvironmentVariables`` entries.

    Returns:
        str: Plist XML body.

    Examples:
        >>> home = Path("/tmp/op")
        >>> xml = _render_launchd_plist(
        ...     label="ai.sevn.gateway",
        ...     module="m:create_app",
        ...     port=3001,
        ...     operator_home=home,
        ... )
        >>> "SEVN_HOME" in xml and "3001" in xml
        True
    """
    args = uvicorn_program_argv(
        module=module,
        host="127.0.0.1",
        port=port,
        factory=module.endswith(":create_app"),
    )
    arg_xml = "\n".join(f"        <string>{a}</string>" for a in args)
    workdir = working_directory if working_directory is not None else operator_home / "workspace"
    log_block = ""
    service_log_env = ""
    if log_basename:
        service = log_basename.removesuffix(".log")
        log_path = operator_home / "workspace" / "logs" / log_basename
        log_block = f"""
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>"""
        service_log_env = f"""
        <key>SEVN_SERVICE_LOG</key>
        <string>{service}</string>"""
    elif "gateway" in label:
        log_path = operator_home / "workspace" / "logs" / "gateway.log"
        log_block = f"""
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>"""
    extra_env_block = ""
    for key, val in (extra_env or {}).items():
        extra_env_block += f"""
        <key>{key}</key>
        <string>{val}</string>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{arg_xml}
    </array>
    <key>WorkingDirectory</key>
    <string>{workdir}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>SEVN_HOME</key>
        <string>{operator_home}</string>{service_log_env}{extra_env_block}
    </dict>{log_block}
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""


def _render_systemd_unit(
    *,
    description: str,
    module: str,
    port: int,
    operator_home: Path,
    working_directory: Path | None = None,
    log_basename: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> str:
    """Render a minimal systemd user unit for one uvicorn service.

    Args:
        description (str): Unit description field.
        module (str): Uvicorn module or factory target.
        port (int): Listen port.
        operator_home (Path): ``SEVN_HOME`` for the service process.
        working_directory (Path | None, optional): ``WorkingDirectory``; defaults to
            ``{operator_home}/workspace`` for the gateway factory app.
        log_basename (str | None, optional): Active log filename under ``logs/``; sets
            stdout/stderr paths and ``SEVN_SERVICE_LOG`` when provided.
        extra_env (dict[str, str] | None, optional): Additional ``Environment=`` lines.

    Returns:
        str: systemd unit file body.

    Examples:
        >>> home = Path("/tmp/op")
        >>> body = _render_systemd_unit(
        ...     description="g",
        ...     module="m:create_app",
        ...     port=3001,
        ...     operator_home=home,
        ... )
        >>> "SEVN_HOME=/tmp/op" in body
        True
    """
    workdir = working_directory if working_directory is not None else operator_home / "workspace"
    log_lines = ""
    env_lines = f"Environment=SEVN_HOME={operator_home}\n"
    for key, val in (extra_env or {}).items():
        env_lines += f"Environment={key}={val}\n"
    if log_basename:
        service = log_basename.removesuffix(".log")
        log_path = operator_home / "workspace" / "logs" / log_basename
        log_lines = f"StandardOutput=append:{log_path}\nStandardError=append:{log_path}\n"
        env_lines += f"Environment=SEVN_SERVICE_LOG={service}\n"
    elif "gateway" in description.lower():
        log_path = operator_home / "workspace" / "logs" / "gateway.log"
        log_lines = f"StandardOutput=append:{log_path}\nStandardError=append:{log_path}\n"
    exec_argv = uvicorn_program_argv(
        module=module,
        host="127.0.0.1",
        port=port,
        factory=module.endswith(":create_app"),
    )
    exec_start = " ".join(exec_argv)
    return f"""[Unit]
Description={description}
After=network-online.target

[Service]
Type=simple
WorkingDirectory={workdir}
{env_lines}{log_lines}ExecStart={exec_start}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def _gateway_daemon_env(operator_home: Path) -> dict[str, str]:
    """Return extra launchd/systemd env for the gateway unit.

    Args:
        operator_home (Path): ``SEVN_HOME`` root.

    Returns:
        dict[str, str]: ``SEVN_PROXY_URL`` for scanner/LLM transport resolution.

    Examples:
        >>> _gateway_daemon_env(Path("/tmp/h"))["SEVN_PROXY_URL"].startswith("http")
        True
    """
    from sevn.cli.gateway_client import resolve_proxy_base_url
    from sevn.config.loader import load_workspace

    env: dict[str, str] = {}
    sevn_json = operator_home / "workspace" / "sevn.json"
    if sevn_json.is_file():
        try:
            workspace_cfg, _layout = load_workspace(sevn_json=sevn_json)
            env["SEVN_PROXY_URL"] = resolve_proxy_base_url(workspace=workspace_cfg)
        except (OSError, ValueError):
            pass
    if "SEVN_PROXY_URL" not in env:
        env["SEVN_PROXY_URL"] = "http://127.0.0.1:8787"
    from sevn.runtime.operator_path import (
        augment_macos_dyld_library_path,
        augment_operator_path,
    )

    # ``operator_home`` is ``~/.sevn``; PATH prefixes live under the real user home.
    env = augment_operator_path(env, home=operator_home.parent)
    # macOS: let WeasyPrint's native libs (Pango/GObject) load after `brew install pango` —
    # dyld only searches the Homebrew lib dir when this is on the launch env.
    return augment_macos_dyld_library_path(env, home=operator_home.parent)


def _unit_body(plan: InstallPlan, path: Path) -> str:
    """Return plist or unit file body for gateway or proxy.

    Args:
        plan (InstallPlan): Platform install plan.
        path (Path): Gateway or proxy unit path.

    Returns:
        str: Rendered unit file contents.

    Examples:
        >>> plan = _launchd_paths(Path("/tmp/h"))
        >>> "plist" in _unit_body(plan, plan.gateway_unit_path)
        True
    """
    name = path.name
    op_home = operator_home_dir()
    if plan.platform == "launchd":
        if "gateway" in name:
            return _render_launchd_plist(
                label=_launchd_label(path),
                module="sevn.gateway.http_server:create_app",
                port=3001,
                operator_home=op_home,
                log_basename="gateway.log",
                extra_env=_gateway_daemon_env(op_home),
            )
        return _render_launchd_plist(
            label=_launchd_label(path),
            module="sevn.proxy.app:create_app",
            port=8787,
            operator_home=op_home,
            working_directory=op_home,
            log_basename="proxy.log",
        )
    if "gateway" in name:
        return _render_systemd_unit(
            description="Sevn gateway (uvicorn)",
            module="sevn.gateway.http_server:create_app",
            port=3001,
            operator_home=op_home,
            log_basename="gateway.log",
            extra_env=_gateway_daemon_env(op_home),
        )
    return _render_systemd_unit(
        description="Sevn egress proxy (uvicorn)",
        module="sevn.proxy.app:create_app",
        port=8787,
        operator_home=op_home,
        working_directory=op_home,
        log_basename="proxy.log",
    )


def unit_file_exists(*, home: Path, service: ServiceName) -> bool:
    """Return True when the sevn-managed unit file for ``service`` exists.

    Args:
        home (Path): Operator home directory (launchd/systemd paths are under it).
        service (ServiceName): ``gateway`` or ``proxy``.

    Returns:
        bool: ``True`` when the expected plist or ``.service`` file is present.

    Examples:
        >>> unit_file_exists(home=Path("/tmp/h"), service="gateway") is False
        True
    """
    plan = plan_install(home)
    return _unit_path(plan, service).is_file()


def unit_is_active(*, home: Path, service: ServiceName) -> bool:
    """Return True when the user unit for ``service`` is loaded and active.

    Args:
        home (Path): Operator home directory.
        service (ServiceName): ``gateway`` or ``proxy``.

    Returns:
        bool: ``True`` when the unit file exists and the platform reports active.

    Examples:
        >>> unit_is_active(home=Path("/tmp/h"), service="gateway") is False
        True
    """
    if not unit_file_exists(home=home, service=service):
        return False
    plan = plan_install(home)
    unit_path = _unit_path(plan, service)
    if plan.platform == "launchd":
        label = _launchd_label(unit_path)
        uid = str(Path.home().stat().st_uid) if home == Path.home() else str(home.stat().st_uid)
        target = f"gui/{uid}/{label}"
        proc = _run(["launchctl", "print", target])
        return proc.returncode == 0
    proc = _run(["systemctl", "--user", "is-active", unit_path.name])
    return proc.returncode == 0


def both_units_installed_and_active(home: Path) -> bool:
    """Return True when gateway and proxy units exist and are active.

    Args:
        home (Path): Operator home directory for unit path resolution.

    Returns:
        bool: ``True`` only when both units are installed and active.

    Examples:
        >>> both_units_installed_and_active(Path("/tmp/h"))
        False
    """
    return (
        unit_file_exists(home=home, service="gateway")
        and unit_file_exists(home=home, service="proxy")
        and unit_is_active(home=home, service="gateway")
        and unit_is_active(home=home, service="proxy")
    )


def install_paired_units(*, home: Path, dry_run: bool = False) -> InstallPlan:
    """Install or plan gateway + proxy user service units.

    Set ``SEVN_DISABLE_DAEMON_INSTALL=1`` (any value) to force ``dry_run`` behaviour.
    Tests must enable this to prevent accidental writes to the real
    ``~/Library/LaunchAgents`` or ``~/.config/systemd/user`` from a pytest tmp dir
    (`specs/23-cli.md` §4.2).

    Args:
        home (Path): Operator home (``~``).
        dry_run (bool, optional): When True, return plan without writing files.

    Returns:
        InstallPlan: Paths that would be or were written.

    Examples:
        >>> p = install_paired_units(home=Path("/tmp/h"), dry_run=True)
        >>> p.gateway_unit_path.name.endswith((".plist", ".service"))
        True
    """
    plan = plan_install(home)
    if dry_run or os.environ.get("SEVN_DISABLE_DAEMON_INSTALL", "").strip():
        return plan
    for path in (plan.gateway_unit_path, plan.proxy_unit_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_unit_body(plan, path), encoding="utf-8")
    return plan


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and capture stdout/stderr as text.

    Args:
        cmd (list[str]): argv for ``subprocess.run``.

    Returns:
        subprocess.CompletedProcess[str]: Completed process with decoded streams.

    Examples:
        >>> proc = _run([sys.executable, "-c", "print(1)"])
        >>> proc.returncode
        0
    """
    return subprocess.run(  # nosec B603
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )


def _daemon_encrypted_file_key_source() -> str:
    """Resolve the encrypted-file unlock mechanism from the promoted ``sevn.json``.

    Returns:
        str: ``"passphrase"`` or ``"master_key"``; ``"passphrase"`` when unset/unreadable.

    Examples:
        >>> _daemon_encrypted_file_key_source() in ("passphrase", "master_key")
        True
    """
    from sevn.config.loader import load_workspace
    from sevn.config.workspace_config import effective_encrypted_file_key_source

    sevn_json = operator_home_dir() / "workspace" / "sevn.json"
    if sevn_json.is_file():
        try:
            workspace_cfg, _layout = load_workspace(sevn_json=sevn_json)
            return effective_encrypted_file_key_source(workspace_cfg.secrets_backend)
        except (OSError, ValueError):
            pass
    return "passphrase"


def _active_unlock_secret_for_launchctl(*, key_source: str) -> str:
    """Resolve the unlock secret to publish into the user service session.

    On macOS, prefer the login Keychain copy written during onboard over a stale shell or
    ``launchctl setenv`` value so the first daemon boot after promote decrypts ``store.enc``.

    Args:
        key_source (str): ``"passphrase"`` or ``"master_key"``.

    Returns:
        str: Trimmed unlock secret for the active var, or ``""`` when unset.

    Examples:
        >>> _active_unlock_secret_for_launchctl(key_source="passphrase") == "" or isinstance(
        ...     _active_unlock_secret_for_launchctl(key_source="passphrase"), str
        ... )
        True
    """
    import asyncio

    from loguru import logger

    from sevn.security.secrets.passphrase_prime import (
        fetch_unlock_secret_from_keychain,
        unlock_env_var_for,
    )

    var = unlock_env_var_for(key_source)
    env_val = os.environ.get(var, "").strip()
    if sys.platform == "darwin":
        kc_val = asyncio.run(fetch_unlock_secret_from_keychain(key_source=key_source)) or ""
        if kc_val:
            if env_val and env_val != kc_val:
                logger.warning(
                    "propagate_daemon_secret_env: {} in shell differed from keychain; "
                    "using keychain value for launchctl",
                    var,
                )
            os.environ[var] = kc_val
            return kc_val
    return env_val


def propagate_daemon_secret_env(*, dry_run: bool = False) -> None:
    """Publish only the unlock var the configured ``key_source`` needs into the service session.

    The promoted ``secrets_backend.encrypted_file.key_source`` decides which unlock variable the
    daemons require: ``SEVN_SECRETS_PASSPHRASE`` (passphrase mode, the default) or
    ``SEVN_SECRETS_MASTER_KEY`` (master_key mode). Only that var is mirrored from the current
    shell (``setenv`` when present, ``unsetenv`` when absent); the **other** unlock var is always
    **unset** from the session. ``launchctl setenv`` / ``set-environment`` values persist across
    restarts (until logout), so this deterministically clears a stale ``SEVN_SECRETS_MASTER_KEY``
    that would otherwise shadow a passphrase-sealed store and silently break decryption.

    Args:
        dry_run (bool, optional): Skip platform calls when True.

    Examples:
        >>> propagate_daemon_secret_env(dry_run=True) is None
        True
    """
    if dry_run:
        return
    key_source = _daemon_encrypted_file_key_source()
    active_var = (
        "SEVN_SECRETS_MASTER_KEY" if key_source == "master_key" else "SEVN_SECRETS_PASSPHRASE"
    )
    active_secret = _active_unlock_secret_for_launchctl(key_source=key_source)
    plan = plan_install(Path.home())
    for var in _DAEMON_SECRET_ENV_KEYS:
        # Mirror the active unlock var from shell/keychain; always clear the inactive one so a
        # stray value for the unused mechanism cannot linger in the session and confuse decryption.
        val = active_secret if var == active_var else ""
        if plan.platform == "launchd":
            if val:
                _run(["launchctl", "setenv", var, val])
            else:
                _run(["launchctl", "unsetenv", var])
        elif val:
            _run(["systemctl", "--user", "set-environment", f"{var}={val}"])
        else:
            _run(["systemctl", "--user", "unset-environment", var])


def propagate_daemon_proxy_env(*, dry_run: bool = False) -> None:
    """Publish ``SEVN_PROXY_URL`` into the user service session for gateway daemons.

    Uses the shell value when set; otherwise resolves from promoted ``sevn.json``.

    Args:
        dry_run (bool, optional): Skip platform calls when True.

    Examples:
        >>> propagate_daemon_proxy_env(dry_run=True) is None
        True
    """
    if dry_run:
        return
    raw = os.environ.get("SEVN_PROXY_URL", "").strip()
    if not raw:
        raw = _gateway_daemon_env(operator_home_dir())["SEVN_PROXY_URL"]
    plan = plan_install(Path.home())
    if plan.platform == "launchd":
        _run(["launchctl", "setenv", "SEVN_PROXY_URL", raw])
    else:
        _run(["systemctl", "--user", "set-environment", f"SEVN_PROXY_URL={raw}"])


def stop_paired_units(*, home: Path, dry_run: bool = False) -> None:
    """Best-effort stop of gateway and proxy user units.

    Missing unit files or inactive services are ignored so teardown can continue.

    Args:
        home (Path): User home directory holding launchd/systemd unit files.
        dry_run (bool, optional): Print planned stop commands only.

    Examples:
        >>> stop_paired_units(home=Path("/tmp/h"), dry_run=True) is None
        True
    """
    for service in ("gateway", "proxy"):
        try:
            control_unit(home=home, service=service, action="stop", dry_run=dry_run)
        except ServiceManagerError:
            continue


def remove_paired_unit_files(*, home: Path, dry_run: bool = False) -> InstallPlan:
    """Remove sevn-managed gateway and proxy unit files from disk.

    Args:
        home (Path): User home directory holding launchd/systemd unit files.
        dry_run (bool, optional): Return plan without deleting files.

    Returns:
        InstallPlan: Paths that were or would be removed.

    Examples:
        >>> plan = remove_paired_unit_files(home=Path("/tmp/h"), dry_run=True)
        >>> plan.gateway_unit_path.name.endswith((".plist", ".service"))
        True
    """
    plan = plan_install(home)
    if dry_run:
        return plan
    for path in (plan.gateway_unit_path, plan.proxy_unit_path):
        if path.is_file():
            path.unlink()
    if plan.platform == "systemd":
        _run(["systemctl", "--user", "daemon-reload"])
    return plan


def control_unit(
    *,
    home: Path,
    service: ServiceName,
    action: ServiceAction,
    dry_run: bool = False,
) -> str:
    """Start, stop, restart, or query status for one user unit.

    Args:
        home (Path): Operator home directory.
        service (ServiceName): ``gateway`` or ``proxy``.
        action (ServiceAction): Service manager verb.
        dry_run (bool, optional): Print planned command only.

    Returns:
        str: Human-readable status line or command summary.

    Raises:
        ServiceManagerError: When the unit file is missing or the command fails.

    Examples:
        >>> control_unit(
        ...     home=Path("/tmp/h"),
        ...     service="gateway",
        ...     action="status",
        ...     dry_run=True,
        ... ).startswith("dry-run:")
        True
    """
    plan = plan_install(home)
    unit_path = _unit_path(plan, service)
    if not unit_path.is_file() and not dry_run:
        msg = f"unit not installed: {unit_path} (run `sevn onboard --install-daemon` first)"
        raise ServiceManagerError(msg)
    if (
        not dry_run
        and action != "status"
        and os.environ.get("SEVN_DISABLE_DAEMON_INSTALL", "").strip()
    ):
        return f"dry-run (SEVN_DISABLE_DAEMON_INSTALL): {service} {action} skipped"

    if plan.platform == "launchd":
        label = _launchd_label(unit_path)
        uid = str(Path.home().stat().st_uid) if home == Path.home() else "0"
        target = f"gui/{uid}/{label}"
        if action == "status":
            cmd = ["launchctl", "print", target]
        elif action == "start":
            # launchctl bootstrap fails with errno 5 ("Input/output error")
            # when the service is already loaded. Make ``start`` idempotent
            # by probing first: ``launchctl print <target>`` exits 0 when
            # loaded, non-zero when not. When already loaded, fall through
            # to ``kickstart`` so the service is ensured-running. Reference:
            # operator chat 2026-05-27.
            if dry_run:
                return (
                    f"dry-run: launchctl bootstrap gui/{uid} {unit_path} (or kickstart if loaded)"
                )
            probe = _run(["launchctl", "print", target])
            if probe.returncode == 0:
                kick = _run(["launchctl", "kickstart", target])
                if kick.returncode == 0:
                    return f"{service} start: already loaded; kickstart ok"
                # Service is loaded but kickstart failed; surface the error
                # rather than masking with a redundant bootstrap attempt.
                detail = (kick.stderr or kick.stdout or "").strip()
                msg = f"launchctl kickstart {target} failed ({kick.returncode}): {detail}"
                raise ServiceManagerError(msg)
            cmd = ["launchctl", "bootstrap", f"gui/{uid}", str(unit_path)]
        elif action == "stop":
            cmd = ["launchctl", "bootout", target]
        elif action == "restart":
            if dry_run:
                return f"dry-run: launchctl kickstart -k {target}"
            kick = _run(["launchctl", "kickstart", "-k", target])
            if kick.returncode == 0:
                return f"{service} restart: ok"
            detail = (kick.stderr or kick.stdout or "").strip()
            if "Could not find service" not in detail:
                msg = f"launchctl kickstart -k {target} failed ({kick.returncode}): {detail}"
                raise ServiceManagerError(msg)
            cmd = ["launchctl", "bootstrap", f"gui/{uid}", str(unit_path)]
        else:
            msg = f"unsupported action: {action}"
            raise ServiceManagerError(msg)
    else:
        unit = unit_path.name
        if action == "status":
            cmd = ["systemctl", "--user", "is-active", unit]
        elif action == "start":
            cmd = ["systemctl", "--user", "start", unit]
        elif action == "stop":
            cmd = ["systemctl", "--user", "stop", unit]
        else:
            cmd = ["systemctl", "--user", "restart", unit]

    if dry_run:
        return "dry-run: " + " ".join(cmd)

    proc = _run(cmd)
    if proc.returncode != 0 and action != "status":
        detail = (proc.stderr or proc.stdout or "").strip()
        msg = f"{' '.join(cmd)} failed ({proc.returncode}): {detail}"
        raise ServiceManagerError(msg)
    if action == "status":
        active = proc.returncode == 0
        return f"{service} ({plan.platform}): {'active' if active else 'inactive'}"
    return f"{service} {action}: ok"


__all__ = [
    "InstallPlan",
    "ServiceAction",
    "ServiceManagerError",
    "ServiceName",
    "both_units_installed_and_active",
    "control_unit",
    "install_paired_units",
    "plan_install",
    "propagate_daemon_proxy_env",
    "propagate_daemon_secret_env",
    "remove_paired_unit_files",
    "stop_paired_units",
    "unit_file_exists",
    "unit_is_active",
]
