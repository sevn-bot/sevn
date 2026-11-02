"""Live export to Logfire and Datadog (plan 0015 W1.7; K-GATE ``logfire``, ``datadog``).

Excluded by default (``-m "not live"``); ``make test LIVE=1`` runs them. Each test
skips cleanly when its credentials are absent. Credentials come from the
operator's environment only and are stored in a disposable age-file home:

- ``SEVN_LIVE_LOGFIRE_TOKEN``: a Logfire project write token (EU or US).
- ``SEVN_LIVE_LOGFIRE_READ_TOKEN``: optional read token; when set, the trace is
  queried back by trace id.
- ``SEVN_LIVE_DD_API_KEY``: a Datadog API key for agentless OTLP intake.
- ``SEVN_LIVE_DD_SITE`` (or ``DD_SITE``): the Datadog site, default ``datadoghq.com``.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import pytest
from support.observability import arm_observability, store_secret

pytestmark = [
    pytest.mark.live,
    pytest.mark.usefixtures("otel_clean"),
    pytest.mark.xfail(reason="green after W5: live export through sevn traces test", strict=False),
]

_TRACE_ID = re.compile(r"\b[0-9a-f]{32}\b")
_READ_BACK_S = 120


def _invoke(*args: str) -> Any:
    from sevn.cli import app
    from typer.testing import CliRunner

    return CliRunner().invoke(app, list(args))


def _sent_trace_id() -> str:
    result = _invoke("traces", "test")
    assert result.exit_code == 0, result.output
    found = _TRACE_ID.search(result.stdout)
    assert found is not None, result.stdout
    return found.group(0)


def _logfire_rows(read_token: str, trace_id: str) -> list[dict[str, Any]]:
    from logfire.query_client import LogfireQueryClient

    assert _TRACE_ID.fullmatch(trace_id)
    sql = (
        "SELECT span_name, attributes->>'sevn.canary' AS canary "  # noqa: S608 — trace_id is hex
        f"FROM records WHERE trace_id = '{trace_id}'"
    )
    deadline = time.monotonic() + _READ_BACK_S
    with LogfireQueryClient(read_token=read_token) as client:
        while time.monotonic() < deadline:
            body = client.query_json_rows(sql=sql)
            rows = body.get("rows", []) if isinstance(body, dict) else []
            if rows:
                return [dict(row) for row in rows]
            time.sleep(5)
    return []


def test_live_logfire_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token = os.environ.get("SEVN_LIVE_LOGFIRE_TOKEN", "")
    read_token = os.environ.get("SEVN_LIVE_LOGFIRE_READ_TOKEN", "")
    if token == "":
        pytest.skip("skipped: no live gate (SEVN_LIVE_LOGFIRE_TOKEN is not set)")
    arm_observability(monkeypatch, tmp_path)
    store_secret("logfire/token", token)
    trace_id = _sent_trace_id()
    if read_token == "":
        pytest.skip(f"exported trace {trace_id}; no SEVN_LIVE_LOGFIRE_READ_TOKEN to read it back")
    rows = _logfire_rows(read_token, trace_id)
    assert rows, f"trace {trace_id} not queryable after {_READ_BACK_S}s"
    names = [row.get("span_name") for row in rows]
    assert "sevn.test" in names
    canary_values = [str(row.get("canary") or "") for row in rows if row.get("canary")]
    assert canary_values
    assert all(value.startswith("«redacted:") for value in canary_values)


def test_live_datadog_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api_key = os.environ.get("SEVN_LIVE_DD_API_KEY", "")
    site = os.environ.get("SEVN_LIVE_DD_SITE", "") or os.environ.get("DD_SITE", "")
    if api_key == "":
        pytest.skip("skipped: no live gate (SEVN_LIVE_DD_API_KEY is not set)")
    arm_observability(
        monkeypatch,
        tmp_path,
        'exporter = "otlp"\npreset = "datadog-agentless"\n'
        f'datadog_site = "{site or "datadoghq.com"}"',
    )
    store_secret("datadog/api_key", api_key)
    result = _invoke("doctor", "--json", "--check")
    assert result.exit_code == 0, result.output
    assert api_key not in result.output
    assert json.loads(result.stdout)["observability_check"] == "ok"
    trace_id = _sent_trace_id()
    # APM and LLM Observability are checked in the UI by the WV gate with this id.
    assert _TRACE_ID.fullmatch(trace_id)
