"""Trace context and collector settings for CLI runtimes (plan 0015 D6; green after W4).

K-CANARY: no export credential (the Logfire token, a Datadog API key, any
``headers`` value) reaches a child CLI's env.
"""

from __future__ import annotations

import importlib
import secrets
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_claude import FakeClaudeClient
from support.canary import canary
from support.chat import connected, load_modules, mint_id, ok, poll_rows, request
from support.observability import (
    arm_observability,
    fake_logfire_token,
    otlp_section,
    store_secret,
    write_observability_config,
)
from support.spans import named, one, traceparent_of, wait_spans

pytestmark = pytest.mark.usefixtures("otel_clean")

_OTEL_KEYS = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_SERVICE_NAME",
)
_CLAUDE_SCRIPT = [
    {"type": "system", "subtype": "init", "session_id": "sess_env"},
    {"type": "result", "usage": {}, "result": "ok"},
]


def _propagate() -> Any:
    return importlib.import_module("sevn.observability.propagate")


def _settings() -> Any:
    from sevn.config import Settings

    return Settings.load()


def _child_env(runtime: str, span: Any) -> dict[str, str]:
    return _propagate().child_env(runtime, span, settings=_settings())


def _span(name: str = "turn") -> Any:
    from opentelemetry import trace

    return trace.get_tracer("sevn.tests").start_span(name)


async def _claude_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeClaudeClient,
    section: str = "",
) -> None:
    """One Claude turn through the protocol. ``section`` is the ``[observability]`` table.

    ``connected`` rewrites ``config.toml`` when the host opens, so the table is
    written again inside the block, before the turn reads its settings.
    """
    from sevn.runtime.runtimes.claude import use_client
    from sevn.runtime.worker import bind

    use_client(fake)
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            write_observability_config(tmp_path, section)
            bind(host.hub)
            frame, _earlier = await request(
                client,
                "bots.create",
                {"name": "Claude", "runtime": "claude", "access": "full", "op_id": mint_id("op_")},
            )
            bot = ok(frame)
            frame, _earlier = await request(
                client,
                "bots.update",
                {"bot_id": bot["id"], "network": "on", "op_id": mint_id("op_")},
            )
            ok(frame)
            frame, _earlier = await request(
                client,
                "messages.send",
                {"bot_id": bot["id"], "text": "hello", "op_id": mint_id("op_")},
            )
            sent = ok(frame)
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (sent["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
    finally:
        use_client(None)


def _connect_env(fake: FakeClaudeClient) -> dict[str, str]:
    assert fake.connects, "the Claude runtime never connected"
    env = fake.connects[-1].get("env")
    assert isinstance(env, dict), fake.connects[-1]
    return {str(key): str(value) for key, value in env.items()}


# --- TRACEPARENT -------------------------------------------------------------------------


async def test_child_env_has_traceparent_of_turn_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any
) -> None:
    _propagate()
    arm_observability(monkeypatch, tmp_path)
    fake = FakeClaudeClient(script=_CLAUDE_SCRIPT)
    await _claude_turn(tmp_path, monkeypatch, fake)
    spans = await wait_spans(span_exporter, lambda found: bool(named(found, "turn")))
    turn = one(spans, "turn")
    env = _connect_env(fake)
    assert env["TRACEPARENT"] == traceparent_of(turn)


def test_child_env_traceparent_matches_the_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any
) -> None:
    _ = span_exporter
    arm_observability(monkeypatch, tmp_path)
    span = _span()
    try:
        context = span.get_span_context()
        env = _child_env("claude", span)
    finally:
        span.end()
    assert env["TRACEPARENT"] == f"00-{context.trace_id:032x}-{context.span_id:016x}-01"
    assert "TRACESTATE" not in env


def test_child_env_carries_tracestate_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any
) -> None:
    from opentelemetry import trace
    from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState

    _ = span_exporter
    arm_observability(monkeypatch, tmp_path)
    parent = SpanContext(
        trace_id=int(secrets.token_hex(16), 16),
        span_id=int(secrets.token_hex(8), 16),
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=TraceState([("sevn", "lane1")]),
    )
    context = trace.set_span_in_context(NonRecordingSpan(parent))
    span = trace.get_tracer("sevn.tests").start_span("turn", context=context)
    try:
        env = _child_env("claude", span)
    finally:
        span.end()
    assert env["TRACESTATE"] == "sevn=lane1"
    assert env["TRACEPARENT"].split("-")[1] == f"{parent.trace_id:032x}"


def test_child_env_without_a_valid_span_has_no_traceparent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opentelemetry.trace import INVALID_SPAN

    arm_observability(monkeypatch, tmp_path)
    env = _child_env("claude", INVALID_SPAN)
    assert "TRACEPARENT" not in env
    assert "TRACESTATE" not in env


# --- loopback collectors only ------------------------------------------------------------


