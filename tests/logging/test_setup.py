"""Tests for daemon loguru setup and rotate-on-restart."""

from __future__ import annotations

import re
import time
from datetime import UTC
from pathlib import Path

from loguru import logger

from sevn.config.defaults import SERVICE_LOG_FORMAT
from sevn.logging.setup import (
    boot_service_logging,
    maybe_boot_service_logging,
    resolve_service_log_timezone,
    rotate_active_log_on_restart,
    setup_service_logging,
)


def test_rotate_renames_gateway_log_and_creates_fresh(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    active = logs_dir / "gateway.log"
    active.write_text("old line\n", encoding="utf-8")

    out = rotate_active_log_on_restart(logs_dir, "gateway.log")

    assert out == active
    assert active.read_text(encoding="utf-8") == ""
    rotated = list(logs_dir.glob("gateway-*.log"))
    assert len(rotated) == 1
    assert rotated[0].read_text(encoding="utf-8") == "old line\n"
    assert re.fullmatch(r"gateway-\d{8}T\d{6}Z\.log", rotated[0].name)


def test_rotate_creates_gateway_log_when_missing(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"

    out = rotate_active_log_on_restart(logs_dir, "gateway.log")

    assert out == logs_dir / "gateway.log"
    assert out.is_file()
    assert out.read_text(encoding="utf-8") == ""


def test_rotate_proxy_log(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    active = logs_dir / "proxy.log"
    active.write_text("proxy\n", encoding="utf-8")

    rotate_active_log_on_restart(logs_dir, "proxy.log")

    assert (logs_dir / "proxy.log").read_text(encoding="utf-8") == ""
    assert list(logs_dir.glob("proxy-*.log"))


def test_setup_service_logging_writes_loguru_format(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    log_path = setup_service_logging("gateway", logs_dir)
    logger.info("hello rotate test")
    logger.complete()

    text = log_path.read_text(encoding="utf-8")
    assert "hello rotate test" in text
    # Local-offset format (`specs/04-tracing.md` §5.1): ``<ts>+HH:MM | …``.
    assert re.search(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2} \| \w+\s+\| \S+ \| .+:\d+ \S+ \| hello rotate test",
        text,
    )


def test_service_log_format_matches_spec_constant() -> None:
    assert "{time:YYYY-MM-DD HH:mm:ss.SSSZ}" in SERVICE_LOG_FORMAT
    assert "!UTC" not in SERVICE_LOG_FORMAT
    assert "{level: <8}" in SERVICE_LOG_FORMAT
    assert "{extra[message_id]}" in SERVICE_LOG_FORMAT
    assert "{file.path}:{line}" in SERVICE_LOG_FORMAT
    assert "{function}" in SERVICE_LOG_FORMAT


def test_sevn_log_tz_local_offset_matches_host(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SEVN_LOG_TZ", "local")
    assert resolve_service_log_timezone() is None
    log_path = setup_service_logging("gateway", tmp_path / "logs")
    logger.info("tz local probe")
    logger.complete()
    text = log_path.read_text(encoding="utf-8")
    host_offset_s = time.localtime().tm_gmtoff
    sign = "+" if host_offset_s >= 0 else "-"
    hours, rem = divmod(abs(int(host_offset_s)), 3600)
    minutes = rem // 60
    expected = f"{sign}{hours:02d}:{minutes:02d}"
    assert expected in text


def test_sevn_log_tz_utc_renders_plus_zero_zero(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SEVN_LOG_TZ", "utc")
    assert resolve_service_log_timezone() == UTC
    log_path = setup_service_logging("gateway", tmp_path / "logs")
    logger.info("tz utc probe")
    logger.complete()
    assert "+00:00" in log_path.read_text(encoding="utf-8")


def test_maybe_boot_service_logging_skips_without_env(tmp_path: Path, monkeypatch) -> None:
    logs_dir = tmp_path / "logs"
    monkeypatch.delenv("SEVN_SERVICE_LOG", raising=False)
    assert maybe_boot_service_logging("gateway", logs_dir) is None


def test_boot_service_logging_rotates_then_binds(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    active = logs_dir / "gateway.log"
    active.write_text("prior\n", encoding="utf-8")

    path = boot_service_logging("gateway", logs_dir)
    logger.info("after boot")
    logger.complete()

    assert path == active
    assert list(logs_dir.glob("gateway-*.log"))
    assert "after boot" in active.read_text(encoding="utf-8")
