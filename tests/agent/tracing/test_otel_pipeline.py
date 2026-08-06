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
from sevn.agent.tracing.trace_event_bridge import TraceEventOtelBridge, TraceExportFilter
from sevn.config.workspace_config import (
    TraceExportConfig,
    TraceSinkEntry,
    TracingConfig,
    WorkspaceConfig,
)
from sevn.tracing.otel_pipeline import (
    _httpx_async_request_hook,
    _httpx_request_hook,
    _keep_sevn_correlation_ids,
)
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
        ScrubbingOptions = staticmethod(lambda **kw: kw)

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


class _FakeSpan:
    """Minimal span double exposing the read/write attribute surface the hook uses."""

    def __init__(self, attributes: dict[str, Any]) -> None:
        self.attributes = dict(attributes)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value


_BOT_URL = "https://api.telegram.org/bot123456:AAHsecrettokenvalue/getUpdates"


@pytest.mark.parametrize("url_key", ["url.full", "http.url"])
def test_httpx_request_hook_strips_bot_token_from_url(url_key: str) -> None:
    """Both URL attribute keys are in Logfire's SAFE_KEYS, so we must redact them."""
    span = _FakeSpan({url_key: _BOT_URL})
    _httpx_request_hook(span, httpx_request_info(_BOT_URL))
    assert "AAHsecrettokenvalue" not in span.attributes[url_key]
    assert span.attributes[url_key] == "https://api.telegram.org/bot<redacted>/getUpdates"


@pytest.mark.asyncio
async def test_httpx_async_request_hook_strips_bot_token() -> None:
    """The gateway's Telegram transport is async — this is the hook that fires."""
    span = _FakeSpan({"url.full": _BOT_URL})
    await _httpx_async_request_hook(span, httpx_request_info(_BOT_URL))
    assert "AAHsecrettokenvalue" not in span.attributes["url.full"]


def test_httpx_request_hook_leaves_unrelated_urls_untouched() -> None:
    span = _FakeSpan({"url.full": "https://api.openai.com/v1/chat/completions"})
    _httpx_request_hook(span, httpx_request_info("https://api.openai.com/v1/chat/completions"))
    assert span.attributes["url.full"] == "https://api.openai.com/v1/chat/completions"


def test_httpx_request_hook_does_not_invent_absent_attributes() -> None:
    """Only keys the instrumentation already set are rewritten."""
    span = _FakeSpan({"url.full": _BOT_URL})
    _httpx_request_hook(span, httpx_request_info(_BOT_URL))
    assert "http.url" not in span.attributes


def httpx_request_info(url: str) -> Any:
    """Build the RequestInfo shape the httpx hooks read ``url`` from."""
    import httpx
    from logfire.integrations.httpx import RequestInfo

    return RequestInfo(
        method=b"POST",
        url=httpx.URL(url),
        headers=httpx.Headers(),
        stream=None,
        extensions=None,
    )


class _Match:
    """ScrubMatch double for the scrubbing callback."""

    def __init__(self, path: tuple[str, ...], value: Any) -> None:
        self.path = path
        self.value = value


def test_scrub_callback_keeps_session_id_and_scrubs_everything_else() -> None:
    """``sevn.session_id`` matches Logfire's default 'session' pattern; keep it."""
    kept = _keep_sevn_correlation_ids(_Match(("attributes", "sevn.session_id"), "sess-1"))
    assert kept == "sess-1"
    assert _keep_sevn_correlation_ids(_Match(("attributes", "password"), "hunter2")) is None
    assert _keep_sevn_correlation_ids(_Match(("attributes", "api_key"), "sk-x")) is None
    # Not allowlisted just because it starts with ``sevn.``.
    assert _keep_sevn_correlation_ids(_Match(("attributes", "sevn.secret"), "x")) is None


def test_configure_gateway_otel_does_not_capture_http_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: ``capture_all=True`` duplicated every LLM and Telegram payload."""
    httpx_kwargs: dict[str, object] = {}
    configure_kwargs: dict[str, object] = {}

    class _FakeLogfire:
        ScrubbingOptions = staticmethod(lambda **kw: kw)

        @staticmethod
        def configure(**kwargs: object) -> object:
            configure_kwargs.update(kwargs)
            return object()

        @staticmethod
        def instrument_pydantic_ai() -> None:
            return None

        @staticmethod
        def instrument_httpx(**kwargs: object) -> None:
            httpx_kwargs.update(kwargs)

    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "logfire", _FakeLogfire())
    workspace = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        tracing=TracingConfig(sinks=[TraceSinkEntry.model_validate({"type": "logfire"})]),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    configure_gateway_otel(workspace, resolved_tokens={0: "tok"})

    assert httpx_kwargs.get("capture_all") is None
    assert httpx_kwargs.get("capture_headers") is True
    assert httpx_kwargs.get("request_hook") is _httpx_request_hook
    assert httpx_kwargs.get("async_request_hook") is _httpx_async_request_hook
    assert configure_kwargs.get("scrubbing") is not None


@pytest.mark.asyncio
async def test_export_filter_drops_excluded_kinds_but_keeps_turn_spine() -> None:
    """Excluded kinds never reach the provider; turn roots are always exported."""
    exporter = _RecordingSpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(
        __import__(
            "opentelemetry.sdk.trace.export",
            fromlist=["SimpleSpanProcessor"],
        ).SimpleSpanProcessor(exporter),
    )
    bridge = TraceEventOtelBridge(
        tracer=provider.get_tracer("test"),
        export_filter=TraceExportFilter(exclude_kinds=("snapshot.checkpoint", "debug.*")),
    )
    await bridge.emit(_sample_event(kind="snapshot.checkpoint", span_id="s1"))
    await bridge.emit(_sample_event(kind="debug.anything", span_id="s2"))
    await bridge.emit(_sample_event(kind="triage.start", span_id="s3"))
    await bridge.emit(
        _sample_event(kind="gateway.turn.start", span_id="s4", turn_id="t-keep"),
    )
    provider.force_flush()

    names = [span.name for span in exporter.spans]
    assert "snapshot.checkpoint" not in names
    assert "debug.anything" not in names
    assert "triage.start" in names


def test_export_filter_defaults_and_overrides() -> None:
    assert TraceExportFilter().exclude_kinds == ("snapshot.checkpoint",)
    assert TraceExportFilter.from_kinds(None).allows("snapshot.checkpoint") is False
    # An explicit empty list opts back in to exporting everything.
    assert TraceExportFilter.from_kinds([]).allows("snapshot.checkpoint") is True
    assert TraceExportFilter.from_kinds(["  ", "x.y"]).exclude_kinds == ("x.y",)


def test_build_gateway_trace_sink_honours_configured_export_filter(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``tracing.export.exclude_kinds`` reaches the bridge the factory registers."""
    from sevn.agent.tracing.trace_event_bridge import get_trace_event_bridge

    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": "."}',
        encoding="utf-8",
    )
    workspace = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        tracing=TracingConfig(
            sinks=[TraceSinkEntry.model_validate({"type": "sqlite"})],
            export=TraceExportConfig(exclude_kinds=["tool.*"]),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)
    build_gateway_trace_sink(workspace, layout)

    bridge = get_trace_event_bridge()
    assert bridge is not None
    assert bridge._filter.allows("tool.invoke") is False
    assert bridge._filter.allows("snapshot.checkpoint") is True


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
