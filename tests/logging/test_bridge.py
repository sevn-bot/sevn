"""Tests for stdlib logging → loguru bridge."""

from __future__ import annotations

import logging

from loguru import logger

from sevn.logging.bridge import InterceptHandler, configure_intercept_logging


def test_intercept_handler_forwards_to_loguru(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "bridge.log"
    logger.remove()
    logger.add(log_path, format="{message}", level="DEBUG")

    handler = InterceptHandler()
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="GET /health 200",
        args=(),
        exc_info=None,
    )
    handler.emit(record)

    assert "GET /health 200" in log_path.read_text(encoding="utf-8")


def test_configure_intercept_logging_wires_uvicorn() -> None:
    configure_intercept_logging()
    uvicorn_log = logging.getLogger("uvicorn")
    assert uvicorn_log.handlers
    assert isinstance(uvicorn_log.handlers[0], InterceptHandler)
