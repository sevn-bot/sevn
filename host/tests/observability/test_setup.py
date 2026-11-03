"""Config, setup, exporters and presets (plan 0015 D1-D4, D10, D12).

Every exporter in this file points at a loopback receiver from ``support.spans``.
Nothing is sent over the network.
"""

from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path
from typing import Any

import pytest
from support.observability import (
    arm_observability,
    emit_span,
    fake_logfire_token,
    host_identity,
    loguru_warnings,
    otlp_section,
    start_observability,
    store_secret,
)
from support.spans import (
    OtlpReceiver,
    dead_port,
    global_logger_provider_is_sdk,
    global_meter_provider_is_sdk,
    global_tracer_provider_is_sdk,
)

pytestmark = pytest.mark.usefixtures("otel_clean")


def _choose() -> str:
    from sevn.config import Settings
    from sevn.observability.setup import choose_exporter

    return choose_exporter(Settings.load())


def _resolve() -> Any:
    from sevn.config import Settings
    from sevn.observability.presets import resolve

    return resolve(Settings.load().observability)


def _load_error() -> str:
    from sevn.config import Settings
    from sevn.errors import ConfigError

    with pytest.raises(ConfigError) as caught:
        Settings.load()
    return str(caught.value)


def _otel_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name.startswith("opentelemetry") and record.levelno >= logging.WARNING
    ]


# --- D1: settings ------------------------------------------------------------


def test_defaults_match_the_locked_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.config import ObservabilitySettings, Settings

    arm_observability(monkeypatch, tmp_path)
    loaded = Settings.load().observability
    assert isinstance(loaded, ObservabilitySettings)
    assert loaded.exporter is None
    assert loaded.preset == ""
    assert loaded.endpoint == ""
    assert loaded.headers == {}
    assert loaded.protocol == "http/protobuf"
    assert loaded.capture_content is False
    assert loaded.sample_ratio == 1.0
    assert loaded.datadog_site == "datadoghq.com"
    assert loaded.service_name == "sevnd"


def test_env_override_uses_the_sevn_observability_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.config import Settings

    arm_observability(monkeypatch, tmp_path)
    monkeypatch.setenv("SEVN_OBSERVABILITY__EXPORTER", "otlp")
    monkeypatch.setenv("SEVN_OBSERVABILITY__ENDPOINT", "http://127.0.0.1:4318")
    monkeypatch.setenv("SEVN_OBSERVABILITY__SAMPLE_RATIO", "0.25")
    loaded = Settings.load().observability
    assert loaded.exporter == "otlp"
    assert loaded.endpoint == "http://127.0.0.1:4318"
    assert loaded.sample_ratio == 0.25
    assert _choose() == "otlp"


def test_unset_exporter_with_logfire_token_selects_logfire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm_observability(monkeypatch, tmp_path)
    store_secret("logfire/token", fake_logfire_token())
    assert _choose() == "logfire"


def test_unset_exporter_without_token_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm_observability(monkeypatch, tmp_path)
    assert _choose() == "none"


def test_explicit_none_beats_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    arm_observability(monkeypatch, tmp_path, 'exporter = "none"')
    store_secret("logfire/token", fake_logfire_token())
    monkeypatch.setenv("LOGFIRE_BASE_URL", otlp_receiver.url)
    assert _choose() == "none"
    handle = start_observability()
    assert handle.exporter == "none"
    emit_span("probe")
    handle.shutdown()
    assert otlp_receiver.requests == []
    assert not global_tracer_provider_is_sdk()


def test_explicit_otlp_without_token_is_otlp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm_observability(monkeypatch, tmp_path, otlp_section("http://127.0.0.1:4318"))
    assert _choose() == "otlp"


def test_logfire_token_exports_through_logfire_with_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    """Auto mode with a token configures the Logfire SDK; LOGFIRE_BASE_URL keeps it local."""
    token = fake_logfire_token()
    arm_observability(monkeypatch, tmp_path)
    store_secret("logfire/token", token)
    monkeypatch.setenv("LOGFIRE_BASE_URL", otlp_receiver.url)
    handle = start_observability()
    try:
        assert handle.exporter == "logfire"
        emit_span("probe")
    finally:
        handle.shutdown()
    otlp_receiver.wait_for(lambda seen: any(span.name == "probe" for span in seen.spans()))
    traces = otlp_receiver.signal_requests("traces")
    assert traces, otlp_receiver.requests
    assert any(token in item.headers.get("authorization", "") for item in traces)


# --- D2: off means nothing is installed ----------------------------------------


