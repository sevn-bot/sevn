"""Render gating matrix tests for Rich/plain fallback (W1)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from sevn.cli.render.console import configure_render, get_console, is_rich, plain_echo
from sevn.cli.render.sections import check_ok, section


@pytest.fixture(autouse=True)
def _reset_render_options() -> None:
    configure_render(json_mode=False, no_color=False, force_plain=False)
    yield
    configure_render(json_mode=False, no_color=False, force_plain=False)


def test_is_rich_false_when_json_mode() -> None:
    configure_render(json_mode=True)
    with patch("sys.stdout.isatty", return_value=True):
        assert is_rich() is False


def test_is_rich_false_when_no_color_env() -> None:
    configure_render(json_mode=False, no_color=False)
    with (
        patch("sys.stdout.isatty", return_value=True),
        patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False),
    ):
        assert is_rich() is False


def test_is_rich_false_when_sevn_no_color_env() -> None:
    configure_render(json_mode=False, no_color=False)
    with (
        patch("sys.stdout.isatty", return_value=True),
        patch.dict(os.environ, {"SEVN_NO_COLOR": "1"}, clear=False),
    ):
        assert is_rich() is False


def test_is_rich_false_when_not_tty() -> None:
    configure_render(json_mode=False, no_color=False)
    with patch("sys.stdout.isatty", return_value=False):
        assert is_rich() is False


def test_is_rich_true_on_tty_without_gates() -> None:
    configure_render(json_mode=False, no_color=False, force_plain=False)
    with patch("sys.stdout.isatty", return_value=True), patch.dict(os.environ, {}, clear=True):
        assert is_rich() is True
        console = get_console()
        assert console.no_color is False


def test_configure_render_no_color_flag() -> None:
    configure_render(no_color=True)
    with patch("sys.stdout.isatty", return_value=True):
        assert is_rich() is False


def test_plain_echo_writes_without_markup(capsys: pytest.CaptureFixture[str]) -> None:
    plain_echo("hello plain")
    captured = capsys.readouterr()
    assert captured.out.strip() == "hello plain"


def test_section_plain_when_not_rich(capsys: pytest.CaptureFixture[str]) -> None:
    configure_render(force_plain=True)
    section("Workspace")
    check_ok("sevn.json present")
    out = capsys.readouterr().out
    assert "◆ Workspace" in out
    assert "sevn.json present" in out
    assert "\x1b[" not in out


def test_render_table_plain_columns(capsys: pytest.CaptureFixture[str]) -> None:
    from sevn.cli.render.tables import render_table

    configure_render(force_plain=True)
    render_table(["id", "state"], [["gw", "up"]], title="services")
    out = capsys.readouterr().out
    assert "services" in out
    assert "gw" in out


def test_textual_loaders_raise_when_not_tty() -> None:
    from sevn.cli.tui import load_log_viewer_app, load_section_picker_app

    configure_render(force_plain=True)
    with pytest.raises(RuntimeError, match="interactive TTY"):
        load_section_picker_app()
    with pytest.raises(RuntimeError, match="interactive TTY"):
        load_log_viewer_app()
