"""Tests for branded ASCII logo conversion and animation frames."""

from __future__ import annotations

import io
import os
from unittest.mock import patch

from sevn.branding.logo_mark import (
    LogoCell,
    build_marquee_frames,
    build_reveal_frames,
    hex_to_rgb,
    load_bundled_logo_png,
    play_frames,
    render_ansi,
    rgb_to_hex,
    trim_grid,
)
from sevn.branding.splash import logo_splash_enabled, maybe_play_logo_splash


def test_brand_hex_roundtrip() -> None:
    assert rgb_to_hex(*hex_to_rgb("#5fb1f7")) == "#5fb1f7"


def test_trim_grid_crops_margins() -> None:
    blank = LogoCell(" ", 0, 0, 0)
    ink = LogoCell("x", 255, 59, 59)
    cols, rows, cells = trim_grid(2, 2, [blank, blank, blank, ink])
    assert (cols, rows) == (1, 1)
    assert cells == [ink]


def test_row_reveal_frame_count() -> None:
    cells = [
        LogoCell("a", 1, 2, 3),
        LogoCell("b", 4, 5, 6),
        LogoCell("c", 7, 8, 9),
        LogoCell("d", 1, 1, 1),
    ]
    frames = build_reveal_frames(2, 2, cells, background=(0, 0, 0), transition="none")
    assert len(frames) == 2
    assert frames[0][0].ch == "a"
    assert frames[0][3].ch == " "
    assert frames[1][3].ch == "d"


def test_dissolve_adds_subframes() -> None:
    cells = [LogoCell("x", 1, 2, 3), LogoCell(" ", 0, 0, 0)]
    none_frames = build_reveal_frames(2, 1, cells, background=(0, 0, 0), transition="none")
    dissolve_frames = build_reveal_frames(2, 1, cells, background=(0, 0, 0), transition="dissolve")
    assert len(dissolve_frames) > len(none_frames)


def test_marquee_slides_left_to_right() -> None:
    ink = LogoCell("x", 255, 59, 59)
    frames = build_marquee_frames(1, 1, [ink], background=(0, 0, 0), track_cols=4, step=1)
    first_x = [next(i for i, c in enumerate(f) if c.ch == "x") for f in frames if ink in f]
    assert first_x == sorted(first_x)
    assert frames[0].count(ink) == 0
    assert any(f.count(ink) == 1 for f in frames)
    assert all(cell.ch == " " for cell in frames[-1])


def test_render_ansi_preserves_blank_rows_for_tty_clearing() -> None:
    """Animation frames must emit full-width blank rows to overwrite prior ink."""
    blank = LogoCell(" ", 24, 24, 24)
    text = render_ansi(4, 2, [blank] * 8, color=False, trim_trailing_blank_lines=False)
    assert len(text.splitlines()) == 2
    assert all(len(line) == 4 for line in text.splitlines())


def test_render_ansi_forces_color() -> None:
    text = render_ansi(1, 1, [LogoCell("x", 255, 59, 59)], color=True)
    assert "\033[38;2;255;59;59m" in text


def test_bundled_logo_png_exists() -> None:
    path = load_bundled_logo_png()
    assert path.is_file()


def test_play_frames_restore_newline_clears_splash() -> None:
    buf = io.StringIO()
    blank = LogoCell(" ", 0, 0, 0)
    play_frames(
        2,
        2,
        [[blank, blank, blank, blank]],
        fps=1000.0,
        stream=buf,
        color=False,
        hold_final_s=0,
        restore_newline=True,
    )
    assert "\033[2K\r\n" in buf.getvalue()
    assert buf.getvalue().endswith("\033[2K\r\n\033[?25h")


def test_play_frames_writes_to_stream() -> None:
    buf = io.StringIO()
    play_frames(
        1,
        1,
        [[LogoCell("x", 255, 59, 59)]],
        fps=24.0,
        stream=buf,
        color=True,
        hold_final_s=0,
    )
    assert "x" in buf.getvalue()


def test_logo_splash_disabled_with_env() -> None:
    with patch.dict(os.environ, {"SEVN_NO_LOGO_SPLASH": "1"}, clear=False):
        assert logo_splash_enabled() is False


def test_maybe_play_logo_splash_skips_when_disabled() -> None:
    with (
        patch("sevn.branding.splash.logo_splash_enabled", return_value=False),
        patch("sevn.branding.splash.play_unicorn_trot") as play,
    ):
        maybe_play_logo_splash()
        play.assert_not_called()
