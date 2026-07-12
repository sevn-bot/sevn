"""Hand-authored trotting-unicorn splash for interactive CLI entry points.

Module: sevn.branding.unicorn_trot
Depends: os, shutil, sys, time, typing

Renders a side-profile pixel unicorn — all blue with a red horn and red mane —
that trots left-to-right across the terminal on a two-frame leg cycle, then
clears itself and returns the cursor to a fresh line. Uses Unicode half-block
glyphs (``▀``/``▄``/``█``) so two vertical pixels share one character cell,
keeping the sprite's proportions correct in a monospace terminal.

Exports:
    build_trot_frames — sliding leg-cycle frames across a track.
    compose_trot_track — place the sprite at an offset on a blank track row grid.
    play_unicorn_trot — animate the trotting unicorn on a TTY stream.
    render_halfblock — render a pixel-code grid with half-block glyphs.
    sprite_rows — sprite pixel-code rows for one leg frame.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from typing import TextIO

_BODY: tuple[str, ...] = (
    "....................RR....",
    "...................RR.....",
    "..................RR......",
    ".............RRRRBBBB.....",
    "............RRRRBBBBBB....",
    "...........RRRRBBBBWBB....",
    "..........RRRRBBBBBBBB....",
    ".........RRRRBBBBBBBB.....",
    "........RRRRBBBBBBB.......",
    ".......RRRRBBBBBBBB.......",
    "......RRRRBBBBBBBBBB......",
    ".RR..RRRBBBBBBBBBBBBBB....",
    "RRR.BBBBBBBBBBBBBBBBBBB...",
    ".RR.BBBBBBBBBBBBBBBBBBBB..",
    "..R.BBBBBBBBBBBBBBBBBBBB..",
    "....BBBBBBBBBBBBBBBBBBB...",
)
_LEGS: tuple[tuple[str, ...], ...] = (
    (
        "....BB...BB....BB...BB....",
        "....BB...BB....BB...BB....",
        "....BB...BB....BB...BB....",
        "....bb...bb....bb...bb....",
    ),
    (
        "......BB.BB....BB.BB......",
        "......BB.BB....BB.BB......",
        "......BB.BB....BB.BB......",
        "......bb.bb....bb.bb......",
    ),
)

SPRITE_W = 26
SPRITE_H = len(_BODY) + len(_LEGS[0])

_PALETTE: dict[str, tuple[int, int, int]] = {
    "B": (95, 177, 247),
    "b": (42, 127, 198),
    "R": (255, 59, 59),
    "W": (255, 255, 255),
}


def sprite_rows(leg_frame: int) -> list[str]:
    """Return the sprite pixel-code rows for one leg frame.

    Args:
        leg_frame (int): ``0`` (legs spread) or ``1`` (legs gathered).

    Returns:
        list[str]: ``SPRITE_H`` rows, each ``SPRITE_W`` pixel codes wide.

    Examples:
        >>> len(sprite_rows(0)) == SPRITE_H
        True
        >>> len(sprite_rows(1)[0]) == SPRITE_W
        True
    """
    legs = _LEGS[leg_frame % len(_LEGS)]
    rows = [*_BODY, *legs]
    return [row.ljust(SPRITE_W, ".")[:SPRITE_W] for row in rows]


def _resolve_color(color: bool | None) -> bool:
    """Return whether ANSI color should be emitted.

    Args:
        color (bool | None): Explicit override, else follow TTY / NO_COLOR.

    Returns:
        bool: ``True`` when color escapes should be written.

    Examples:
        >>> _resolve_color(False)
        False
    """
    if color is not None:
        return color
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _cell(top_code: str, bottom_code: str, *, use_color: bool) -> str:
    """Render one character cell from its top and bottom pixel codes.

    Args:
        top_code (str): Upper-pixel color code.
        bottom_code (str): Lower-pixel color code.
        use_color (bool): Emit true-color escapes when ``True``.

    Returns:
        str: A half-block glyph, optionally wrapped in ANSI color.

    Examples:
        >>> _cell("R", "B", use_color=False)
        '█'
    """
    top = _PALETTE.get(top_code)
    bottom = _PALETTE.get(bottom_code)
    if not use_color:
        if top and bottom:
            return "\u2588"
        if top:
            return "\u2580"
        if bottom:
            return "\u2584"
        return " "
    if top and bottom:
        return f"\033[38;2;{top[0]};{top[1]};{top[2]}m\033[48;2;{bottom[0]};{bottom[1]};{bottom[2]}m\u2580"
    if top:
        return f"\033[38;2;{top[0]};{top[1]};{top[2]}m\033[49m\u2580"
    if bottom:
        return f"\033[38;2;{bottom[0]};{bottom[1]};{bottom[2]}m\033[49m\u2584"
    return "\033[39m\033[49m "


def render_halfblock(code_rows: list[str], *, color: bool | None = None) -> str:
    """Render a pixel-code grid using half-block glyphs (two pixels per cell).

    Args:
        code_rows (list[str]): Rows of single-character pixel codes.
        color (bool | None): Force color on/off; default follows TTY / NO_COLOR.

    Returns:
        str: Rendered text with ``ceil(len(code_rows) / 2)`` lines.

    Examples:
        >>> render_halfblock(["R", "B"], color=False).strip()
        '█'
        >>> "38;2;255;59;59" in render_halfblock(["R", "B"], color=True)
        True
    """
    use_color = _resolve_color(color)
    height = len(code_rows)
    width = max((len(row) for row in code_rows), default=0)
    lines: list[str] = []
    for top_index in range(0, height, 2):
        top = code_rows[top_index]
        bottom = code_rows[top_index + 1] if top_index + 1 < height else ""
        parts = [
            _cell(
                top[col] if col < len(top) else ".",
                bottom[col] if col < len(bottom) else ".",
                use_color=use_color,
            )
            for col in range(width)
        ]
        line = "".join(parts)
        if use_color:
            line += "\033[0m"
        lines.append(line)
    return "\n".join(lines) + "\n"


def compose_trot_track(leg_frame: int, offset: int, track_cols: int) -> list[str]:
    """Place the sprite at a horizontal offset on a blank ``track_cols`` grid.

    Args:
        leg_frame (int): Leg-cycle frame to draw.
        offset (int): Leftmost sprite column on the track.
        track_cols (int): Total track width in pixel columns.

    Returns:
        list[str]: ``SPRITE_H`` rows, each ``track_cols`` codes wide.

    Examples:
        >>> rows = compose_trot_track(0, 0, SPRITE_W)
        >>> len(rows) == SPRITE_H and len(rows[0]) == SPRITE_W
        True
    """
    rows: list[str] = []
    for row in sprite_rows(leg_frame):
        buf = ["."] * track_cols
        for pixel_x, code in enumerate(row):
            track_x = offset + pixel_x
            if code != "." and 0 <= track_x < track_cols:
                buf[track_x] = code
        rows.append("".join(buf))
    return rows


def build_trot_frames(track_cols: int, *, step: int = 2) -> list[list[str]]:
    """Build frames that slide the trotting sprite left-to-right across a track.

    The leg frame swaps every two frames for a two-beat trot, and a final blank
    frame clears the sprite off the track.

    Args:
        track_cols (int): Track width in pixel columns.
        step (int): Columns advanced per frame (higher is faster).

    Returns:
        list[list[str]]: Frame code-row grids, each ``SPRITE_H`` rows tall.

    Examples:
        >>> frames = build_trot_frames(30, step=4)
        >>> all(len(frame) == SPRITE_H for frame in frames)
        True
        >>> all(code == "." for row in frames[-1] for code in row)
        True
    """
    travel = max(1, step)
    frames: list[list[str]] = []
    offset = -SPRITE_W
    index = 0
    while offset <= track_cols:
        frames.append(compose_trot_track((index // 2) % 2, offset, track_cols))
        offset += travel
        index += 1
    frames.append(["." * track_cols for _ in range(SPRITE_H)])
    return frames


def play_unicorn_trot(
    *,
    fps: float = 18.0,
    step: int = 2,
    track_cols: int | None = None,
    stream: TextIO | None = None,
    color: bool | None = None,
) -> None:
    """Animate the trotting unicorn on a TTY, then clear it to a fresh line.

    Args:
        fps (float): Frames per second.
        step (int): Columns advanced per frame (higher is faster).
        track_cols (int | None): Travel width; defaults to terminal width - 1.
        stream (TextIO | None): Output stream; defaults to stdout.
        color (bool | None): ANSI color override.

    Examples:
        >>> play_unicorn_trot(track_cols=10, fps=1000, stream=open(os.devnull, "w", encoding="utf-8"))  # doctest: +SKIP
    """
    out = stream or sys.stdout
    track = track_cols or max(1, shutil.get_terminal_size(fallback=(80, 24)).columns - 1)
    frames = build_trot_frames(track, step=step)
    if not frames:
        return
    interval = 1.0 / max(fps, 0.1)
    char_rows = (SPRITE_H + 1) // 2
    out.write("\033[?25l")
    out.flush()
    try:
        for index, frame in enumerate(frames):
            out.write("\033[H")
            out.write(render_halfblock(frame, color=color))
            out.flush()
            if index < len(frames) - 1:
                time.sleep(interval)
    finally:
        out.write("\033[H")
        for _ in range(char_rows):
            out.write("\033[2K\r\n")
        out.write("\033[?25h")
        out.flush()


__all__ = [
    "SPRITE_H",
    "SPRITE_W",
    "build_trot_frames",
    "compose_trot_track",
    "play_unicorn_trot",
    "render_halfblock",
    "sprite_rows",
]
