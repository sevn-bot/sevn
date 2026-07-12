"""Loguru setup and rotate-on-restart for gateway/proxy service logs.

Module: sevn.logging.setup
Depends: datetime, os, pathlib, loguru, sevn.config.defaults

Exports:
    setup_service_logging — bind loguru file sink for a daemon service.
    resolve_service_log_timezone — map ``SEVN_LOG_TZ`` to a ``tzinfo``.
    resolve_service_log_format — loguru format string for ``SEVN_LOG_TZ``.
    rotate_active_log_on_restart — rename active log, open fresh canonical file.
    boot_service_logging — rotate then bind loguru for daemon restart.
    maybe_boot_service_logging — boot when ``SEVN_SERVICE_LOG`` matches service.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

if TYPE_CHECKING:
    from loguru import Record

from sevn.config.defaults import SERVICE_LOG_FORMAT
from sevn.logging.bridge import configure_intercept_logging
from sevn.logging.context import inject_message_id

_KNOWN_SERVICES: frozenset[str] = frozenset({"gateway", "proxy"})
_LOG_RECORD_SUFFIX: str = (
    " | {level: <8} | {extra[message_id]} | {extra[short_path]}:{line} {function} | {message}"
)


def _offset_suffix(dt: datetime) -> str:
    """Format ``±HH:MM`` for a timezone-aware ``datetime``.

    Args:
        dt (datetime): Aware timestamp.

    Returns:
        str: Offset suffix such as ``+02:00``.

    Examples:
        >>> from datetime import UTC, datetime
        >>> _offset_suffix(datetime(2026, 5, 27, 12, 0, tzinfo=UTC))
        '+00:00'
    """
    offset = dt.utcoffset()
    if offset is None:
        return "+00:00"
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def _render_timestamp(dt: datetime) -> str:
    """Render one service-log timestamp with millisecond precision + offset.

    Args:
        dt (datetime): Aware timestamp in the target zone.

    Returns:
        str: ``YYYY-MM-DD HH:mm:ss.SSS±HH:MM`` fragment.

    Examples:
        >>> from datetime import UTC, datetime
        >>> _render_timestamp(datetime(2026, 5, 27, 12, 0, 0, 277000, tzinfo=UTC))
        '2026-05-27 12:00:00.277+00:00'
    """
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{ms:03d}{_offset_suffix(dt)}"


def resolve_service_log_timezone() -> tzinfo | None:
    """Resolve loguru sink timezone from ``SEVN_LOG_TZ`` (`specs/04-tracing.md` §5.1).

    Args:
        None.

    Returns:
        tzinfo | None: ``None`` for host-local (loguru default); ``UTC`` when
        ``SEVN_LOG_TZ=utc``; a :class:`zoneinfo.ZoneInfo` for IANA names.

    Raises:
        ValueError: When ``SEVN_LOG_TZ`` is set to an unknown IANA zone.

    Examples:
        >>> resolve_service_log_timezone() is None or resolve_service_log_timezone() == UTC
        True
    """
    raw = os.environ.get("SEVN_LOG_TZ", "local").strip()
    if not raw or raw.casefold() == "local":
        return None
    if raw.casefold() == "utc":
        return UTC
    try:
        return ZoneInfo(raw)
    except ZoneInfoNotFoundError as exc:
        msg = f"unknown SEVN_LOG_TZ zone {raw!r}"
        raise ValueError(msg) from exc


def resolve_service_log_format() -> str:
    """Return the loguru format string for the active ``SEVN_LOG_TZ`` policy.

    Args:
        None.

    Returns:
        str: Format string passed to ``logger.add(..., format=…)``.

    Examples:
        >>> "message_id" in resolve_service_log_format()
        True
    """
    raw = os.environ.get("SEVN_LOG_TZ", "local").strip()
    if not raw or raw.casefold() == "local":
        return SERVICE_LOG_FORMAT.replace("{file.path}", "{extra[short_path]}")
    if raw.casefold() == "utc":
        return "{time:YYYY-MM-DD HH:mm:ss.SSS!UTC}+00:00" + _LOG_RECORD_SUFFIX
    return "{extra[sevn_ts]}" + _LOG_RECORD_SUFFIX


def _short_log_path(file_path: str) -> str:
    """Return ``sevn/…`` module path for service log lines (D10).

    Args:
        file_path (str): Absolute or relative path from loguru ``record.file``.

    Returns:
        str: Slash form from the last ``/sevn/`` segment, or basename when absent.

    Examples:
        >>> _short_log_path("/Users/x/.local/share/uv/tools/sevn/lib/sevn/channels/telegram.py")
        'sevn/channels/telegram.py'
        >>> _short_log_path("/tmp/other_module.py")
        'other_module.py'
    """
    normalized = file_path.replace("\\", "/")
    marker = "/sevn/"
    idx = normalized.rfind(marker)
    if idx >= 0:
        return normalized[idx + 1 :]
    return Path(file_path).name


def _service_log_patcher(record: Record) -> None:
    """Inject ``message_id``, ``short_path``, and optional IANA ``sevn_ts`` into records.

    Args:
        record (Record): Loguru record dict (mutated in place).

    Returns:
        None: Always.

    Examples:
        >>> _service_log_patcher.__doc__ is not None
        True
    """
    inject_message_id(record)
    record["extra"]["short_path"] = _short_log_path(record["file"].path)
    tz = resolve_service_log_timezone()
    if isinstance(tz, ZoneInfo):
        record["extra"]["sevn_ts"] = _render_timestamp(record["time"].astimezone(tz))


def _active_log_name(service: str) -> str:
    """Return the canonical active log filename for a service.

    Args:
        service (str): ``gateway`` or ``proxy``.

    Returns:
        str: Basename such as ``gateway.log``.

    Raises:
        ValueError: When ``service`` is not a known daemon name.

    Examples:
        >>> _active_log_name("gateway")
        'gateway.log'
        >>> _active_log_name("proxy")
        'proxy.log'
    """
    if service not in _KNOWN_SERVICES:
        msg = f"unknown service {service!r}; expected one of {sorted(_KNOWN_SERVICES)}"
        raise ValueError(msg)
    return f"{service}.log"


def rotate_active_log_on_restart(logs_dir: Path, active_name: str) -> Path:
    """Rename an existing active log, then create a fresh canonical file.

    When ``logs_dir / active_name`` exists, it is renamed to
    ``{stem}-<UTC-timestamp>.log`` in the same directory (for example
    ``gateway.log`` → ``gateway-20260520T143022Z.log``). A new empty file is
    always created at the canonical path. Does not move logs to ``old_logs/``.

    Args:
        logs_dir (Path): Workspace ``logs/`` directory.
        active_name (str): Canonical basename (``gateway.log`` or ``proxy.log``).

    Returns:
        Path: Path to the new empty active log file.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> logs = td / "logs"
        >>> logs.mkdir()
        >>> active = logs / "gateway.log"
        >>> _ = active.write_text("line\\n", encoding="utf-8")
        >>> out = rotate_active_log_on_restart(logs, "gateway.log")
        >>> out == active and active.read_text(encoding="utf-8") == ""
        True
        >>> len(list(logs.glob("gateway-*.log"))) == 1
        True
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    active_path = logs_dir / active_name
    if active_path.is_file():
        stem = active_path.stem
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        rotated = logs_dir / f"{stem}-{ts}.log"
        active_path.rename(rotated)
    active_path.touch()
    return active_path


