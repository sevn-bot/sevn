"""ASCII logo conversion and row-reveal terminal animation.

Module: sevn.branding.logo_mark
Depends: importlib.resources, pathlib, PIL, time, typing

Exports:
    LogoCell — one grid cell (character + RGB).
    build_marquee_frames — frames sliding the grid left-to-right across a track.
    build_palette — resolve ink colors from SVG/CSS sources.
    build_reveal_frames — stop-motion frames (row-by-row, optional dissolve).
    convert_colored — raster to colored cell grid.
    grid_from_image_path — load PNG path into trimmed grid.
    hex_to_rgb — parse CSS hex to RGB.
    load_bundled_logo_png — packaged ``logo-mark.png`` path.
    parse_palette_from_css — read tokens from ``colors.css``.
    parse_palette_from_svg — scrape fill/stroke hex from SVG.
    play_bundled_logo_animation — load bundled PNG and animate.
    play_frames — play frames on a TTY stream.
    render_ansi — true-color ANSI text.
    render_html — self-contained HTML preview.
    render_plain — monochrome block text.
    rgb_to_hex — format RGB as CSS hex.
    trim_grid — crop empty margins.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Literal, TextIO, cast

from PIL import Image

Transition = Literal["none", "dissolve"]
Mode = Literal["reveal", "marquee"]

_CHAR_ASPECT = 1.6
_SOLID_CHAR = "\u2588"
_BRAND_BACKGROUND_HEX = "#181513"
_BRAND_INK_HEX = ("#ff3b3b", "#5fb1f7", "#ffffff")

_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")
_CSS_VAR_RE = re.compile(r"--sevn-(?:primary|accent)(?:-[a-z]+)?:\s*(#[0-9a-fA-F]{3,8})\s*;")


@dataclass(frozen=True)
class LogoCell:
    """One ASCII grid cell."""

    ch: str
    r: int
    g: int
    b: int


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse a CSS hex color into RGB channels.

    Args:
        hex_color (str): CSS hex color string.

    Returns:
        tuple[int, int, int]: RGB channels.

    Examples:
        >>> hex_to_rgb("#ff3b3b")
        (255, 59, 59)
    """
    value = hex_color.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    number = int(value, 16)
    return (number >> 16) & 255, (number >> 8) & 255, number & 255


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Format RGB channels as a CSS hex color.

    Args:
        r (int): Red channel.
        g (int): Green channel.
        b (int): Blue channel.

    Returns:
        str: Lowercase CSS hex color.

    Examples:
        >>> rgb_to_hex(95, 177, 247)
        '#5fb1f7'
    """
    return "#" + "".join(f"{channel:02x}" for channel in (r, g, b))


BRAND_BACKGROUND = hex_to_rgb("#181513")
BRAND_INK_PALETTE: tuple[tuple[int, int, int], ...] = tuple(hex_to_rgb(h) for h in _BRAND_INK_HEX)


def parse_palette_from_svg(svg_path: Path) -> list[tuple[int, int, int]]:
    """Collect unique fill/stroke colors from an SVG file.

    Args:
        svg_path (Path): Brand SVG path.

    Returns:
        list[tuple[int, int, int]]: Colors in file order.

    Examples:
        >>> path = Path("styles/sevn/style/logos/logo-mark.svg")
        >>> rgb_to_hex(*parse_palette_from_svg(path)[0])
        '#4bacfb'
    """
    text = svg_path.read_text(encoding="utf-8")
    ordered: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()
    for hex_color in _HEX_RE.findall(text):
        rgb = hex_to_rgb(hex_color)
        if rgb not in seen:
            seen.add(rgb)
            ordered.append(rgb)
    return ordered


def parse_palette_from_css(css_path: Path) -> list[tuple[int, int, int]]:
    """Read brand ink colors from ``colors.css`` tokens.

    Args:
        css_path (Path): CSS token file path.

    Returns:
        list[tuple[int, int, int]]: Background, accent, primary, white.

    Examples:
        >>> path = Path("styles/sevn/style/tokens/colors.css")
        >>> rgb_to_hex(*parse_palette_from_css(path)[2])
        '#5fb1f7'
    """
    text = css_path.read_text(encoding="utf-8")
    tokens = _CSS_VAR_RE.findall(text)
    primary = hex_to_rgb(next(h for h in tokens if h.lower() == "#5fb1f7"))
    accent = hex_to_rgb(next(h for h in tokens if h.lower() == "#ff3b3b"))
    return [BRAND_BACKGROUND, accent, primary, (255, 255, 255)]


def build_palette(
    palette_svg: Path | None,
    palette_css: Path | None,
) -> tuple[list[tuple[int, int, int]], str]:
    """Resolve ink palette and HTML background hex.

    Args:
        palette_svg (Path | None): Optional SVG palette source.
        palette_css (Path | None): CSS token fallback.

    Returns:
        tuple[list[tuple[int, int, int]], str]: Ink colors and background hex.

    Examples:
        >>> colors, bg = build_palette(None, None)
        >>> bg
        '#181513'
    """
    if palette_svg is not None and palette_svg.is_file():
        raw = parse_palette_from_svg(palette_svg)
        background = raw[0] if raw else BRAND_BACKGROUND
        ink = list(raw[1:]) if len(raw) > 1 else list(BRAND_INK_PALETTE)
    elif palette_css is not None and palette_css.is_file():
        background, *ink = parse_palette_from_css(palette_css)
    else:
        background = BRAND_BACKGROUND
        ink = list(BRAND_INK_PALETTE)
    if (255, 255, 255) not in ink:
        ink.append((255, 255, 255))
    return ink, rgb_to_hex(*background)


def convert_colored(
    img: Image.Image,
    *,
    cols: int,
    ink_palette: list[tuple[int, int, int]],
    background: tuple[int, int, int],
) -> tuple[int, int, list[LogoCell]]:
    """Sample *img* into a solid-block colored grid.

    Args:
        img (Image.Image): Source logo raster.
        cols (int): Target character width.
        ink_palette (list[tuple[int, int, int]]): Brand ink colors.
        background (tuple[int, int, int]): Brand background RGB.

    Returns:
        tuple[int, int, list[LogoCell]]: Width, height, and cells.

    Examples:
        >>> img = Image.new("RGBA", (8, 8), (0, 0, 0, 255))
        >>> w, h, _cells = convert_colored(
        ...     img, cols=4, ink_palette=[(255, 59, 59)], background=(0, 0, 0)
        ... )
        >>> h >= 1
        True
    """
    w, h = img.size
    rows = max(1, round(cols * (h / w) / _CHAR_ASPECT))
    small = img.convert("RGBA").resize((cols, rows), Image.Resampling.LANCZOS)
    cells: list[LogoCell] = []
    for y in range(rows):
        for x in range(cols):
            r, g, b, a = cast("tuple[int, int, int, int]", small.getpixel((x, y)))
            is_blank = a < 32
            if not is_blank:
                lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
                if lum < 0.08:
                    is_blank = True
                else:
                    nearest_ink = min(
                        ink_palette,
                        key=lambda color: (
                            (r - color[0]) ** 2 + (g - color[1]) ** 2 + (b - color[2]) ** 2
                        ),
                    )
                    nearest_bg = min(
                        list(BRAND_INK_PALETTE),
                        key=lambda color: (
                            (r - color[0]) ** 2 + (g - color[1]) ** 2 + (b - color[2]) ** 2
                        ),
                    )
                    bg_dist = (
                        (r - background[0]) ** 2
                        + (g - background[1]) ** 2
                        + (b - background[2]) ** 2
                    )
                    ink_dist = (
                        (r - nearest_ink[0]) ** 2
                        + (g - nearest_ink[1]) ** 2
                        + (b - nearest_ink[2]) ** 2
                    )
                    is_blank = bg_dist < ink_dist and bg_dist < (
                        (r - nearest_bg[0]) ** 2
                        + (g - nearest_bg[1]) ** 2
                        + (b - nearest_bg[2]) ** 2
                    )
            if is_blank:
                cells.append(LogoCell(ch=" ", r=background[0], g=background[1], b=background[2]))
                continue
            ink = min(
                ink_palette,
                key=lambda color: (r - color[0]) ** 2 + (g - color[1]) ** 2 + (b - color[2]) ** 2,
            )
            cells.append(LogoCell(ch=_SOLID_CHAR, r=ink[0], g=ink[1], b=ink[2]))
    return cols, rows, cells


def trim_grid(cols: int, rows: int, cells: list[LogoCell]) -> tuple[int, int, list[LogoCell]]:
    """Drop empty outer rows and columns.

    Args:
        cols (int): Grid width.
        rows (int): Grid height.
        cells (list[LogoCell]): Flat cell list.

    Returns:
        tuple[int, int, list[LogoCell]]: Trimmed grid.

    Examples:
        >>> blank = LogoCell(" ", 0, 0, 0)
        >>> ink = LogoCell("x", 1, 2, 3)
        >>> trim_grid(2, 2, [blank, blank, blank, ink])
        (1, 1, [LogoCell(ch='x', r=1, g=2, b=3)])
    """
    used_rows = [y for y in range(rows) if any(cells[y * cols + x].ch != " " for x in range(cols))]
    if not used_rows:
        return cols, rows, cells
    used_cols = [x for x in range(cols) if any(cells[y * cols + x].ch != " " for y in used_rows)]
    trimmed = [cells[y * cols + x] for y in used_rows for x in used_cols]
    return len(used_cols), len(used_rows), trimmed


def render_plain(cols: int, rows: int, cells: list[LogoCell]) -> str:
    """Render a monochrome silhouette using solid block characters.

    Args:
        cols (int): Grid width.
        rows (int): Grid height.
        cells (list[LogoCell]): Colored cell grid.

    Returns:
        str: Plain-text ASCII art.

    Examples:
        >>> render_plain(1, 1, [LogoCell("x", 1, 2, 3)])
        'x\\n'
    """
    lines = ["".join(cells[y * cols + x].ch for x in range(cols)).rstrip() for y in range(rows)]
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


def render_ansi(
    cols: int,
    rows: int,
    cells: list[LogoCell],
    *,
    color: bool | None = None,
    trim_trailing_blank_lines: bool = True,
) -> str:
    """Render true-color ANSI text.

    Args:
        cols (int): Grid width.
        rows (int): Grid height.
        cells (list[LogoCell]): Colored cell grid.
        color (bool | None): Force color on/off; default follows TTY / NO_COLOR.
        trim_trailing_blank_lines (bool): Drop trailing whitespace-only rows for
            static output; keep ``False`` when frames must overwrite prior TTY ink.

    Returns:
        str: ANSI-colored or plain text.

    Examples:
        >>> "\\033[38;2;" in render_ansi(1, 1, [LogoCell("x", 255, 59, 59)], color=True)
        True
    """
    use_color = color
    if use_color is None:
        if os.environ.get("NO_COLOR"):
            use_color = False
        elif os.environ.get("FORCE_COLOR"):
            use_color = True
        else:
            use_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    reset = "\033[0m"
    lines: list[str] = []
    for y in range(rows):
        parts: list[str] = []
        prev: tuple[int, int, int] | None = None
        for x in range(cols):
            cell = cells[y * cols + x]
            if cell.ch == " ":
                parts.append(" ")
                prev = None
                continue
            rgb = (cell.r, cell.g, cell.b)
            if use_color and rgb != prev:
                parts.append(f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{cell.ch}")
                prev = rgb
            else:
                parts.append(cell.ch)
                if use_color:
                    prev = rgb
        lines.append("".join(parts) + (reset if use_color else ""))
    if trim_trailing_blank_lines:
        while lines and not lines[-1].strip():
            lines.pop()
    return "\n".join(lines) + "\n"


def render_html(
    cols: int,
    rows: int,
    cells: list[LogoCell],
    *,
    bg: str,
    palette_note: str = "sevn brand",
) -> str:
    """Write a self-contained colored HTML preview document.

    Args:
        cols (int): Grid width.
        rows (int): Grid height.
        cells (list[LogoCell]): Colored cell grid.
        bg (str): Page background CSS color.
        palette_note (str): Palette source note for HTML comment.

    Returns:
        str: Complete HTML document.

    Examples:
        >>> html = render_html(1, 1, [LogoCell("x", 95, 177, 247)], bg="#181513")
        >>> "95,177,247" in html
        True
    """
    rows_html: list[str] = []
    for y in range(rows):
        spans: list[str] = []
        for x in range(cols):
            cell = cells[y * cols + x]
            if cell.ch == " ":
                spans.append(" ")
                continue
            color = f"rgb({cell.r},{cell.g},{cell.b})"
            safe = cell.ch.replace("&", "&amp;").replace("<", "&lt;")
            spans.append(f'<span style="color:{color}">{safe}</span>')
        rows_html.append("".join(spans))
    body = "\n".join(rows_html)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>sevn logo — ASCII</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: {bg};
    }}
    pre {{
      margin: 0;
      padding: 1.5rem;
      font: 14px/1 "SF Mono", Menlo, Consolas, "Courier New", monospace;
      white-space: pre;
    }}
  </style>
</head>
<body><!-- palette: {palette_note} --><pre>{body}</pre></body>
</html>
"""