def test_off_installs_no_sdk_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from opentelemetry import trace

    arm_observability(monkeypatch, tmp_path)
    handle = start_observability()
    try:
        assert handle.exporter == "none"
        assert not global_tracer_provider_is_sdk()
        assert not global_meter_provider_is_sdk()
        assert not global_logger_provider_is_sdk()
        span = trace.get_tracer("sevn.tests").start_span("probe")
        assert not span.is_recording()
        span.end()
    finally:
        handle.shutdown()


def test_off_makes_no_outbound_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    """Standard OTEL_* and LOGFIRE_* variables alone never turn export on."""
    arm_observability(monkeypatch, tmp_path)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", otlp_receiver.url)
    monkeypatch.setenv("LOGFIRE_BASE_URL", otlp_receiver.url)
    handle = start_observability()
    emit_span("probe")
    handle.shutdown()
    assert handle.exporter == "none"
    assert otlp_receiver.requests == []


def test_resource_attributes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    import sevn

    arm_observability(monkeypatch, tmp_path, otlp_section(otlp_receiver.url))
    monkeypatch.setenv("SEVN_ENV", "staging")
    identity = host_identity()
    handle = start_observability()
    emit_span("probe")
    handle.shutdown()
    spans = [span for span in otlp_receiver.spans() if span.name == "probe"]
    assert len(spans) == 1, otlp_receiver.requests
    resource = spans[0].resource
    assert resource["service.name"] == "sevnd"
    assert resource["service.version"] == sevn.__version__
    assert resource["sevn.host_id"] == identity.host_id
    assert resource["deployment.environment"] == "staging"
    assert resource["deployment.environment.name"] == "staging"


def test_deployment_environment_defaults_to_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    arm_observability(
        monkeypatch,
        tmp_path,
        otlp_section(otlp_receiver.url, 'service_name = "sevnd-lab"'),
    )
    handle = start_observability()
    emit_span("probe")
    handle.shutdown()
    resource = next(span.resource for span in otlp_receiver.spans() if span.name == "probe")
    assert resource["deployment.environment"] == "local"
    assert resource["deployment.environment.name"] == "local"
    assert resource["service.name"] == "sevnd-lab"


# --- D1 + D4: headers are secret refs -------------------------------------------


def test_plain_header_value_is_a_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = "plain-" + secrets.token_hex(12)
    arm_observability(
        monkeypatch,
        tmp_path,
        otlp_section("http://127.0.0.1:4318", f'headers = {{ "x-api-key" = "{plain}" }}'),
    )
    message = _load_error()
    assert "observability" in message
    assert "secret://" in message
    # The error names the header, never the value it refused.
    assert plain not in message


def test_header_secret_ref_resolved_only_in_exporter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    from sevn.config import Settings

    value = secrets.token_urlsafe(24)
    arm_observability(
        monkeypatch,
        tmp_path,
        otlp_section(otlp_receiver.url, 'headers = { "x-sevn-key" = "secret://test/otlp_key" }'),
    )
    store_secret("test/otlp_key", value)
    target = _resolve()
    assert target.trace_headers["x-sevn-key"] == "secret://test/otlp_key"
    assert value not in Settings.load().model_dump_json()
    handle = start_observability()
    emit_span("probe")
    handle.shutdown()
    traces = otlp_receiver.signal_requests("traces")
    assert traces, otlp_receiver.requests
    assert all(item.headers.get("x-sevn-key") == value for item in traces)


def test_missing_header_secret_leaves_tracing_off_and_logs_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    arm_observability(
        monkeypatch,
        tmp_path,
        otlp_section(otlp_receiver.url, 'headers = { "x-sevn-key" = "secret://test/absent" }'),
    )
    with loguru_warnings() as warnings:
        handle = start_observability()
        emit_span("probe")
        handle.shutdown()
    assert handle.exporter == "none"
    assert not global_tracer_provider_is_sdk()
    assert otlp_receiver.requests == []
    assert len(warnings) == 1, [str(record["message"]) for record in warnings]


def test_setup_after_another_provider_stays_off_and_logs_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    # The OTel API keeps the first global provider for the process, so a later
    # setup() could never reach its own exporters: it must say so and stay off.
    trace.set_tracer_provider(TracerProvider())
    arm_observability(monkeypatch, tmp_path, otlp_section(otlp_receiver.url))
    with loguru_warnings() as warnings:
        handle = start_observability()
        emit_span("probe")
        handle.shutdown()
    assert handle.exporter == "none"
    assert otlp_receiver.requests == []
    messages = [str(record["message"]) for record in warnings]
    assert len(messages) == 1, messages
    assert "already installed" in messages[0]


# --- D4: endpoints and presets ----------------------------------------------------


