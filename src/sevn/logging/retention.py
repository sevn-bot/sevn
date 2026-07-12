"""Retention sweeper for rotated gateway/proxy service logs.



Module: sevn.logging.retention
Depends: pathlib, shutil, time, loguru, sevn.config.defaults, sevn.config.workspace_config



Exports:

    ServiceLogSweepResult — counts from one sweeper pass.
    effective_logging_config — resolve ``logging.*`` with schema defaults.
    iter_expired_rotated_logs — yield rotated logs past ``retention_days``.
    archive_rotated_log — apply ``archive_mode`` to one expired file.
    sweep_rotated_service_logs — sweep ``gateway-*.log`` / ``proxy-*.log`` by mtime.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger

from sevn.config.defaults import (
    DEFAULT_LOG_ARCHIVE_DESTINATION,
)

if TYPE_CHECKING:
    from sevn.config.workspace_config import LoggingWorkspaceConfig, WorkspaceConfig


ArchiveMode = Literal["delete", "copy", "r2", "gcs"]


ROTATED_LOG_GLOBS: tuple[str, ...] = ("gateway-*.log", "proxy-*.log")
_ACTIVE_LOG_NAMES: frozenset[str] = frozenset({"gateway.log", "proxy.log"})


@dataclass(frozen=True, slots=True)
class ServiceLogSweepResult:
    """Outcome counters for one retention sweeper pass."""

    scanned: int
    archived: int
    skipped_cloud: int


def effective_logging_config(workspace: WorkspaceConfig | None) -> LoggingWorkspaceConfig:
    """Return effective ``logging.*`` settings with schema defaults applied.



    Args:

        workspace (WorkspaceConfig | None): Loaded workspace document.



    Returns:

        LoggingWorkspaceConfig: Resolved logging subtree.



    Examples:

        >>> from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config
        >>> ws = parse_workspace_config({"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}})
        >>> cfg = effective_logging_config(ws)
        >>> cfg.retention_days == 10
        True
    """

    from sevn.config.workspace_config import LoggingWorkspaceConfig

    if workspace is None or workspace.logging is None:
        return LoggingWorkspaceConfig()
    return workspace.logging


def _matches_rotated_pattern(name: str) -> bool:
    """Return whether ``name`` is a rotated gateway/proxy log basename.



    Args:

        name (str): File basename under ``logs/``.



    Returns:

        bool: ``True`` when the name matches ``gateway-*.log`` or ``proxy-*.log``.



    Examples:

        >>> _matches_rotated_pattern("gateway-20260520T143022Z.log")
        True
        >>> _matches_rotated_pattern("gateway.log")
        False
    """

    if name in _ACTIVE_LOG_NAMES:
        return False
    return any(fnmatch(name, pattern) for pattern in ROTATED_LOG_GLOBS)


def iter_expired_rotated_logs(
    logs_dir: Path,
    *,
    retention_days: int,
    now_s: float | None = None,
) -> list[Path]:
    """List rotated service logs older than ``retention_days`` by mtime.



    Args:

        logs_dir (Path): Workspace ``logs/`` directory.
        retention_days (int): Keep rotated files newer than this many whole days.
        now_s (float | None): Optional clock injection for tests.



    Returns:

        list[Path]: Expired rotated log paths (possibly empty).



    Examples:

        >>> import os
        >>> import tempfile
        >>> import time
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> logs = td / "logs"
        >>> logs.mkdir()
        >>> old = logs / "gateway-20260101T000000Z.log"
        >>> _ = old.write_text("x", encoding="utf-8")
        >>> os.utime(old, (time.time() - 86400 * 20, time.time() - 86400 * 20))
        >>> old in iter_expired_rotated_logs(logs, retention_days=10, now_s=time.time())
        True
    """

    if retention_days < 0 or not logs_dir.is_dir():
        return []
    clock = now_s if now_s is not None else time.time()
    cutoff = clock - float(retention_days * 86400)
    expired: list[Path] = []
    for child in logs_dir.iterdir():
        if not child.is_file() or not _matches_rotated_pattern(child.name):
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime <= cutoff:
            expired.append(child)
    return expired


def _copy_then_delete(source: Path, destination: Path) -> None:
    """Copy ``source`` to ``destination`` then remove ``source``.



    Args:

        source (Path): Rotated log to archive.
        destination (Path): Destination file path.



    Returns:

        None: Mutates filesystem only.



    Examples:

        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> src = td / "gateway-old.log"
        >>> dst = td / "archive" / "gateway-old.log"
        >>> _ = src.write_text("line", encoding="utf-8")
        >>> _copy_then_delete(src, dst)
        >>> dst.read_text(encoding="utf-8")
        'line'
        >>> src.exists()
        False
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    source.unlink(missing_ok=True)


def _archive_to_cloud(
    source: Path,
    *,
    mode: ArchiveMode,
    cloud_cfg: LoggingWorkspaceConfig,
) -> bool:
    """Attempt cloud upload for ``mode`` in ``{r2, gcs}`` (v1 stub).



    Cloud archive modes are schema-valid but not yet implemented; the sweeper
    keeps local files when upload is unavailable.



    Args:

        source (Path): Rotated log path.
        mode (ArchiveMode): ``r2`` or ``gcs``.
        cloud_cfg (LoggingWorkspaceConfig): Logging config with ``cloud.*`` refs.



    Returns:

        bool: ``True`` when upload succeeded and local file was removed.



    Examples:

        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import LoggingCloudConfig, LoggingCloudProviderConfig, LoggingWorkspaceConfig
        >>> cfg = LoggingWorkspaceConfig(
        ...     archive_mode="r2",
        ...     cloud=LoggingCloudConfig(r2=LoggingCloudProviderConfig(bucket_ref="${SECRET:x}")),
        ... )
        >>> _archive_to_cloud(Path("/tmp/x.log"), mode="r2", cloud_cfg=cfg)
        False
    """

    provider = mode
    cloud = cloud_cfg.cloud
    bucket_ref = None
    if cloud is not None:
        section = cloud.r2 if mode == "r2" else cloud.gcs
        if section is not None:
            bucket_ref = section.bucket_ref
    logger.bind(path=str(source), archive_mode=provider, bucket_ref=bucket_ref).warning(
        "cloud service log archive not implemented in v1; retaining local file",
    )
    return False


def archive_rotated_log(
    source: Path,
    *,
    content_root: Path,
    logging_cfg: LoggingWorkspaceConfig,
) -> bool:
    """Apply ``logging.archive_mode`` to one expired rotated log file.



    Args:

        source (Path): Expired rotated log under ``logs/``.
        content_root (Path): Workspace content root for relative archive paths.
        logging_cfg (LoggingWorkspaceConfig): Effective logging settings.



    Returns:

        bool: ``True`` when the local file was removed after archive/delete.



    Examples:

        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import LoggingWorkspaceConfig
        >>> td = Path(tempfile.mkdtemp())
        >>> logs = td / "logs"
        >>> logs.mkdir()
        >>> src = logs / "proxy-20260101T000000Z.log"
        >>> _ = src.write_text("p", encoding="utf-8")
        >>> cfg = LoggingWorkspaceConfig(archive_mode="delete")
        >>> archive_rotated_log(src, content_root=td, logging_cfg=cfg)
        True
        >>> src.exists()
        False
    """

    mode = logging_cfg.archive_mode
    if mode == "delete":
        source.unlink(missing_ok=True)
        return True
    if mode == "copy":
        rel = logging_cfg.archive_destination or DEFAULT_LOG_ARCHIVE_DESTINATION
        archive_root = (content_root / rel).resolve()
        destination = archive_root / source.name
        _copy_then_delete(source, destination)
        return True
    if mode in ("r2", "gcs"):
        return _archive_to_cloud(source, mode=mode, cloud_cfg=logging_cfg)
    msg = f"unsupported archive_mode {mode!r}"
    raise ValueError(msg)


def sweep_rotated_service_logs(
    logs_dir: Path,
    *,
    content_root: Path,
    workspace: WorkspaceConfig | None,
    now_s: float | None = None,
) -> ServiceLogSweepResult:
    """Sweep expired ``gateway-*.log`` / ``proxy-*.log`` files per ``logging.*``.



    Args:

        logs_dir (Path): Workspace ``logs/`` directory.
        content_root (Path): Workspace content root.
        workspace (WorkspaceConfig | None): Loaded workspace config.
        now_s (float | None): Optional clock injection for tests.



    Returns:

        ServiceLogSweepResult: Scan/archive counters for the pass.



    Examples:

        >>> import os
        >>> import tempfile
        >>> import time
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import LoggingWorkspaceConfig, WorkspaceConfig
        >>> td = Path(tempfile.mkdtemp())
        >>> logs = td / "logs"
        >>> logs.mkdir()
        >>> old = logs / "gateway-20260101T000000Z.log"
        >>> _ = old.write_text("x", encoding="utf-8")
        >>> os.utime(old, (time.time() - 86400, time.time() - 86400))
        >>> ws = WorkspaceConfig.minimal(logging=LoggingWorkspaceConfig(retention_days=0))
        >>> sweep_rotated_service_logs(logs, content_root=td, workspace=ws, now_s=time.time()).archived
        1
    """

    logging_cfg = effective_logging_config(workspace)
    expired = iter_expired_rotated_logs(
        logs_dir,
        retention_days=logging_cfg.retention_days,
        now_s=now_s,
    )
    archived = 0
    skipped_cloud = 0
    for path in expired:
        try:
            removed = archive_rotated_log(
                path,
                content_root=content_root,
                logging_cfg=logging_cfg,
            )
        except OSError:
            logger.bind(path=str(path)).exception("service log retention failed")
            continue
        if removed:
            archived += 1
        elif logging_cfg.archive_mode in ("r2", "gcs"):
            skipped_cloud += 1
    if archived:
        logger.bind(
            archived=archived,
            retention_days=logging_cfg.retention_days,
            archive_mode=logging_cfg.archive_mode,
        ).info("service log retention sweep")
    return ServiceLogSweepResult(
        scanned=len(expired),
        archived=archived,
        skipped_cloud=skipped_cloud,
    )


__all__ = [
    "ROTATED_LOG_GLOBS",
    "ServiceLogSweepResult",
    "archive_rotated_log",
    "effective_logging_config",
    "iter_expired_rotated_logs",
    "sweep_rotated_service_logs",
]
