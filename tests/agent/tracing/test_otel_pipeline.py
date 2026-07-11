"""Tests for shared OTel pipeline + TraceEvent bridge (W1)."""

from __future__ import annotations

import os
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExportResult

from sevn.agent.tracing.otel_pipeline import (
    configure_gateway_otel,
    is_otel_export_configured,
    reset_otel_pipeline_for_tests,
    resolve_otlp_targets,
)
from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceEvent
from sevn.agent.tracing.sink_factory import build_gateway_trace_sink
from sevn.agent.tracing.trace_event_bridge import TraceEventOtelBridge
from sevn.config.workspace_config import TraceSinkEntry, TracingConfig, WorkspaceConfig
from sevn.workspace.layout import WorkspaceLayout


class _RecordingSpanExporter:
    """Capture exported spans for assertions."""

    def __init__(self) -> None:
        self.spans: list[Any] = []

    def export(self, spans: Any) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        _ = timeout_millis
        return True


@pytest.fixture(autouse=True)
def _reset_otel() -> None:
    reset_otel_pipeline_for_tests()
    yield
    reset_otel_pipeline_for_tests()


def _sample_event(
    *,
    kind: str = "gateway.boot",
    span_id: str = "span-test",
    parent_span_id: str | None = None,
    turn_id: str = SYSTEM_TURN_ID,
) -> TraceEvent:
    return TraceEvent(
        kind=kind,
        span_id=span_id,
        parent_span_id=parent_span_id,
        session_id="sess",
        turn_id=turn_id,
        tier=None,
        ts_start_ns=100,
        ts_end_ns=200,
        status="ok",
        attrs={"note": "test"},
    )


@pytest.mark.asyncio
async def test_no_token_boot_configures_provider_without_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    workspace = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    provider = configure_gateway_otel(workspace)
    assert isinstance(provider, TracerProvider)
    assert is_otel_export_configured() is False


def test_configure_gateway_otel_passes_resolved_token_to_logfire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeLogfire:
        @staticmethod
        def configure(**kwargs: object) -> object:
            captured.update(kwargs)
            return object()

        @staticmethod
        def instrument_pydantic_ai() -> None:
            return None

        @staticmethod
        def instrument_httpx(**kwargs: object) -> None:
            _ = kwargs

    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "logfire", _FakeLogfire())
    workspace = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        tracing=TracingConfig(
            sinks=[
                TraceSinkEntry.model_validate(
                    {"type": "logfire", "token_ref": "${SECRET:encrypted_file:logfire.token}"},
                ),
            ],
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    configure_gateway_otel(workspace, resolved_tokens={0: "resolved-logfire-token"})
    assert captured.get("token") == "resolved-logfire-token"
    assert captured.get("send_to_logfire") is True
    assert is_otel_export_configured() is True


@pytest.mark.asyncio
async def test_trace_event_bridge_nests_child_under_turn_root() -> None:
    exporter = _RecordingSpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(
        __import__(
            "opentelemetry.sdk.trace.export",
            fromlist=["SimpleSpanProcessor"],
        ).SimpleSpanProcessor(exporter),
    )
    trace.set_tracer_provider(provider)
    bridge = TraceEventOtelBridge(tracer=provider.get_tracer("test"))

    turn_id = "turn-1"
    turn_span = "turn-root-span"
    await bridge.emit(
        TraceEvent(
            kind="gateway.turn.start",
            span_id=turn_span,
            parent_span_id=None,
            session_id="sess",
            turn_id=turn_id,
            tier=None,
            ts_start_ns=100,
            ts_end_ns=100,
            status="started",
            attrs={},
        ),
    )
    await bridge.emit(
        _sample_event(
            kind="triage.start",
            span_id="triage-span",
            parent_span_id=turn_span,
            turn_id=turn_id,
        ),
    )
    await bridge.emit(
        _sample_event(kind="gateway.turn.complete", span_id="complete", turn_id=turn_id),
    )
    provider.force_flush()
    names = [span.name for span in exporter.spans]
    assert "gateway.turn.start" in names
    assert "triage.start" in names
    assert "gateway.turn.complete" not in names


def test_build_gateway_trace_sink_with_fake_otlp_endpoint(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, str]] = []

    class _CapturingOtlpExporter(_RecordingSpanExporter):
        def __init__(
            self,
            endpoint: str = "",
            headers: dict[str, str] | None = None,
            **kwargs: Any,
        ) -> None:
            _ = endpoint, kwargs
            captured.append(dict(headers or {}))
            super().__init__()

    monkeypatch.setattr(
        "sevn.agent.tracing.otel_pipeline.OTLPSpanExporter",
        _CapturingOtlpExporter,
    )
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    workspace = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        tracing=TracingConfig(
            sinks=[
                TraceSinkEntry.model_validate({"type": "sqlite"}),
                TraceSinkEntry.model_validate(
                    {
                        "type": "otel",
                        "endpoint": "http://127.0.0.1:4318/v1/traces",
                        "token_ref": "${ENV:LOGFIRE_TOKEN}",
                    },
                ),
            ],
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)
    os.environ["LOGFIRE_TOKEN"] = "offline-test-token"
    try:
        sink = build_gateway_trace_sink(workspace, layout)
        assert sink is not None
        assert is_otel_export_configured() is True
        targets = resolve_otlp_targets(workspace)
        assert len(targets) == 1
    finally:
        os.environ.pop("LOGFIRE_TOKEN", None)
