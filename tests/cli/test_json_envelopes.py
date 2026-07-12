"""Tests for JSON envelopes (`specs/23-cli.md` §2.6)."""

from __future__ import annotations

import json
from io import StringIO

from sevn.cli.json_util import CLI_JSON_SCHEMA_VERSION, emit_json_failure, emit_json_success


def test_emit_json_success_shape() -> None:
    buf = StringIO()
    emit_json_success(command="sevn doctor", data={"x": 1}, stream=buf)
    obj = json.loads(buf.getvalue())
    assert obj["ok"] is True
    assert obj["command"] == "sevn doctor"
    assert obj["data"] == {"x": 1}
    assert obj["schema_version"] == CLI_JSON_SCHEMA_VERSION


def test_emit_json_failure_shape() -> None:
    buf = StringIO()
    emit_json_failure(
        command="sevn gateway status",
        error_code="NOT_IMPLEMENTED",
        message="stub",
        exit_code=4,
        details={"k": "v"},
        stream=buf,
    )
    obj = json.loads(buf.getvalue())
    assert obj["ok"] is False
    assert obj["error_code"] == "NOT_IMPLEMENTED"
    assert obj["exit_code"] == 4
    assert obj["details"] == {"k": "v"}
