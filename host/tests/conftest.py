"""Shared fixtures. Product imports stay inside fixtures so collection succeeds."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# Append, do not prepend: host/tests/secrets must not shadow the stdlib secrets module.
_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.append(_TESTS_DIR)

import pytest  # noqa: E402
from support.http_app import running_app  # noqa: E402


@pytest.fixture
def host_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[object, str, object]]:
    """Lifespan stays open. Yields `(app, token, client)`."""
    with running_app(tmp_path, monkeypatch) as opened:
        yield opened


# --- plan 0015: OpenTelemetry fixtures (support/spans.py) ---------------------


@pytest.fixture
def otel_clean() -> Iterator[None]:
    """The OTel API starts and ends the test with no global provider."""
    from support.spans import reset_otel_globals

    reset_otel_globals()
    try:
        yield
    finally:
        reset_otel_globals()


@pytest.fixture
def span_exporter() -> Iterator[Any]:
    """An ``InMemorySpanExporter`` behind the global SDK tracer provider."""
    from support.spans import in_memory_spans

    with in_memory_spans() as exporter:
        yield exporter


@pytest.fixture
def otlp_receiver() -> Iterator[Any]:
    """A loopback OTLP/HTTP collector that records every request."""
    from support.spans import OtlpReceiver

    with OtlpReceiver() as receiver:
        yield receiver


@pytest.fixture
def grpc_receiver() -> Iterator[Any]:
    """A loopback OTLP/gRPC collector that records every request."""
    from support.spans import GrpcReceiver

    with GrpcReceiver() as receiver:
        yield receiver