@pytest.mark.parametrize(
    ("protocol", "traces", "logs", "metrics"),
    [
        (
            "http/protobuf",
            "http://localhost:4318/v1/traces",
            "http://localhost:4318/v1/logs",
            "http://localhost:4318/v1/metrics",
        ),
        ("grpc", "http://localhost:4317", "http://localhost:4317", "http://localhost:4317"),
    ],
)
def test_datadog_agent_preset_defaults_to_localhost_4318(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    protocol: str,
    traces: str,
    logs: str,
    metrics: str,
) -> None:
    arm_observability(
        monkeypatch,
        tmp_path,
        f'exporter = "otlp"\npreset = "datadog-agent"\nprotocol = "{protocol}"',
    )
    target = _resolve()
    assert target.protocol == protocol
    assert target.traces_endpoint == traces
    assert target.logs_endpoint == logs
    assert target.metrics_endpoint == metrics
    assert target.trace_headers == {}
    assert target.log_headers == {}
    assert target.metric_headers == {}
    assert target.loopback is True


def test_datadog_agent_preset_honours_an_explicit_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm_observability(
        monkeypatch,
        tmp_path,
        'exporter = "otlp"\npreset = "datadog-agent"\nendpoint = "http://127.0.0.1:14318"',
    )
    target = _resolve()
    assert target.traces_endpoint == "http://127.0.0.1:14318/v1/traces"
    assert target.loopback is True


@pytest.mark.parametrize(
    "site",
    ["datadoghq.com", "datadoghq.eu", "us3.datadoghq.com", "ap1.datadoghq.com", "ddog-gov.com"],
)
def test_datadog_agentless_preset_sets_site_endpoint_and_key_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, site: str
) -> None:
    arm_observability(
        monkeypatch,
        tmp_path,
        f'exporter = "otlp"\npreset = "datadog-agentless"\ndatadog_site = "{site}"',
    )
    target = _resolve()
    assert target.protocol == "http/protobuf"
    assert target.traces_endpoint == f"https://otlp.{site}/v1/traces"
    assert target.logs_endpoint == f"https://otlp.{site}/v1/logs"
    assert target.metrics_endpoint == f"https://otlp.{site}/v1/metrics"
    assert target.trace_headers == {
        "dd-api-key": "secret://datadog/api_key",
        "dd-otlp-source": "llmobs",
        "compute_stats": "true",
    }
    assert target.log_headers == {"dd-api-key": "secret://datadog/api_key"}
    assert target.metric_headers == {"dd-api-key": "secret://datadog/api_key"}
    assert target.loopback is False


def test_datadog_agentless_key_ref_comes_from_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm_observability(
        monkeypatch,
        tmp_path,
        'exporter = "otlp"\npreset = "datadog-agentless"\n'
        'headers = { "dd-api-key" = "secret://ops/datadog" }',
    )
    target = _resolve()
    assert target.trace_headers["dd-api-key"] == "secret://ops/datadog"
    assert target.log_headers == {"dd-api-key": "secret://ops/datadog"}


def test_datadog_agentless_rejects_grpc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arm_observability(
        monkeypatch,
        tmp_path,
        'exporter = "otlp"\npreset = "datadog-agentless"\nprotocol = "grpc"',
    )
    message = _load_error()
    assert "observability" in message
    assert "grpc" in message


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("", "http://127.0.0.1:24318/v1/traces"),
        ("http://127.0.0.1:4318", "http://127.0.0.1:4318/v1/traces"),
    ],
)
def test_standard_otel_endpoint_only_fills_an_empty_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: str, expected: str
) -> None:
    arm_observability(monkeypatch, tmp_path, otlp_section(endpoint))
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:24318")
    target = _resolve()
    assert target.traces_endpoint == expected


def test_otlp_http_posts_protobuf_to_signal_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    arm_observability(monkeypatch, tmp_path, otlp_section(otlp_receiver.url))
    handle = start_observability()
    assert handle.exporter == "otlp"
    emit_span("probe")
    handle.shutdown()
    traces = otlp_receiver.signal_requests("traces")
    assert traces, otlp_receiver.requests
    assert all(item.path == "/v1/traces" for item in traces)
    assert all(item.headers.get("content-type") == "application/x-protobuf" for item in traces)
    assert [span.name for span in otlp_receiver.spans()].count("probe") == 1


def test_grpc_protocol_uses_grpc_exporter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    grpc_receiver: Any,
    otlp_receiver: OtlpReceiver,
) -> None:
    endpoint = grpc_receiver.endpoint
    arm_observability(monkeypatch, tmp_path, otlp_section(endpoint, 'protocol = "grpc"'))
    handle = start_observability()
    emit_span("probe")
    handle.shutdown()
    spans = grpc_receiver.spans()
    assert [span.name for span in spans].count("probe") == 1
    assert otlp_receiver.requests == []


