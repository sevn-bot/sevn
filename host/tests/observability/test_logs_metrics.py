"""Trace ids on log records, OTel log export, host gauges (plan 0015 D8, D9; green after W4)."""

from __future__ import annotations

import importlib
import json
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_ollama import FakeOllama
from support.canary import canary
from support.chat import connected, insert_job, load_modules, mint_id, ok, request
from support.observability import arm_observability, otlp_section, start_observability
from support.spans import OtlpReceiver, dead_port

pytestmark = [
    pytest.mark.usefixtures("otel_clean"),
    pytest.mark.xfail(reason="green after W4: logs and host metrics", strict=False),
]

_GAUGES = ("sevn.jobs.queued", "sevn.turns.running", "sevn.agents.open", "sevn.ollama.reachable")


@pytest.fixture
def host_logging(tmp_path: Path) -> Iterator[Path]:
    """``sevn.log.setup`` into a temporary JSON file; every sink is removed afterwards."""
    from sevn.log import logger, setup

    log_path = tmp_path / "logs" / "sevnd.log"
    setup(level="DEBUG", json_file=log_path)
    try:
        yield log_path
    finally:
        logger.complete()
        logger.remove()


def _json_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# --- D8: trace ids on records ----------------------------------------------------------


def test_loguru_record_has_trace_and_span_ids(span_exporter: Any, host_logging: Path) -> None:
    from opentelemetry import trace
    from sevn.log import logger

    _ = span_exporter
    importlib.import_module("sevn.observability.logs")
    found: list[Any] = []
    sink = logger.add(lambda message: found.append(message.record))
    try:
        with trace.get_tracer("sevn.tests").start_as_current_span("turn") as span:
            context = span.get_span_context()
            logger.info("inside the turn")
        logger.info("outside any span")
    finally:
        logger.complete()
        logger.remove(sink)
    inside = next(record for record in found if record["message"] == "inside the turn")
    assert inside["extra"]["trace_id"] == f"{context.trace_id:032x}"
    assert inside["extra"]["span_id"] == f"{context.span_id:016x}"
    line = next(item for item in _json_lines(host_logging) if item["message"] == "inside the turn")
    assert line["extra"]["trace_id"] == f"{context.trace_id:032x}"
    assert line["extra"]["span_id"] == f"{context.span_id:016x}"
    outside = next(record for record in found if record["message"] == "outside any span")
    assert not outside["extra"].get("trace_id")


def test_redaction_patcher_still_runs_with_trace_ids(
    span_exporter: Any, host_logging: Path
) -> None:
    from opentelemetry import trace
    from sevn.log import logger
    from sevn.secrets.registry import register

    _ = span_exporter
    importlib.import_module("sevn.observability.logs")
    name = "test/" + secrets.token_hex(6)
    value = secrets.token_urlsafe(32)
    register(name, value)
    with trace.get_tracer("sevn.tests").start_as_current_span("turn"):
        logger.info("leaked " + value)
    logger.complete()
    text = host_logging.read_text(encoding="utf-8")
    assert value not in text
    assert f"«redacted:{name}»" in text
    line = next(item for item in _json_lines(host_logging) if "leaked" in item["message"])
    assert line["extra"]["trace_id"]


# --- D8: OTel log export ----------------------------------------------------------------


def test_log_records_exported_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    """K-CANARY: exported log records carry the span ids and never the secret."""
    from opentelemetry import trace
    from sevn.log import logger

    arm_observability(monkeypatch, tmp_path, otlp_section(otlp_receiver.url))
    debug_marker = "debug-" + secrets.token_hex(6)
    with canary() as probe:
        handle = start_observability()
        try:
            with trace.get_tracer("sevn.tests").start_as_current_span("turn") as span:
                context = span.get_span_context()
                logger.info("tool said {detail}", detail=f"key={probe.value}")
                logger.warning("plain " + probe.value)
                logger.debug(debug_marker)
        finally:
            handle.shutdown()
        logs = otlp_receiver.logs()
        bodies = [str(record.body) for record in logs]
        said = [record for record in logs if "tool said" in str(record.body)]
        assert said, bodies
        assert said[0].trace_id == f"{context.trace_id:032x}"
        assert said[0].span_id == f"{context.span_id:016x}"
        assert any(f"«redacted:{probe.name}»" in body for body in bodies)
        assert not any(debug_marker in body for body in bodies)
        assert probe.value.encode() not in otlp_receiver.all_bytes()
        probe.assert_absent(probe.value)


def test_log_exporter_scrubs_without_the_loguru_patcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    """The log exporter wrapper runs ``scrub`` itself (D7), not only the loguru patcher."""
    from sevn.log import logger, redact
    from sevn.secrets.registry import register

    arm_observability(monkeypatch, tmp_path, otlp_section(otlp_receiver.url))
    name = "test/" + secrets.token_hex(6)
    value = secrets.token_urlsafe(32)
    register(name, value)
    handle = start_observability()
    logger.configure(patcher=None)
    try:
        logger.warning("unpatched " + value)
    finally:
        logger.configure(patcher=redact)
        handle.shutdown()
    bodies = [str(record.body) for record in otlp_receiver.logs()]
    assert any("unpatched" in body for body in bodies), bodies
    assert value.encode() not in otlp_receiver.all_bytes()


def test_tracing_off_installs_no_log_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    from sevn.log import logger

    arm_observability(monkeypatch, tmp_path)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", otlp_receiver.url)
    importlib.import_module("sevn.observability.logs")
    handle = start_observability()
    logger.warning("nowhere to go")
    handle.shutdown()
    assert otlp_receiver.requests == []


# --- D9: host gauges ----------------------------------------------------------------------


@pytest.mark.parametrize("ollama_up", [True, False])
async def test_gauges_report_queue_running_and_ollama(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    otlp_receiver: OtlpReceiver,
    ollama_up: bool,
) -> None:
    from sevn.domain.agents import AgentService

    metrics = importlib.import_module("sevn.observability.metrics")
    arm_observability(monkeypatch, tmp_path, otlp_section(otlp_receiver.url))
    load_modules("sevn.api.bots")
    with FakeOllama("{}") as ollama:
        url = ollama.url if ollama_up else f"http://127.0.0.1:{dead_port()}"
        monkeypatch.setenv("SEVN_OLLAMA_URL", url)
        async with connected(tmp_path, monkeypatch) as (_host, client):
            frame, _earlier = await request(
                client, "bots.create", {"name": "Nimbus", "op_id": mint_id("op_")}
            )
            bot = ok(frame)
            agent = await AgentService().spawn(bot_id=str(bot["id"]))
            for index in range(2):
                await insert_job(
                    tmp_path, bot_id=str(bot["id"]), agent_id=agent.id, text=f"wait {index}"
                )
            handle = start_observability()
            try:
                await metrics.sample()
            finally:
                handle.shutdown()
    points = otlp_receiver.metrics()
    names = {point.name for point in points}
    assert set(_GAUGES) <= names, sorted(names)
    queued = [point for point in points if point.name == "sevn.jobs.queued"]
    mine = [point for point in queued if point.attributes.get("sevn.bot_id") == bot["id"]]
    assert mine, queued
    assert mine[-1].value == 2
    assert all(set(point.attributes) == {"sevn.bot_id"} for point in queued)
    for name, expected in (
        ("sevn.turns.running", 0),
        ("sevn.agents.open", 1),
        ("sevn.ollama.reachable", 1 if ollama_up else 0),
    ):
        latest = [point for point in points if point.name == name]
        assert latest[-1].value == expected, (name, latest)
        assert "sevn.bot_id" not in latest[-1].attributes
