"""Bridge stdlib logging (uvicorn) into loguru (`specs/02-config-and-workspace.md` §2.4).

Module: sevn.logging.bridge
Depends: logging, sys, loguru

Exports:
    InterceptHandler — stdlib ``logging.Handler`` forwarding records to loguru.
    configure_intercept_logging — wire uvicorn loggers through loguru sinks.
"""

from __future__ import annotations

import logging
import os
import sys
import types

from loguru import logger

# §11 (`PROBLEMS.md`): httpcore / httpx internal DEBUG floods ``gateway.log`` —
# every Telegram getUpdates long-poll emits ~10 ``send_request_headers.started``
# / ``receive_response_body`` lines. Silence by default; opt back in via
# ``SEVN_HTTP_TRACE=1`` for transport debugging.
_HTTP_TRACE_LOGGERS: tuple[str, ...] = (
    "httpcore",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpx",
    "httpx._client",
)


class InterceptHandler(logging.Handler):
    """Forward stdlib log records to loguru with correct caller depth."""

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a stdlib record through loguru.

        Args:
            record (logging.LogRecord): Record from stdlib logging.

        Examples:
            >>> isinstance(InterceptHandler(), logging.Handler)
            True
        """
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame: types.FrameType | None = sys._getframe(6)
        depth = 6
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_intercept_logging() -> None:
    """Redirect uvicorn and other stdlib loggers into the active loguru sinks.

    Call after ``setup_service_logging`` binds file sinks so access/error logs share
    ``SERVICE_LOG_FORMAT``.

    Examples:
        >>> configure_intercept_logging()
        >>> logging.getLogger("uvicorn").handlers
        [<...InterceptHandler...>]
    """
    intercept = InterceptHandler()
    logging.basicConfig(handlers=[intercept], level=logging.DEBUG, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"):
        log = logging.getLogger(name)
        log.handlers = [intercept]
        log.propagate = False
    # §11 — silence httpcore/httpx unless ``SEVN_HTTP_TRACE=1``.
    http_trace_on = os.environ.get("SEVN_HTTP_TRACE", "").strip() in ("1", "true", "yes")
    http_level = logging.DEBUG if http_trace_on else logging.WARNING
    for name in _HTTP_TRACE_LOGGERS:
        logging.getLogger(name).setLevel(http_level)


__all__ = ["InterceptHandler", "configure_intercept_logging"]
