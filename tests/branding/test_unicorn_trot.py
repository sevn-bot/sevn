"""Tests for the trotting-unicorn splash sprite and animation."""

from __future__ import annotations

import io

from sevn.branding.unicorn_trot import (
    SPRITE_H,
    SPRITE_W,
    build_trot_frames,
    play_unicorn_trot,
    render_halfblock,
    sprite_rows,
)


def test_sprite_rows_dimensions() -> None:
    rows = sprite_rows(0)
    assert len(rows) == SPRITE_H
    assert all(len(row) == SPRITE_W for row in rows)


def test_leg_frames_differ() -> None:
    assert sprite_rows(0) != sprite_rows(1)


def test_sprite_uses_red_horn_and_mane() -> None:
    rows = sprite_rows(0)
    assert any("R" in row for row in rows[:3]), "horn rows should be red"
    assert sum(row.count("R") for row in rows) > 6, "mane should add red pixels"


def test_render_halfblock_both_colors() -> None:
    text = render_halfblock(["R", "B"], color=True)
    assert "38;2;255;59;59" in text
    assert "48;2;95;177;247" in text


def test_render_halfblock_plain_glyph() -> None:
    assert render_halfblock(["R", "B"], color=False).strip() == "\u2588"
    assert render_halfblock(["R", "."], color=False).strip() == "\u2580"
    assert render_halfblock([".", "B"], color=False).strip() == "\u2584"


def test_trot_frames_slide_left_to_right() -> None:
    frames = build_trot_frames(40, step=3)

    def first_ink(frame: list[str]) -> int | None:
        for col in range(len(frame[0])):
            if any(row[col] != "." for row in frame):
                return col
        return None

    positions = [pos for frame in frames if (pos := first_ink(frame)) is not None]
    assert positions == sorted(positions)
    assert all(code == "." for row in frames[-1] for code in row)


def test_play_unicorn_trot_clears_to_newline() -> None:
    buf = io.StringIO()
    play_unicorn_trot(track_cols=12, fps=1000.0, stream=buf, color=False)
    out = buf.getvalue()
    assert out.startswith("\033[?25l")
    assert "\033[2K\r\n" in out
    assert out.endswith("\033[?25h")
