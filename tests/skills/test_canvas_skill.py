"""Bundled ``canvas`` skill script subprocess tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

_CANVAS_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "canvas"
)
_SCRIPTS = _CANVAS_ROOT / "scripts"


def _run_script(script_name: str, cli_args: list[str]) -> dict[str, object]:
    script = _SCRIPTS / script_name
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = env.get("SEVN_WORKSPACE", str(Path.cwd()))
    proc = subprocess.run(
        [sys.executable, str(script), *cli_args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = cast("dict[str, object]", json.loads(proc.stdout.strip()))
    assert payload.get("ok") is True
    return payload


def test_compose_table_smoke() -> None:
    """Table compose returns html, fallback_text, and openui_render hint."""
    payload = _run_script(
        "compose_table.py",
        [
            "--title",
            "Revenue",
            "--columns",
            '["Metric", "Value"]',
            "--rows",
            '[["Revenue", "42"], ["Cost", "10"]]',
        ],
    )
    data = payload["data"]
    assert isinstance(data, dict)
    html = data.get("html")
    assert isinstance(html, str)
    assert "Revenue" in html
    assert "<table" in html
    fallback = data.get("fallback_text")
    assert isinstance(fallback, str)
    assert "Metric" in fallback
    hint = data.get("openui_render")
    assert isinstance(hint, dict)
    assert hint.get("tool") == "openui_render"


def test_compose_cards_smoke() -> None:
    """Card grid compose returns structured openui_render arguments."""
    payload = _run_script(
        "compose_cards.py",
        [
            "--title",
            "Summary",
            "--cards",
            '[{"title": "North", "body": "Up 5%"}, {"title": "South", "body": "Flat"}]',
        ],
    )
    data = payload["data"]
    assert isinstance(data, dict)
    html = data.get("html")
    assert isinstance(html, str)
    assert "North" in html
    assert "Flat" in html
    hint = data.get("openui_render")
    assert isinstance(hint, dict)
    arguments = hint.get("arguments")
    assert isinstance(arguments, dict)
    assert arguments.get("fallback_text")


def test_compose_openui_payload_smoke(tmp_path: Path) -> None:
    """Inline HTML wrapper emits openui_render tool hint."""
    html_file = tmp_path / "panel.html"
    html_file.write_text("<p>Panel body</p>", encoding="utf-8")
    payload = _run_script(
        "compose_openui_payload.py",
        [
            "--html-file",
            str(html_file),
            "--fallback-text",
            "Panel body",
            "--title",
            "Panel",
        ],
    )
    data = payload["data"]
    assert isinstance(data, dict)
    assert data.get("html") == "<p>Panel body</p>"
    hint = data.get("openui_render")
    assert isinstance(hint, dict)
    arguments = hint.get("arguments")
    assert isinstance(arguments, dict)
    assert arguments.get("title") == "Panel"