# --- D10: sampling ----------------------------------------------------------------


@pytest.mark.parametrize("ratio", ["-0.1", "1.5"])
def test_sample_ratio_out_of_range_is_a_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ratio: str
) -> None:
    arm_observability(
        monkeypatch, tmp_path, otlp_section("http://127.0.0.1:4318", f"sample_ratio = {ratio}")
    )
    message = _load_error()
    assert "sample_ratio" in message


@pytest.mark.parametrize("ratio", ["0.0", "1.0"])
def test_sample_ratio_bounds_are_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ratio: str
) -> None:
    from sevn.config import Settings

    arm_observability(
        monkeypatch, tmp_path, otlp_section("http://127.0.0.1:4318", f"sample_ratio = {ratio}")
    )
    assert Settings.load().observability.sample_ratio == float(ratio)


@pytest.mark.parametrize(("ratio", "exported"), [("0.0", 0), ("1.0", 5)])
def test_sample_ratio_controls_what_is_exported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    otlp_receiver: OtlpReceiver,
    ratio: str,
    exported: int,
) -> None:
    arm_observability(
        monkeypatch, tmp_path, otlp_section(otlp_receiver.url, f"sample_ratio = {ratio}")
    )
    handle = start_observability()
    for _ in range(5):
        emit_span("probe")
    handle.shutdown()
    assert [span.name for span in otlp_receiver.spans()].count("probe") == exported


# --- D12: failure policy ------------------------------------------------------------


def test_unreachable_collector_never_fails_startup_and_logs_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from opentelemetry import trace

    caplog.set_level(logging.WARNING)
    arm_observability(monkeypatch, tmp_path, otlp_section(f"http://127.0.0.1:{dead_port()}"))
    with loguru_warnings() as warnings:
        handle = start_observability()
        assert handle.exporter == "otlp"
        provider = trace.get_tracer_provider()
        for _ in range(2):
            emit_span("probe")
            flush = getattr(provider, "force_flush", None)
            assert callable(flush)
            flush()
        handle.shutdown()
    sevn_warnings = [
        record for record in warnings if not record["name"].startswith("opentelemetry")
    ]
    total = len(sevn_warnings) + len(_otel_warnings(caplog))
    assert total == 1, (
        [str(record["message"]) for record in sevn_warnings],
        [record.getMessage() for record in _otel_warnings(caplog)],
    )


def test_lifespan_with_unreachable_collector_serves_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from support.http_app import running_app

    arm_observability(
        monkeypatch,
        tmp_path,
        otlp_section(f"http://127.0.0.1:{dead_port()}"),
        extra='[http]\nhost = "127.0.0.1"\nport = 8787',
    )
    with running_app(tmp_path, monkeypatch) as (_app, _token, client):
        response = client.get("/health")
        assert response.status_code == 200
        # The lifespan did set up the exporter; it just cannot reach the collector.
        assert global_tracer_provider_is_sdk()


def test_lifespan_sets_up_and_flushes_on_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    """The HTTP lifespan runs setup and shutdown; FastAPI requests become spans."""
    from support.http_app import running_app

    arm_observability(
        monkeypatch,
        tmp_path,
        otlp_section(otlp_receiver.url),
        extra='[http]\nhost = "127.0.0.1"\nport = 8787',
    )
    with running_app(tmp_path, monkeypatch) as (_app, _token, client):
        response = client.get("/health")
        assert response.status_code == 200
    spans = otlp_receiver.spans()
    routes = [span for span in spans if span.attributes.get("http.route") == "/health"]
    assert routes, [span.name for span in spans]
    assert routes[0].resource["service.name"] == "sevnd"


def test_shutdown_flushes_pending_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    arm_observability(monkeypatch, tmp_path, otlp_section(otlp_receiver.url))
    handle = start_observability()
    emit_span("pending")
    # The batch processor holds the span; only shutdown sends it now.
    handle.shutdown()
    assert [span.name for span in otlp_receiver.spans()].count("pending") == 1


def test_shutdown_within_cap_when_collector_hangs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with OtlpReceiver(hang_s=30) as hanging:
        arm_observability(monkeypatch, tmp_path, otlp_section(hanging.url))
        handle = start_observability()
        emit_span("stuck")
        started = time.monotonic()
        handle.shutdown()
        elapsed = time.monotonic() - started
    assert elapsed < 6.5, f"shutdown blocked {elapsed:.1f}s; the cap is 5 s"


def test_shutdown_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    arm_observability(monkeypatch, tmp_path, otlp_section(otlp_receiver.url))
    handle = start_observability()
    emit_span("probe")
    handle.shutdown()
    handle.shutdown()
    assert [span.name for span in otlp_receiver.spans()].count("probe") == 1