def build_reveal_frames(
    cols: int,
    rows: int,
    cells: list[LogoCell],
    *,
    background: tuple[int, int, int],
    transition: Transition = "none",
) -> list[list[LogoCell]]:
    """Build stop-motion frames that reveal the logo row-by-row.

    ``none`` adds one frame per row. ``dissolve`` staggers characters left-to-right
    within each newly revealed row (ascii-editor dissolve analogue).

    Args:
        cols (int): Grid width.
        rows (int): Grid height.
        cells (list[LogoCell]): Final colored grid.
        background (tuple[int, int, int]): Blank cell RGB.
        transition (Transition): ``none`` or ``dissolve``.

    Returns:
        list[list[LogoCell]]: Frame cell lists (same length each).

    Examples:
        >>> c = LogoCell("x", 1, 2, 3)
        >>> b = LogoCell(" ", 0, 0, 0)
        >>> frames = build_reveal_frames(1, 1, [c], background=(0, 0, 0))
        >>> len(frames)
        1
        >>> frames[0][0].ch
        'x'
    """
    blank = LogoCell(ch=" ", r=background[0], g=background[1], b=background[2])
    frames: list[list[LogoCell]] = []

    def _frame_through(max_row: int, max_col_in_row: int | None = None) -> list[LogoCell]:
        out: list[LogoCell] = []
        for y in range(rows):
            for x in range(cols):
                idx = y * cols + x
                if y < max_row:
                    out.append(cells[idx])
                elif y == max_row:
                    if max_col_in_row is None or x <= max_col_in_row:
                        out.append(cells[idx])
                    else:
                        out.append(blank)
                else:
                    out.append(blank)
        return out

    for row in range(rows):
        if transition == "dissolve":
            for col in range(cols):
                frames.append(_frame_through(row, col))
        else:
            frames.append(_frame_through(row, None))
    return frames


