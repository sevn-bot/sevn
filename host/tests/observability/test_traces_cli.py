"""``sevn doctor`` observability fields and ``sevn traces test`` (plan 0015 D11; green after W5).

The file is not named ``test_cli.py``: ``host/tests/test_cli.py`` exists, and the
tests tree has no packages, so two modules with one basename cannot both import.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from support.canary import canary
from support.observability import (
    arm_observability,
    fake_logfire_token,
    otlp_section,
    store_secret,
)
from support.spans import OtlpReceiver, dead_port

pytestmark = [
    pytest.mark.usefixtures("otel_clean"),
]

_TRACE_ID = re.compile(r"\b[0-9a-f]{32}\b")


def _invoke(*args: str) -> Any:
    from sevn.cli import app
    from typer.testing import CliRunner

    return CliRunner().invoke(app, list(args))


def _doctor(*extra: str) -> dict[str, Any]:
    result = _invoke("doctor", "--json", *extra)
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert isinstance(body, dict)
    return body


@pytest.mark.parametrize(
    ("section", "token", "exporter", "content"),
    [
        ("", False, "none", "off"),
        ("", True, "logfire", "off"),
        ('exporter = "none"', True, "none", "off"),
        (otlp_section("http://127.0.0.1:4318"), False, "otlp:127.0.0.1", "off"),
        ('exporter = "otlp"\npreset = "datadog-agent"', False, "otlp:datadog-agent", "off"),
        (
            'exporter = "otlp"\npreset = "datadog-agentless"\ncapture_content = true',
            False,
            "otlp:datadog-agentless",
            "on",
        ),
    ],
)
def test_doctor_reports_exporter_and_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    token: bool,
    exporter: str,
    content: str,
) -> None:
    arm_observability(monkeypatch, tmp_path, section)
    if token:
        store_secret("logfire/token", fake_logfire_token())
    body = _doctor()
    assert body["observability_exporter"] == exporter
    assert body["observability_content"] == content
    assert "observability_check" not in body


def test_doctor_text_output_lists_the_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm_observability(monkeypatch, tmp_path, otlp_section("http://127.0.0.1:4318"))
    result = _invoke("doctor")
    assert result.exit_code == 0, result.output
    assert "observability_exporter: otlp:127.0.0.1" in result.stdout
    assert "observability_content: off" in result.stdout


@pytest.mark.parametrize("state", ["accepts", "unreachable", "off"])
def test_doctor_check_reports_whether_the_endpoint_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver, state: str
) -> None:
    if state == "accepts":
        arm_observability(monkeypatch, tmp_path, otlp_section(otlp_receiver.url))
    elif state == "unreachable":
        arm_observability(monkeypatch, tmp_path, otlp_section(f"http://127.0.0.1:{dead_port()}"))
    else:
        arm_observability(monkeypatch, tmp_path)
    body = _doctor("--check")
    check = str(body["observability_check"])
    if state == "accepts":
        assert check == "ok"
        assert otlp_receiver.signal_requests("traces")
    elif state == "unreachable":
        assert check.startswith("failed")
    else:
        assert check == "off"
        assert otlp_receiver.requests == []


def test_doctor_never_prints_a_header_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    arm_observability(
        monkeypatch,
        tmp_path,
        otlp_section(otlp_receiver.url, 'headers = { "x-api-key" = "secret://ops/otlp" }'),
    )
    with canary() as probe:
        store_secret("ops/otlp", probe.value)
        result = _invoke("doctor", "--json", "--check")
        assert result.exit_code == 0, result.output
        assert probe.value not in result.output
        assert json.loads(result.stdout)["observability_check"] == "ok"
        # The exporter still sent the real header value; only the output hides it.
        traces = otlp_receiver.signal_requests("traces")
        assert traces
        assert traces[0].headers.get("x-api-key") == probe.value


@pytest.mark.parametrize("exporter", ["otlp", "logfire"])
def test_traces_test_sends_redacted_canary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver, exporter: str
) -> None:
    if exporter == "otlp":
        arm_observability(monkeypatch, tmp_path, otlp_section(otlp_receiver.url))
    else:
        arm_observability(monkeypatch, tmp_path)
        store_secret("logfire/token", fake_logfire_token())
        monkeypatch.setenv("LOGFIRE_BASE_URL", otlp_receiver.url)
    result = _invoke("traces", "test")
    assert result.exit_code == 0, result.output
    found = _TRACE_ID.search(result.stdout)
    assert found is not None, result.stdout
    trace_id = found.group(0)
    otlp_receiver.wait_for(lambda seen: any(span.name == "sevn.test" for span in seen.spans()))
    spans = [span for span in otlp_receiver.spans() if span.name == "sevn.test"]
    assert len(spans) == 1
    assert spans[0].trace_id == trace_id
    assert str(spans[0].attributes["sevn.canary"]).startswith("«redacted:")
    assert "«redacted:" in otlp_receiver.all_bytes().decode("utf-8", errors="replace")


def test_traces_test_with_exporter_off_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, otlp_receiver: OtlpReceiver
) -> None:
    arm_observability(monkeypatch, tmp_path)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", otlp_receiver.url)
    result = _invoke("traces", "test")
    assert result.exit_code == 1, result.output
    assert "exporter" in result.output
    assert otlp_receiver.requests == []


def test_traces_test_reports_an_unreachable_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm_observability(monkeypatch, tmp_path, otlp_section(f"http://127.0.0.1:{dead_port()}"))
    result = _invoke("traces", "test")
    assert result.exit_code == 1, result.output
    assert "failed" in result.output.lower()
