"""Live export to Logfire and Datadog (plan 0015 W1.7; K-GATE ``logfire``, ``datadog``).

Excluded by default (``-m "not live"``); ``make test LIVE=1`` runs them. Each test
skips cleanly when its credentials are absent. Credentials come from the
operator's environment only and are stored in a disposable age-file home:

- ``SEVN_LIVE_LOGFIRE_TOKEN``: a Logfire project write token (EU or US).
- ``SEVN_LIVE_LOGFIRE_READ_TOKEN``: optional read token; when set, the trace is
  queried back by trace id.
- ``SEVN_LIVE_DD_API_KEY``: a Datadog API key for agentless OTLP intake.
- ``SEVN_LIVE_DD_SITE`` (or ``DD_SITE``): the Datadog site, default ``datadoghq.com``.

Credential values never reach a pytest report: the helpers read them from the env
themselves (no argument or local holds one), hide their frames, re-raise failures
without the original exception, and every CLI output is scrubbed before it is
used in an assertion message.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from support.observability import arm_observability, store_secret
from support.spans import reset_otel_globals

pytestmark = [
    pytest.mark.live,
    pytest.mark.usefixtures("otel_clean"),
]

_TRACE_ID = re.compile(r"\b[0-9a-f]{32}\b")
_READ_BACK_S = 120
_LOGFIRE_WRITE_ENV = "SEVN_LIVE_LOGFIRE_TOKEN"
_LOGFIRE_READ_ENV = "SEVN_LIVE_LOGFIRE_READ_TOKEN"
_DD_KEY_ENV = "SEVN_LIVE_DD_API_KEY"
_CREDENTIAL_ENV = (_LOGFIRE_WRITE_ENV, _LOGFIRE_READ_ENV, _DD_KEY_ENV)


def _has(env_name: str) -> bool:
    return os.environ.get(env_name, "") != ""


def _scrubbed(text: str) -> str:
    """``text`` with every live credential value replaced, safe for an assertion message."""
    __tracebackhide__ = True
    for env_name in _CREDENTIAL_ENV:
        if _has(env_name):
            text = text.replace(os.environ[env_name], f"«{env_name}»")
    return text


def _leaks_credential(text: str) -> bool:
    __tracebackhide__ = True
    return any(_has(env_name) and os.environ[env_name] in text for env_name in _CREDENTIAL_ENV)


def _store_from_env(env_name: str, secret_name: str) -> None:
    """Store the value of ``env_name`` as ``secret_name``; a failure never carries the value."""
    __tracebackhide__ = True
    try:
        store_secret(secret_name, os.environ[env_name])
    except Exception as exc:  # noqa: BLE001 — re-raised without the frames that hold the value
        raise RuntimeError(f"storing {secret_name} failed ({type(exc).__name__})") from None


def _invoke(*args: str) -> Any:
    from sevn.cli import app
    from typer.testing import CliRunner

    return CliRunner().invoke(app, list(args))


def _sent_trace_id() -> str:
    result = _invoke("traces", "test")
    output = _scrubbed(result.output)
    assert result.exit_code == 0, output
    assert not _leaks_credential(result.output), "a live credential appeared in traces test"
    found = _TRACE_ID.search(result.stdout)
    assert found is not None, output
    return found.group(0)


def _logfire_rows(trace_id: str, since: datetime) -> list[dict[str, Any]]:
    """Rows of ``trace_id`` read back with the read token from the env (never an argument)."""
    __tracebackhide__ = True
    from logfire.query_client import LogfireQueryClient

    assert _TRACE_ID.fullmatch(trace_id)
    sql = (
        "SELECT span_name, attributes->>'sevn.canary' AS canary "  # noqa: S608 — hex-checked above; no bind params
        f"FROM records WHERE trace_id = '{trace_id}'"
    )
    deadline = time.monotonic() + _READ_BACK_S
    try:
        with LogfireQueryClient(read_token=os.environ[_LOGFIRE_READ_ENV]) as client:
            while time.monotonic() < deadline:
                body = client.query_json_rows(sql=sql, min_timestamp=since)
                rows = body.get("rows", []) if isinstance(body, dict) else []
                if rows:
                    return [dict(row) for row in rows]
                time.sleep(5)
    except Exception as exc:  # noqa: BLE001 — re-raised without the frames that hold the token
        raise RuntimeError(
            f"Logfire query for trace {trace_id} failed ({type(exc).__name__}: "
            f"{_scrubbed(str(exc))})"
        ) from None
    return []


def test_live_logfire_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not _has(_LOGFIRE_WRITE_ENV):
        pytest.skip(f"skipped: no live gate ({_LOGFIRE_WRITE_ENV} is not set)")
    arm_observability(monkeypatch, tmp_path)
    _store_from_env(_LOGFIRE_WRITE_ENV, "logfire/token")
    since = datetime.now(UTC) - timedelta(minutes=5)
    trace_id = _sent_trace_id()
    if not _has(_LOGFIRE_READ_ENV):
        pytest.skip(f"exported trace {trace_id}; no {_LOGFIRE_READ_ENV} to read it back")
    rows = _logfire_rows(trace_id, since)
    assert rows, f"trace {trace_id} not queryable after {_READ_BACK_S}s"
    names = [row.get("span_name") for row in rows]
    assert "sevn.test" in names
    canary_values = [str(row.get("canary") or "") for row in rows if row.get("canary")]
    assert canary_values
    assert all(value.startswith("«redacted:") for value in canary_values)


def test_live_datadog_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    site = os.environ.get("SEVN_LIVE_DD_SITE", "") or os.environ.get("DD_SITE", "")
    if not _has(_DD_KEY_ENV):
        pytest.skip(f"skipped: no live gate ({_DD_KEY_ENV} is not set)")
    arm_observability(
        monkeypatch,
        tmp_path,
        'exporter = "otlp"\npreset = "datadog-agentless"\n'
        f'datadog_site = "{site or "datadoghq.com"}"',
    )
    _store_from_env(_DD_KEY_ENV, "datadog/api_key")
    result = _invoke("doctor", "--json", "--check")
    output = _scrubbed(result.output)
    assert result.exit_code == 0, output
    assert not _leaks_credential(result.output), "the Datadog API key appeared in doctor output"
    check = json.loads(result.stdout)["observability_check"]
    assert check == "ok", output
    # Each CLI command is its own process in real use, so each one may install the
    # global providers. Two in one test process need the set-once guards reset.
    reset_otel_globals()
    trace_id = _sent_trace_id()
    # APM and LLM Observability are checked in the UI by the WV gate with this id.
    assert _TRACE_ID.fullmatch(trace_id)
