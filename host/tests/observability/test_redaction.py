"""Span redaction and content capture (plan 0015 D7; green after W2).

K-CANARY: a registered secret placed in span attributes, events, an exception
and the status description is absent from every byte the loopback receiver saw,
on both the OTLP path and the Logfire path.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import string
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from support.canary import canary
from support.chat import arm_home
from support.observability import (
    arm_observability,
    fake_logfire_token,
    otlp_section,
    start_observability,
    store_secret,
)
from support.spans import OtlpReceiver

pytestmark = pytest.mark.usefixtures("otel_clean")

_ALNUM = string.ascii_letters + string.digits


def _chunk(size: int, symbols: str = _ALNUM) -> str:
    return "".join(secrets.choice(symbols) for _ in range(size))


def _b64(payload: dict[str, str]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _key(kind: str) -> str:
    """A generated value in one D7 key shape. None of these is a real credential."""
    if kind == "openai":
        return "sk-" + _chunk(24)
    if kind == "anthropic":
        return "sk-ant-api03-" + _chunk(24)
    if kind in {"slack_bot", "slack_app", "slack_user"}:
        letter = {"slack_bot": "b", "slack_app": "a", "slack_user": "p"}[kind]
        return f"xox{letter}-" + _chunk(12, string.digits) + "-" + _chunk(16)
    if kind == "github":
        return "ghp_" + _chunk(36)
    if kind == "aws":
        return "AKIA" + _chunk(16, string.ascii_uppercase + string.digits)
    if kind == "jwt":
        header = _b64({"alg": "HS256", "typ": "JWT"})
        body = _b64({"sub": secrets.token_hex(8)})
        return f"{header}.{body}." + base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode().rstrip("=")
    if kind == "bearer":
        return "Bearer " + secrets.token_urlsafe(24)
    raise AssertionError(kind)


def _register() -> tuple[str, str]:
    from sevn.secrets.registry import register

    name = "test/" + secrets.token_hex(6)
    value = secrets.token_urlsafe(32)
    register(name, value)
    return name, value


class _Recording:
    """A SpanExporter that records what the redacting wrapper hands it."""

    def __init__(self, result: Any = None) -> None:
        from opentelemetry.sdk.trace.export import SpanExportResult

        self.result = SpanExportResult.SUCCESS if result is None else result
        self.batches: list[list[Any]] = []
        self.shutdowns = 0
        self.flushes = 0

    def export(self, spans: Sequence[Any]) -> Any:
        self.batches.append(list(spans))
        return self.result

    def shutdown(self) -> None:
        self.shutdowns += 1

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        _ = timeout_millis
        self.flushes += 1
        return True


def _local_provider(exporter: Any) -> Any:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider


# --- scrub ------------------------------------------------------------------------


def test_scrub_replaces_registered_secret() -> None:
    from sevn.observability.redact import scrub

    name, value = _register()
    assert scrub(f"before {value} after") == f"before «redacted:{name}» after"


def test_scrub_replaces_every_occurrence_longest_first() -> None:
    from sevn.observability.redact import scrub
    from sevn.secrets.registry import register

    short_name, short = _register()
    long_name = "test/" + secrets.token_hex(6)
    long_value = short + secrets.token_urlsafe(8)
    register(long_name, long_value)
    out = scrub(f"{long_value} {short} {short}")
    assert out == f"«redacted:{long_name}» «redacted:{short_name}» «redacted:{short_name}»"


@pytest.mark.parametrize(
    "kind",
    [
        "openai",
        "anthropic",
        "slack_bot",
        "slack_app",
        "slack_user",
        "github",
        "aws",
        "jwt",
        "bearer",
    ],
)
def test_key_patterns_masked(kind: str) -> None:
    from sevn.observability.redact import scrub

    value = _key(kind)
    out = scrub(f"token: {value} end")
    secret_part = value.split(" ", 1)[1] if kind == "bearer" else value
    assert secret_part not in out
    assert "«redacted" in out
    assert out.startswith("token: ")
    assert out.endswith(" end")


def test_scrub_leaves_clean_text_and_non_strings() -> None:
    from sevn.observability.redact import scrub

    assert scrub("plain words, nothing secret") == "plain words, nothing secret"
    assert scrub("") == ""
    assert scrub(42) == 42
    assert scrub(1.5) == 1.5
    assert scrub(True) is True


def test_scrub_sequences_keep_their_type() -> None:
    from sevn.observability.redact import scrub

    name, value = _register()
    assert scrub([value, "kept"]) == [f"«redacted:{name}»", "kept"]
    assert scrub((value, "kept")) == (f"«redacted:{name}»", "kept")
    assert scrub([1, 2]) == [1, 2]


# --- RedactingExporter --------------------------------------------------------------


def test_redacting_exporter_scrubs_attributes_events_and_status() -> None:
    from opentelemetry.trace import Status, StatusCode
    from sevn.observability.redact import RedactingExporter

    name, value = _register()
    marker = f"«redacted:{name}»"
    inner = _Recording()
    provider = _local_provider(RedactingExporter(inner))
    tracer = provider.get_tracer("sevn.tests")
    with tracer.start_as_current_span(
        "probe",
        attributes={"note": f"x {value}", "count": 3, "flag": True, "seq": (value, "ok")},
    ) as span:
        original = span.get_span_context()
        span.add_event("tool.result", {"detail": value, "size": 7})
        span.set_status(Status(StatusCode.ERROR, f"bad {value}"))
    provider.shutdown()

    assert len(inner.batches) == 1
    exported = inner.batches[0][0]
    attributes = dict(exported.attributes)
    assert exported.name == "probe"
    assert exported.context.trace_id == original.trace_id
    assert exported.context.span_id == original.span_id
    assert attributes["note"] == f"x {marker}"
    assert attributes["count"] == 3
    assert attributes["flag"] is True
    assert list(attributes["seq"]) == [marker, "ok"]
    event = exported.events[0]
    assert event.name == "tool.result"
    assert dict(event.attributes)["detail"] == marker
    assert dict(event.attributes)["size"] == 7
    assert exported.status.status_code == StatusCode.ERROR
    assert exported.status.description == f"bad {marker}"
    assert value not in repr(exported.to_json())


def test_redacting_exporter_scrubs_key_patterns() -> None:
    from sevn.observability.redact import RedactingExporter

    value = _key("anthropic")
    inner = _Recording()
    provider = _local_provider(RedactingExporter(inner))
    with provider.get_tracer("sevn.tests").start_as_current_span(
        "probe", attributes={"header": f"x-api-key: {value}"}
    ):
        pass
    provider.shutdown()
    exported = inner.batches[0][0]
    assert value not in str(dict(exported.attributes))


def test_redacting_exporter_delegates_result_flush_and_shutdown() -> None:
    from opentelemetry.sdk.trace.export import SpanExportResult
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from sevn.observability.redact import RedactingExporter

    memory = InMemorySpanExporter()
    provider = _local_provider(memory)
    with provider.get_tracer("sevn.tests").start_as_current_span("probe"):
        pass
    spans = memory.get_finished_spans()
    provider.shutdown()

    failing = _Recording(SpanExportResult.FAILURE)
    wrapper = RedactingExporter(failing)
    assert wrapper.export(spans) == SpanExportResult.FAILURE
    assert wrapper.force_flush() is True
    wrapper.shutdown()
    assert failing.flushes == 1
    assert failing.shutdowns == 1
    assert wrapper.inner is failing


# --- K-CANARY end to end ----------------------------------------------------------------


@pytest.mark.parametrize("exporter", ["otlp", "logfire"])
def test_registered_secret_scrubbed_from_attributes_events_and_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    otlp_receiver: OtlpReceiver,
    exporter: str,
) -> None:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    if exporter == "otlp":
        arm_observability(monkeypatch, tmp_path, otlp_section(otlp_receiver.url))
    else:
        arm_observability(monkeypatch, tmp_path)
        monkeypatch.setenv("LOGFIRE_BASE_URL", otlp_receiver.url)
    with canary() as probe:
        if exporter == "logfire":
            store_secret("logfire/token", fake_logfire_token())
        handle = start_observability()
        try:
            assert handle.exporter == exporter
            tracer = trace.get_tracer("sevn.tests")
            with tracer.start_as_current_span(
                "probe",
                attributes={"sevn.note": f"key={probe.value}", "sevn.list": [probe.value, "kept"]},
            ) as span:
                span.add_event("tool.result", {"detail": f"saw {probe.value}"})
                span.record_exception(RuntimeError(f"boom {probe.value}"))
                span.set_status(Status(StatusCode.ERROR, f"failed with {probe.value}"))
        finally:
            handle.shutdown()
        otlp_receiver.wait_for(lambda seen: any(item.name == "probe" for item in seen.spans()))
        exported = next(item for item in otlp_receiver.spans() if item.name == "probe")
        marker = f"«redacted:{probe.name}»"
        assert marker in str(exported.attributes.get("sevn.note"))
        events = dict(exported.events)
        assert marker in str(events["tool.result"].get("detail"))
        assert probe.value.encode() not in otlp_receiver.all_bytes()
        probe.assert_absent(probe.value)


def test_logfire_scrubbing_callback_uses_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from logfire import ScrubMatch
    from sevn.observability.redact import logfire_callback

    arm_home(monkeypatch, tmp_path)
    with canary() as probe:
        value = f"token is {probe.value}"
        found = re.search(re.escape(probe.value), value)
        assert found is not None
        match = ScrubMatch(path=("attributes", "sevn.note"), value=value, pattern_match=found)
        out = logfire_callback(match)
        assert out is not None
        assert probe.value not in str(out)
        assert f"«redacted:{probe.name}»" in str(out)


def test_logfire_scrubbing_callback_masks_key_patterns() -> None:
    from logfire import ScrubMatch
    from sevn.observability.redact import logfire_callback

    value = _key("github")
    text = f"pushed with {value}"
    found = re.search(re.escape(value), text)
    assert found is not None
    out = logfire_callback(ScrubMatch(path=("attributes", "note"), value=text, pattern_match=found))
    assert out is not None
    assert value not in str(out)


# --- content capture ------------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("text", ["plan the Lisbon trip ✈", "", "a" * 10_000])
def test_content_off_records_size_and_hash_only(text: str) -> None:
    from sevn.observability.redact import content_attributes

    attributes = content_attributes(text, capture=False)
    assert attributes == {
        "sevn.content.size": len(text.encode("utf-8")),
        "sevn.content.sha256": _sha(text),
    }


def test_content_off_hashes_the_scrubbed_text() -> None:
    from sevn.observability.redact import content_attributes

    name, value = _register()
    raw = f"use {value} now"
    scrubbed = f"use «redacted:{name}» now"
    attributes = content_attributes(raw, capture=False)
    assert attributes["sevn.content.sha256"] == _sha(scrubbed)
    assert attributes["sevn.content.sha256"] != _sha(raw)
    assert value not in str(attributes)
    assert "sevn.content.text" not in attributes


def test_content_on_records_text_still_scrubbed() -> None:
    from sevn.observability.redact import content_attributes

    name, value = _register()
    scrubbed = f"use «redacted:{name}» now"
    attributes = content_attributes(f"use {value} now", capture=True)
    assert attributes["sevn.content.text"] == scrubbed
    assert attributes["sevn.content.size"] == len(scrubbed.encode("utf-8"))
    assert attributes["sevn.content.sha256"] == _sha(scrubbed)
    assert value not in str(attributes)