def setup_service_logging(service: str, logs_dir: Path) -> Path:
    """Configure loguru to append to the service's active log file.

    Binds a single file sink at ``logs_dir / {service}.log`` using
    ``SERVICE_LOG_FORMAT``. Does not rotate; callers invoke
    ``rotate_active_log_on_restart`` on restart before this function.

    Args:
        service (str): ``gateway`` or ``proxy``.
        logs_dir (Path): Workspace ``logs/`` directory.

    Returns:
        Path: Active log file path passed to the loguru sink.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> logs = td / "logs"
        >>> path = setup_service_logging("gateway", logs)
        >>> path.name
        'gateway.log'
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / _active_log_name(service)
    logger.remove()
    extra: dict[str, str] = {"message_id": "-", "short_path": "-"}
    if isinstance(resolve_service_log_timezone(), ZoneInfo):
        extra["sevn_ts"] = "-"
    logger.configure(extra=extra, patcher=_service_log_patcher)
    logger.add(
        log_path,
        format=resolve_service_log_format(),
        level="DEBUG",
        enqueue=True,
    )
    configure_intercept_logging()
    return log_path


def boot_service_logging(service: str, logs_dir: Path) -> Path:
    """Rotate the active log on restart, then bind loguru to the canonical file.

    Args:
        service (str): ``gateway`` or ``proxy``.
        logs_dir (Path): Workspace ``logs/`` directory.

    Returns:
        Path: Active log file path passed to the loguru sink.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> logs = td / "logs"
        >>> path = boot_service_logging("gateway", logs)
        >>> path.name
        'gateway.log'
    """
    active_name = _active_log_name(service)
    rotate_active_log_on_restart(logs_dir, active_name)
    return setup_service_logging(service, logs_dir)


def maybe_boot_service_logging(service: str, logs_dir: Path) -> Path | None:
    """Boot daemon logging when ``SEVN_SERVICE_LOG`` matches ``service``.

    Args:
        service (str): ``gateway`` or ``proxy``.
        logs_dir (Path): Workspace ``logs/`` directory.

    Returns:
        Path | None: Active log path when boot ran; ``None`` when env did not match.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> logs = td / "logs"
        >>> maybe_boot_service_logging("gateway", logs) is None
        True
    """
    if os.environ.get("SEVN_SERVICE_LOG") != service:
        return None
    return boot_service_logging(service, logs_dir)


__all__ = [
    "boot_service_logging",
    "maybe_boot_service_logging",
    "resolve_service_log_format",
    "resolve_service_log_timezone",
    "rotate_active_log_on_restart",
    "setup_service_logging",
]
