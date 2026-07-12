"""Stdout JSON envelopes for ``--json`` (`specs/23-cli.md` §2.6).

Module: sevn.cli.json_util
Depends: json, typing, typer

Exports:
    emit_json_success — ``ok: true`` envelope on stdout.
    emit_json_failure — ``ok: false`` envelope on stdout.

Private:
    CLI_JSON_SCHEMA_VERSION — semver for envelope field names.
"""

from __future__ import annotations

import json
from typing import Any, TextIO

import typer

CLI_JSON_SCHEMA_VERSION: str = "1.0.0"


def emit_json_success(
    *,
    command: str,
    data: dict[str, Any],
    stream: TextIO | None = None,
) -> None:
    """Print one JSON object: ``ok``, ``command``, ``data``, ``schema_version``.

    Args:
        command (str): Invoked command label for parsers.
        data (dict[str, Any]): Success payload.
        stream (TextIO | None): When set, write here (tests); else ``typer.echo`` to Click stdout.

    Examples:
        >>> from io import StringIO
        >>> buf = StringIO()
        >>> emit_json_success(command="t", data={}, stream=buf)
        >>> "ok" in buf.getvalue()
        True
    """
    payload = {
        "ok": True,
        "command": command,
        "data": data,
        "schema_version": CLI_JSON_SCHEMA_VERSION,
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if stream is not None:
        stream.write(text)
        stream.flush()
    else:
        typer.echo(text, nl=False)


def emit_json_failure(
    *,
    command: str,
    error_code: str,
    message: str,
    exit_code: int,
    details: dict[str, Any] | None = None,
    stream: TextIO | None = None,
) -> None:
    """Print failure envelope; parsers read stdout only.

    Args:
        command (str): Invoked command label.
        error_code (str): Stable machine-readable code.
        message (str): Human-readable summary.
        exit_code (int): Process exit code hint for parsers.
        details (dict[str, Any] | None): Optional structured detail.
        stream (TextIO | None): When set, write here (tests); else ``typer.echo``.

    Examples:
        >>> from io import StringIO
        >>> buf = StringIO()
        >>> emit_json_failure(command="t", error_code="E", message="m", exit_code=4, stream=buf)
        >>> "ok" in buf.getvalue()
        True
    """
    payload: dict[str, Any] = {
        "ok": False,
        "error_code": error_code,
        "message": message,
        "exit_code": exit_code,
        "command": command,
    }
    if details:
        payload["details"] = details
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if stream is not None:
        stream.write(text)
        stream.flush()
    else:
        typer.echo(text, nl=False)
