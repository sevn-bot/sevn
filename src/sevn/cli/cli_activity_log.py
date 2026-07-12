"""Operator-facing CLI activity log sink tagged ``[cli]`` (`specs/23-cli.md` §7).

Module: sevn.cli.cli_activity_log
Depends: datetime, os, pathlib, sevn.cli.log_redact, sevn.cli.workspace

Exports:
    resolve_cli_log_path — ``{workspace}/logs/cli.log`` when workspace is bound.
    install_cli_activity_log — enable default-on activity logging for this process.
    shutdown_cli_activity_log — flush/close the activity log handle.
    log_cli_activity — append one redacted operator-facing line.
    log_cli_invocation — record argv summary at command start.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from sevn.cli.errors import CliPreconditionError
from sevn.cli.log_redact import redact_log_line
from sevn.cli.workspace import sevn_home_dir
from sevn.config.loader import load_workspace

CLI_LOG_SOURCE = "cli"

_sink_path: Path | None = None
_enabled: bool = False


def resolve_cli_log_path(*, operator_home: Path | None = None) -> Path:
    """Return ``{workspace}/logs/cli.log`` for the bound operator install.

    Args:
        operator_home (Path | None): ``SEVN_HOME``; defaults to ``sevn_home_dir()``.

    Returns:
        Path: Absolute path to ``cli.log`` under the workspace logs directory.

    Raises:
        CliPreconditionError: When ``workspace/sevn.json`` is missing.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> ws = td / "workspace"
        >>> ws.mkdir()
        >>> _ = (ws / "sevn.json").write_text(
        ...     '{"schema_version": 1, "workspace_root": ".", '
        ...     '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        ...     encoding="utf-8",
        ... )
        >>> resolve_cli_log_path(operator_home=td).name
        'cli.log'
    """
    home = (operator_home or sevn_home_dir()).expanduser().resolve()
    sevn_json = home / "workspace" / "sevn.json"
    if not sevn_json.is_file():
        msg = f"no workspace/sevn.json under {home}"
        raise CliPreconditionError(msg, exit_code=4)
    try:
        _cfg, layout = load_workspace(sevn_json=sevn_json)
    except ValidationError as exc:
        msg = f"invalid workspace/sevn.json under {home}"
        raise CliPreconditionError(msg, exit_code=4) from exc
    return layout.logs_dir / "cli.log"


def _format_cli_log_line(level: str, message: str) -> str:
    """Format one ``cli.log`` line with UTC timestamp and ``[cli]`` tag.

    Args:
        level (str): Log level label.
        message (str): Raw message (redacted before formatting).

    Returns:
        str: Single log line without trailing newline.

    Examples:
        >>> "[cli]" in _format_cli_log_line("info", "hello")
        True
    """
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    redacted = redact_log_line(message)
    return f"{ts} | {level.upper():<5} | [{CLI_LOG_SOURCE}] | {redacted}"


def _ensure_sink() -> Path | None:
    """Open ``cli.log`` under the bound workspace when available.

    Returns:
        Path | None: Writable log path, or None when workspace is unbound.

    Examples:
        >>> isinstance(_ensure_sink(), (Path, type(None)))
        True
    """
    global _sink_path
    if _sink_path is not None:
        return _sink_path
    try:
        path = resolve_cli_log_path()
    except CliPreconditionError:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch(mode=0o600)
    else:
        os.chmod(path, 0o600)
    _sink_path = path
    return path


def install_cli_activity_log(*, enabled: bool = True) -> bool:
    """Enable the default-on ``cli.log`` activity sink for this process.

    Args:
        enabled (bool): When False, leave logging disabled.

    Returns:
        bool: True when a writable ``cli.log`` path was bound.

    Examples:
        >>> install_cli_activity_log(enabled=False)
        False
    """
    global _enabled
    if not enabled:
        _enabled = False
        return False
    path = _ensure_sink()
    _enabled = path is not None
    return _enabled


def shutdown_cli_activity_log() -> None:
    """Reset activity-log state (tests only).

    Examples:
        >>> shutdown_cli_activity_log()
    """
    global _sink_path, _enabled
    _sink_path = None
    _enabled = False


def log_cli_activity(message: str, *, level: str = "INFO") -> None:
    """Append one redacted operator-facing line to ``cli.log``.

    Args:
        message (str): Human-readable CLI message (secrets redacted).
        level (str): Log level label (``INFO``, ``WARN``, ``ERROR``).

    Examples:
        >>> shutdown_cli_activity_log()
        >>> log_cli_activity("noop")  # no sink — no-op
    """
    if not _enabled:
        return
    path = _ensure_sink()
    if path is None:
        return
    line = _format_cli_log_line(level, message)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def log_cli_invocation(*, subcommand: str | None = None) -> None:
    """Record the invoked CLI subcommand at command start.

    Args:
        subcommand (str | None): Typer ``ctx.invoked_subcommand`` when set.

    Examples:
        >>> log_cli_invocation(subcommand="version")
    """
    if subcommand:
        log_cli_activity(f"invoke sevn {subcommand}")
    else:
        log_cli_activity("invoke sevn")


__all__ = [
    "CLI_LOG_SOURCE",
    "install_cli_activity_log",
    "log_cli_activity",
    "log_cli_invocation",
    "resolve_cli_log_path",
    "shutdown_cli_activity_log",
]
