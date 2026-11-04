"""Arrange helpers for the observability RED suite (plan 0015). Product imports stay in calls."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

# Variables that would point an exporter somewhere real, or turn one on, if they
# leaked in from the developer's shell.
_AMBIENT = (
    "SEVN_ENV",
    "LOGFIRE_TOKEN",
    "LOGFIRE_BASE_URL",
    "LOGFIRE_SEND_TO_LOGFIRE",
    "LOGFIRE_ENVIRONMENT",
    "DD_API_KEY",
    "DD_SITE",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_SERVICE_NAME",
    "OTEL_RESOURCE_ATTRIBUTES",
    "OTEL_SDK_DISABLED",
    "OTEL_TRACES_EXPORTER",
    "OTEL_METRICS_EXPORTER",
    "OTEL_LOGS_EXPORTER",
    "TRACEPARENT",
    "TRACESTATE",
    "CLAUDE_CODE_ENABLE_TELEMETRY",
)

_SETTINGS_PREFIX = "SEVN_OBSERVABILITY__"


def arm_observability(
    monkeypatch: pytest.MonkeyPatch,
    home: Path,
    section: str = "",
    *,
    extra: str = "",
) -> None:
    """Point the host at ``home`` with an ``[observability]`` table.

    ``section`` is the table body (TOML lines). An empty ``section`` writes no
    table, so every field keeps its default. ``extra`` adds other tables.
    """
    import os

    from support.chat import arm_home

    for key in _AMBIENT:
        monkeypatch.delenv(key, raising=False)
    for key in list(os.environ):
        if key.startswith(_SETTINGS_PREFIX):
            monkeypatch.delenv(key, raising=False)
    write_observability_config(home, section, extra=extra)
    arm_home(monkeypatch, home)


def write_observability_config(home: Path, section: str = "", *, extra: str = "") -> None:
    """Write ``config.toml`` with ``[secrets]``, ``extra`` and an ``[observability]`` table.

    ``support.memory.memory_host`` (under ``support.chat.connected``) rewrites
    ``config.toml`` when it opens, so a test that needs these tables in a live
    in-process host calls this again inside the ``connected`` block.
    """
    home.mkdir(parents=True, exist_ok=True)
    text = '[secrets]\nbackend = "age-file"\n'
    if extra:
        text += "\n" + extra.strip() + "\n"
    if section:
        text += "\n[observability]\n" + section.strip() + "\n"
    (home / "config.toml").write_text(text, encoding="utf-8")


def otlp_section(endpoint: str, *lines: str) -> str:
    """An ``exporter = "otlp"`` table aimed at ``endpoint``."""
    body = ['exporter = "otlp"', f'endpoint = "{endpoint}"', *lines]
    return "\n".join(body)


def store_secret(name: str, value: str) -> None:
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    open_backend(Settings.load(), Paths.from_env()).set(name, value)


def host_identity() -> Any:
    from sevn.config import Settings
    from sevn.identity import load_or_create
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    return load_or_create(open_backend(Settings.load(), Paths.from_env()))


def start_observability() -> Any:
    """``sevn.observability.setup.setup(Settings.load(), identity)``."""
    from sevn.config import Settings
    from sevn.observability.setup import setup

    return setup(Settings.load(), host_identity())


def fake_logfire_token() -> str:
    """A generated write token in Logfire's shape. It is not a real credential."""
    return "pylf_v1_us_" + secrets.token_hex(24)


def emit_span(name: str = "probe", attributes: dict[str, Any] | None = None) -> Any:
    """Open and end one span on the global provider; return its span context."""
    from opentelemetry import trace

    tracer = trace.get_tracer("sevn.tests")
    with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
        return span.get_span_context()


@contextmanager
def loguru_warnings() -> Iterator[list[Any]]:
    """Collect loguru records at WARNING and above while the block runs."""
    from sevn.log import logger

    found: list[Any] = []
    sink_id = logger.add(lambda message: found.append(message.record), level="WARNING")
    try:
        yield found
    finally:
        logger.complete()
        logger.remove(sink_id)


def warning_texts(records: list[Any]) -> list[str]:
    return [str(record["message"]) for record in records]


__all__ = [
    "arm_observability",
    "emit_span",
    "fake_logfire_token",
    "host_identity",
    "loguru_warnings",
    "otlp_section",
    "start_observability",
    "store_secret",
    "warning_texts",
    "write_observability_config",
]