def build_marquee_frames(
    cols: int,
    rows: int,
    cells: list[LogoCell],
    *,
    background: tuple[int, int, int],
    track_cols: int,
    step: int = 2,
) -> list[list[LogoCell]]:
    """Build frames sliding the full logo left-to-right across a wider track.

    Each frame is a ``track_cols x rows`` grid with the logo drawn at an
    increasing horizontal offset, so the mark enters from the left edge and
    exits off the right edge. Larger *step* moves the mark faster.

    Args:
        cols (int): Logo grid width.
        rows (int): Logo grid height.
        cells (list[LogoCell]): Final colored logo grid.
        background (tuple[int, int, int]): Blank cell RGB.
        track_cols (int): Total travel width (usually terminal columns).
        step (int): Columns advanced per frame.

    Returns:
        list[list[LogoCell]]: Frame cell lists, each ``track_cols * rows`` long.

    Examples:
        >>> c = LogoCell("x", 1, 2, 3)
        >>> frames = build_marquee_frames(1, 1, [c], background=(0, 0, 0), track_cols=3, step=1)
        >>> len(frames)
        6
        >>> frames[1][0].ch
        'x'
        >>> frames[-1][0].ch
        ' '
    """
    blank = LogoCell(ch=" ", r=background[0], g=background[1], b=background[2])
    travel = max(1, step)
    frames: list[list[LogoCell]] = []
    offset = -cols
    while offset <= track_cols:
        frame = [blank] * (track_cols * rows)
        for y in range(rows):
            for x in range(cols):
                tx = offset + x
                if 0 <= tx < track_cols:
                    frame[y * track_cols + tx] = cells[y * cols + x]
        frames.append(frame)
        offset += travel
    frames.append([blank] * (track_cols * rows))
    return frames


