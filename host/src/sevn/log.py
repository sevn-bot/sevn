"""loguru setup, stdlib interception, and secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from sevn.secrets.registry import registered_secrets

if TYPE_CHECKING:
    from loguru import Record

_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"Bearer\s+\S{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
_JSON_KEY = "_json"
_STD_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy", "httpx")
_PRETTY = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)
_managed_sinks: list[int] = []


def _redact_text(text: str, secrets: tuple[tuple[str, str], ...]) -> str:
    for value, name in secrets:
        if value in text:
            text = text.replace(value, f"«redacted:{name}»")
    for pattern in _PATTERNS:
        text = pattern.sub("«redacted»", text)
    return text


def redact(record: Record) -> None:
    secrets = registered_secrets()
    record["message"] = _redact_text(record["message"], secrets)
    extra = record["extra"]
    for key, value in list(extra.items()):
        if isinstance(value, str):
            extra[key] = _redact_text(value, secrets)


def _json_format(record: Record) -> str:
    extra = record["extra"]
    visible = {key: value for key, value in extra.items() if key != _JSON_KEY}
    payload: dict[str, object] = {
        "time": record["time"].isoformat(),
        "level": record["level"].name,
        "message": record["message"],
        "extra": visible,
    }
    extra[_JSON_KEY] = json.dumps(payload, default=str, ensure_ascii=False)
    return "{extra[_json]}\n"


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        depth = 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        stdlib_name = record.name

        def _set_name(log_record: Record) -> None:
            log_record["name"] = stdlib_name

        logger.patch(_set_name).opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _install_intercept(level: str) -> None:
    handler = InterceptHandler()
    numeric = logger.level(level).no
    logging.root.handlers = [handler]
    logging.root.setLevel(numeric)
    for name in _STD_LOGGERS:
        named = logging.getLogger(name)
        named.handlers = [handler]
        named.setLevel(numeric)
        named.propagate = False


def setup(level: str, json_file: Path) -> None:
    """Install stderr, a rotating JSON file, interception, and the redaction patcher."""
    for sink_id in _managed_sinks:
        try:
            logger.remove(sink_id)
        except ValueError:
            pass
    _managed_sinks.clear()
    logger.configure(patcher=redact)
    json_file.parent.mkdir(parents=True, exist_ok=True)
    if sys.stderr.isatty():
        stderr_id = logger.add(sys.stderr, level=level, format=_PRETTY, colorize=True)
    else:
        stderr_id = logger.add(sys.stderr, level=level, format=_json_format, colorize=False)
    file_id = logger.add(
        json_file,
        level=level,
        format=_json_format,
        rotation="20 MB",
        retention=10,
        colorize=False,
    )
    _managed_sinks.extend((stderr_id, file_id))
    _install_intercept(level)


__all__ = ["InterceptHandler", "logger", "redact", "setup"]
