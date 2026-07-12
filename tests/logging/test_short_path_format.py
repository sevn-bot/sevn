"""Service log ``sevn/…`` short path (gateway operator-recovery W7)."""

from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

from sevn.logging import setup as logging_setup
from sevn.logging.setup import (
    _service_log_patcher,
    _short_log_path,
    resolve_service_log_format,
    setup_service_logging,
)


def test_short_log_path_from_site_packages_install() -> None:
    absolute = (
        "/Users/alex/.local/share/uv/tools/sevn/lib/python3.12/site-packages/"
        "sevn/channels/telegram.py"
    )
    assert _short_log_path(absolute) == "sevn/channels/telegram.py"


def test_short_log_path_windows_separator() -> None:
    absolute = "C:\\Users\\dev\\site-packages\\sevn\\gateway\\agent_turn.py"
    assert _short_log_path(absolute) == "sevn/gateway/agent_turn.py"


def test_short_log_path_basename_fallback() -> None:
    assert _short_log_path("/tmp/other_module.py") == "other_module.py"


def test_service_log_patcher_sets_short_path() -> None:
    record: dict[str, object] = {
        "extra": {},
        "file": type("F", (), {"path": "/opt/sevn/lib/sevn/logging/setup.py"})(),
        "time": None,
    }
    _service_log_patcher(record)  # type: ignore[arg-type]
    assert record["extra"]["short_path"] == "sevn/logging/setup.py"


def test_setup_service_logging_uses_short_path_not_absolute(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    log_path = setup_service_logging("gateway", logs_dir)
    logging_setup.logger.info("short path probe")
    logger.complete()

    text = log_path.read_text(encoding="utf-8")
    assert "short path probe" in text
    assert "test_short_path_format.py:" in text
    assert str(tmp_path) not in text
    assert "/Users/" not in text
    assert "site-packages" not in text


def test_resolve_service_log_format_uses_short_path_in_all_branches(monkeypatch) -> None:
    monkeypatch.setenv("SEVN_LOG_TZ", "local")
    assert "{extra[short_path]}" in resolve_service_log_format()
    assert "{file.path}" not in resolve_service_log_format()

    monkeypatch.setenv("SEVN_LOG_TZ", "utc")
    utc_fmt = resolve_service_log_format()
    assert "{extra[short_path]}" in utc_fmt
    assert "{file.path}" not in utc_fmt

    monkeypatch.setenv("SEVN_LOG_TZ", "America/New_York")
    iana_fmt = resolve_service_log_format()
    assert "{extra[short_path]}" in iana_fmt
    assert "{file.path}" not in iana_fmt


def test_service_log_line_matches_short_path_pattern(tmp_path: Path) -> None:
    log_path = setup_service_logging("gateway", tmp_path / "logs")
    logging_setup.logger.info("pattern probe")
    logger.complete()
    text = log_path.read_text(encoding="utf-8")
    assert re.search(
        r"test_short_path_format\.py:\d+ \S+ \| pattern probe",
        text,
    )
    assert "/Users/" not in text