def _marquee_track_cols(explicit: int | None = None) -> int:
    """Return a marquee track width that avoids terminal wrap on the last column.

    Args:
        explicit (int | None): Override width; ``0`` or ``None`` uses the terminal.

    Returns:
        int: At least one column, one shy of the requested width.

    Examples:
        >>> _marquee_track_cols(80)
        79
    """
    width = explicit or shutil.get_terminal_size(fallback=(80, 24)).columns
    return max(1, width - 1)


def play_frames(
    cols: int,
    rows: int,
    frames: list[list[LogoCell]],
    *,
    fps: float = 6.0,
    stream: TextIO | None = None,
    color: bool | None = None,
    hold_final_s: float = 0.35,
    restore_newline: bool = False,
) -> None:
    """Play reveal frames on a TTY (cursor home, hide/show cursor).

    Args:
        cols (int): Grid width.
        rows (int): Grid height.
        frames (list[list[LogoCell]]): Animation frames.
        fps (float): Frames per second.
        stream (TextIO | None): Output stream; defaults to stdout.
        color (bool | None): ANSI color override.
        hold_final_s (float): Pause on the last frame before returning.
        restore_newline (bool): Clear splash rows and leave the cursor on a fresh
            line below (marquee exit hygiene).

    Examples:
        >>> play_frames(1, 1, [[LogoCell("x", 1, 2, 3)]], fps=24.0, stream=open(os.devnull, "w", encoding="utf-8"))  # doctest: +SKIP
    """
    if not frames:
        return
    out = stream or sys.stdout
    interval = 1.0 / max(fps, 0.1)
    hide = "\033[?25l"
    show = "\033[?25h"
    out.write(hide)
    out.flush()
    try:
        for index, frame in enumerate(frames):
            out.write("\033[H")
            out.write(render_ansi(cols, rows, frame, color=color, trim_trailing_blank_lines=False))
            out.flush()
            if index < len(frames) - 1:
                time.sleep(interval)
        if hold_final_s > 0:
            time.sleep(hold_final_s)
    finally:
        if restore_newline and rows > 0:
            out.write("\033[H")
            for _row in range(rows):
                out.write("\033[2K\r\n")
        out.write(show)
        out.flush()