@pytest.mark.parametrize(
    ("section", "endpoint", "protocol"),
    [
        ('exporter = "otlp"\npreset = "datadog-agent"', "http://localhost:4318", "http/protobuf"),
        (
            'exporter = "otlp"\npreset = "datadog-agent"\nprotocol = "grpc"',
            "http://localhost:4317",
            "grpc",
        ),
        (otlp_section("http://127.0.0.1:4318"), "http://127.0.0.1:4318", "http/protobuf"),
        (otlp_section("http://localhost:14318"), "http://localhost:14318", "http/protobuf"),
        (otlp_section("http://[::1]:4318"), "http://[::1]:4318", "http/protobuf"),
    ],
)
def test_loopback_collector_env_passed_to_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    span_exporter: Any,
    section: str,
    endpoint: str,
    protocol: str,
) -> None:
    _ = span_exporter
    arm_observability(monkeypatch, tmp_path, section)
    span = _span()
    try:
        env = _child_env("opencode", span)
    finally:
        span.end()
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == endpoint
    assert env["OTEL_EXPORTER_OTLP_PROTOCOL"] == protocol
    assert env["OTEL_SERVICE_NAME"] == "sevn-cli-opencode"
    assert "OTEL_EXPORTER_OTLP_HEADERS" not in env
    assert "TRACEPARENT" in env


@pytest.mark.parametrize(
    "case",
    ["datadog_agentless", "remote_otlp", "logfire_token", "loopback_with_header"],
)
def test_remote_or_credentialed_exporter_env_not_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any, case: str
) -> None:
    _ = span_exporter
    if case == "datadog_agentless":
        section = 'exporter = "otlp"\npreset = "datadog-agentless"'
    elif case == "remote_otlp":
        section = otlp_section(
            "https://otlp.example.com", 'headers = { "x-api-key" = "secret://ops/otlp" }'
        )
    elif case == "logfire_token":
        section = ""
    else:
        section = otlp_section(
            "http://127.0.0.1:4318", 'headers = { "x-api-key" = "secret://ops/otlp" }'
        )
    arm_observability(monkeypatch, tmp_path, section)
    with canary() as probe:
        store_secret("datadog/api_key", probe.value)
        store_secret("ops/otlp", probe.value)
        store_secret("logfire/token", probe.value)
        span = _span()
        try:
            env = _child_env("claude", span)
        finally:
            span.end()
        assert "OTEL_EXPORTER_OTLP_HEADERS" not in env
        assert all(probe.value not in value for value in env.values())
        assert "TRACEPARENT" in env
        if case != "loopback_with_header":
            assert not any(key in env for key in _OTEL_KEYS), env
            assert "CLAUDE_CODE_ENABLE_TELEMETRY" not in env


@pytest.mark.parametrize(
    ("runtime", "section", "enabled"),
    [
        ("claude", otlp_section("http://127.0.0.1:4318"), True),
        ("claude", 'exporter = "otlp"\npreset = "datadog-agent"', True),
        ("claude", 'exporter = "otlp"\npreset = "datadog-agentless"', False),
        ("claude", otlp_section("https://collector.example.com"), False),
        ("claude", 'exporter = "none"', False),
        ("opencode", otlp_section("http://127.0.0.1:4318"), False),
    ],
)
def test_claude_telemetry_switch_only_with_loopback_collector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    span_exporter: Any,
    runtime: str,
    section: str,
    enabled: bool,
) -> None:
    _ = span_exporter
    arm_observability(monkeypatch, tmp_path, section)
    span = _span()
    try:
        env = _child_env(runtime, span)
    finally:
        span.end()
    if enabled:
        assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    else:
        assert "CLAUDE_CODE_ENABLE_TELEMETRY" not in env


async def test_claude_runtime_gets_loopback_collector_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any
) -> None:
    _propagate()
    section = otlp_section("http://127.0.0.1:4318")
    arm_observability(monkeypatch, tmp_path, section)
    fake = FakeClaudeClient(script=_CLAUDE_SCRIPT)
    await _claude_turn(tmp_path, monkeypatch, fake, section)
    await wait_spans(span_exporter, lambda found: bool(named(found, "turn")))
    env = _connect_env(fake)
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://127.0.0.1:4318"
    assert env["OTEL_SERVICE_NAME"] == "sevn-cli-claude"
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"


async def test_claude_runtime_child_env_holds_no_export_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any
) -> None:
    """K-CANARY: the token and header secret stay out of the Claude CLI env."""
    _propagate()
    section = otlp_section(
        "http://127.0.0.1:4318", 'headers = { "x-api-key" = "secret://ops/otlp" }'
    )
    arm_observability(monkeypatch, tmp_path, section)
    # A token in the parent env must not ride along either.
    monkeypatch.setenv("LOGFIRE_TOKEN", fake_logfire_token())
    with canary() as probe:
        store_secret("ops/otlp", probe.value)
        store_secret("logfire/token", probe.value)
        fake = FakeClaudeClient(script=_CLAUDE_SCRIPT)
        await _claude_turn(tmp_path, monkeypatch, fake, section)
        await wait_spans(span_exporter, lambda found: bool(named(found, "turn")))
        env = _connect_env(fake)
        assert "TRACEPARENT" in env
        # The loopback collector is configured, so the turn did read this config.
        assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://127.0.0.1:4318"
        assert "OTEL_EXPORTER_OTLP_HEADERS" not in env
        assert env.get("LOGFIRE_TOKEN", "") == ""
        assert all(probe.value not in value for value in env.values())
        probe.assert_absent(probe.value)
