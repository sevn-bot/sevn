"""Helpers for the ``sevn service`` RED suite (plan 0025 D1).

Product imports stay inside calls so collection succeeds before W2.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any


def invoke(args: Sequence[str]) -> Any:
    from sevn.cli import app
    from typer.testing import CliRunner

    return CliRunner().invoke(app, list(args))


def combined(result: Any) -> str:
    stderr = getattr(result, "stderr", "") or ""
    return f"{result.output}\n{stderr}"


def status_json(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, combined(result)
    body = json.loads(result.stdout.strip().splitlines()[-1])
    assert isinstance(body, dict), body
    return body


def unit_words(value: str) -> list[str]:
    """Split one systemd value the way systemd does: double quotes group, ``%%`` is ``%``."""
    words: list[str] = []
    current: list[str] = []
    quoted = False
    started = False
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and quoted and index + 1 < len(value):
            current.append(value[index + 1])
            index += 2
            continue
        if char == '"':
            quoted = not quoted
            started = True
        elif char.isspace() and not quoted:
            if started:
                words.append("".join(current))
                current = []
                started = False
        else:
            current.append(char)
            started = True
        index += 1
    if started:
        words.append("".join(current))
    return [word.replace("%%", "%") for word in words]


def parse_unit(text: str) -> dict[str, dict[str, list[str]]]:
    """``{section: {key: [raw values in order]}}`` for a systemd unit file."""
    sections: dict[str, dict[str, list[str]]] = {}
    current: dict[str, list[str]] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
            continue
        assert current is not None, f"key outside a section: {line!r}"
        key, _, value = line.partition("=")
        current.setdefault(key.strip(), []).append(value.strip())
    return sections


def unit_environment(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for value in parse_unit(text).get("Service", {}).get("Environment", []):
        for word in unit_words(value):
            key, _, item = word.partition("=")
            env[key] = item
    return env


def unit_exec_start(text: str) -> list[str]:
    values = parse_unit(text)["Service"]["ExecStart"]
    assert len(values) == 1, values
    return unit_words(values[0])