def load_bundled_logo_png() -> Path:
    """Return a filesystem path to the packaged ``logo-mark.png``.

    Returns:
        Path: Extracted or cached bundled asset path.

    Raises:
        FileNotFoundError: When the packaged asset is missing.

    Examples:
        >>> path = load_bundled_logo_png()
        >>> path.name
        'logo-mark.png'
    """
    ref = resources.files("sevn.data") / "branding/logo-mark.png"
    with resources.as_file(ref) as path:
        return Path(path)


def grid_from_image_path(
    image_path: Path,
    *,
    cols: int = 56,
    palette_svg: Path | None = None,
    palette_css: Path | None = None,
) -> tuple[int, int, list[LogoCell], str]:
    """Load a PNG and return a trimmed colored grid.

    Args:
        image_path (Path): Logo raster path.
        cols (int): Target character width.
        palette_svg (Path | None): Optional SVG palette source.
        palette_css (Path | None): Optional CSS palette source.

    Returns:
        tuple[int, int, list[LogoCell], str]: Width, height, cells, background hex.

    Examples:
        >>> path = load_bundled_logo_png()
        >>> w, h, cells, bg = grid_from_image_path(path, cols=32)
        >>> bg
        '#181513'
    """
    ink, bg_hex = build_palette(palette_svg, palette_css)
    background = hex_to_rgb(bg_hex)
    with Image.open(image_path) as img:
        width, height, cells = convert_colored(
            img,
            cols=cols,
            ink_palette=ink,
            background=background,
        )
    width, height, cells = trim_grid(width, height, cells)
    return width, height, cells, bg_hex


def play_bundled_logo_animation(
    *,
    cols: int = 56,
    fps: float = 6.0,
    transition: Transition = "none",
    stream: TextIO | None = None,
    mode: Mode = "reveal",
    track_cols: int | None = None,
    step: int = 2,
) -> None:
    """Load the bundled logo and play a row-reveal or left-to-right marquee.

    ``reveal`` reveals the full logo row-by-row (optionally with ``dissolve``).
    ``marquee`` slides the small logo fast across the terminal width.

    Args:
        cols (int): Character width of the rendered logo.
        fps (float): Frames per second.
        transition (Transition): ``none`` or ``dissolve`` (``reveal`` mode only).
        stream (TextIO | None): Output stream.
        mode (Mode): ``reveal`` (row cut) or ``marquee`` (slide left-to-right).
        track_cols (int | None): Marquee travel width; defaults to terminal width.
        step (int): Marquee columns advanced per frame (higher is faster).

    Examples:
        >>> play_bundled_logo_animation(stream=open(os.devnull, "w", encoding="utf-8"))  # doctest: +SKIP
    """
    path = load_bundled_logo_png()
    ink, _bg_hex = build_palette(None, None)
    background = BRAND_BACKGROUND
    with Image.open(path) as img:
        width, height, cells = convert_colored(
            img,
            cols=cols,
            ink_palette=ink,
            background=background,
        )
    width, height, cells = trim_grid(width, height, cells)
    if mode == "marquee":
        track = _marquee_track_cols(track_cols)
        marquee = build_marquee_frames(
            width,
            height,
            cells,
            background=background,
            track_cols=track,
            step=step,
        )
        play_frames(
            track,
            height,
            marquee,
            fps=fps,
            stream=stream,
            hold_final_s=0.0,
            restore_newline=True,
        )
        return
    frames = build_reveal_frames(
        width,
        height,
        cells,
        background=background,
        transition=transition,
    )
    play_frames(width, height, frames, fps=fps, stream=stream)


__all__ = [
    "BRAND_BACKGROUND",
    "BRAND_INK_PALETTE",
    "LogoCell",
    "Mode",
    "Transition",
    "build_marquee_frames",
    "build_palette",
    "build_reveal_frames",
    "convert_colored",
    "grid_from_image_path",
    "hex_to_rgb",
    "load_bundled_logo_png",
    "parse_palette_from_css",
    "parse_palette_from_svg",
    "play_bundled_logo_animation",
    "play_frames",
    "render_ansi",
    "render_html",
    "render_plain",
    "rgb_to_hex",
    "trim_grid",
]
